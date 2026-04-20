from __future__ import annotations

from dataclasses import dataclass
import socket
import ssl
import threading
from urllib.parse import unquote, urlparse


DEFAULT_PORT = 6379
DEFAULT_SOCKET_TIMEOUT_SECONDS = 5.0


class RedisClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RedisConnectionConfig:
    host: str
    port: int
    db: int
    username: str | None
    password: str | None
    use_ssl: bool
    socket_timeout_seconds: float


class RedisConnection:
    def __init__(self, config: RedisConnectionConfig) -> None:
        self._config = config
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._reader = None

    def execute(self, *parts: object) -> object:
        if self._socket is None or self._reader is None:
            self._connect()
        return self._execute_connected(*parts)

    def close(self) -> None:
        reader = self._reader
        sock = self._socket
        self._reader = None
        self._socket = None
        if reader is not None:
            try:
                reader.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._config.host, self._config.port),
            timeout=self._config.socket_timeout_seconds,
        )
        raw_socket.settimeout(self._config.socket_timeout_seconds)
        if self._config.use_ssl:
            context = ssl.create_default_context()
            wrapped_socket = context.wrap_socket(
                raw_socket,
                server_hostname=self._config.host,
            )
            wrapped_socket.settimeout(self._config.socket_timeout_seconds)
            sock: socket.socket | ssl.SSLSocket = wrapped_socket
        else:
            sock = raw_socket
        reader = sock.makefile("rb")
        self._socket = sock
        self._reader = reader
        try:
            if self._config.password is not None or self._config.username is not None:
                if self._config.username is not None:
                    self._execute_connected(
                        "AUTH",
                        self._config.username,
                        self._config.password or "",
                    )
                elif self._config.password is not None:
                    self._execute_connected("AUTH", self._config.password)
            if self._config.db:
                self._execute_connected("SELECT", str(self._config.db))
        except Exception:
            self.close()
            raise

    def _execute_connected(self, *parts: object) -> object:
        sock = self._socket
        reader = self._reader
        if sock is None or reader is None:
            raise RedisClientError("redis connection is not established")
        try:
            sock.sendall(_encode_command(parts))
            return _read_response(reader)
        except (OSError, ValueError, ssl.SSLError) as exc:
            self.close()
            raise RedisClientError(f"redis command failed: {exc}") from exc


class RedisClient:
    def __init__(
        self,
        redis_url: str,
        *,
        max_connections: int = 8,
        socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
    ) -> None:
        self._config = parse_redis_url(
            redis_url,
            socket_timeout_seconds=socket_timeout_seconds,
        )
        self._max_connections = max(1, max_connections)
        self._condition = threading.Condition()
        self._idle_connections: list[RedisConnection] = []
        self._open_connections = 0

    def execute(self, *parts: object) -> object:
        connection = self._acquire_connection()
        try:
            response = connection.execute(*parts)
        except RedisClientError:
            self._discard_connection(connection)
            raise
        except Exception as exc:  # pragma: no cover - safety net
            self._discard_connection(connection)
            raise RedisClientError(f"unexpected redis client failure: {exc}") from exc
        self._release_connection(connection)
        return response

    def close(self) -> None:
        with self._condition:
            connections = list(self._idle_connections)
            self._idle_connections.clear()
            self._open_connections = 0
        for connection in connections:
            connection.close()

    def _acquire_connection(self) -> RedisConnection:
        with self._condition:
            while True:
                if self._idle_connections:
                    return self._idle_connections.pop()
                if self._open_connections < self._max_connections:
                    self._open_connections += 1
                    return RedisConnection(self._config)
                self._condition.wait(timeout=self._config.socket_timeout_seconds)

    def _release_connection(self, connection: RedisConnection) -> None:
        with self._condition:
            self._idle_connections.append(connection)
            self._condition.notify()

    def _discard_connection(self, connection: RedisConnection) -> None:
        connection.close()
        with self._condition:
            self._open_connections = max(0, self._open_connections - 1)
            self._condition.notify()


def parse_redis_url(
    redis_url: str,
    *,
    socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
) -> RedisConnectionConfig:
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError(f"unsupported redis url scheme: {parsed.scheme or '(empty)'}")
    if not parsed.hostname:
        raise ValueError("redis url host is required")
    database = 0
    if parsed.path and parsed.path != "/":
        try:
            database = int(parsed.path.lstrip("/"))
        except ValueError as exc:
            raise ValueError(f"invalid redis database index: {parsed.path}") from exc
    username = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password) if parsed.password is not None else None
    return RedisConnectionConfig(
        host=parsed.hostname,
        port=parsed.port or DEFAULT_PORT,
        db=database,
        username=username,
        password=password,
        use_ssl=parsed.scheme == "rediss",
        socket_timeout_seconds=max(0.5, socket_timeout_seconds),
    )


def _encode_command(parts: tuple[object, ...]) -> bytes:
    encoded_parts = [_encode_bulk_string(part) for part in parts]
    return b"*" + str(len(encoded_parts)).encode("ascii") + b"\r\n" + b"".join(encoded_parts)


def _encode_bulk_string(value: object) -> bytes:
    if isinstance(value, bytes):
        payload = value
    elif value is None:
        payload = b""
    else:
        payload = str(value).encode("utf-8")
    return b"$" + str(len(payload)).encode("ascii") + b"\r\n" + payload + b"\r\n"


def _read_response(reader) -> object:
    prefix = reader.read(1)
    if not prefix:
        raise RedisClientError("redis connection closed")
    if prefix == b"+":
        return _readline(reader).decode("utf-8", errors="replace")
    if prefix == b"-":
        message = _readline(reader).decode("utf-8", errors="replace")
        raise RedisClientError(message)
    if prefix == b":":
        return int(_readline(reader))
    if prefix == b"$":
        length = int(_readline(reader))
        if length < 0:
            return None
        payload = _read_exact(reader, length)
        _read_exact(reader, 2)
        return payload.decode("utf-8", errors="replace")
    if prefix == b"*":
        count = int(_readline(reader))
        if count < 0:
            return None
        return [_read_response(reader) for _ in range(count)]
    if prefix == b"_":
        _read_exact(reader, 2)
        return None
    if prefix == b"#":
        value = _read_exact(reader, 1)
        _read_exact(reader, 2)
        return value == b"t"
    raise RedisClientError(f"unsupported redis response prefix: {prefix!r}")


def _readline(reader) -> bytes:
    line = reader.readline()
    if not line or not line.endswith(b"\r\n"):
        raise RedisClientError("malformed redis response line")
    return line[:-2]


def _read_exact(reader, size: int) -> bytes:
    payload = reader.read(size)
    if payload is None or len(payload) != size:
        raise RedisClientError("unexpected end of redis response")
    return payload
