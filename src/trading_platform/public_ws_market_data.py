from __future__ import annotations

from datetime import UTC, datetime
import time
import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
from urllib.parse import urlparse
from uuid import uuid4

from .market_data_connector import MarketDataError, PublicMarketDataConnector


def _iso_from_epoch_ms(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        raw_timestamp = int(str(value))
    except ValueError:
        return None
    magnitude = abs(raw_timestamp)
    if magnitude >= 10_000_000_000_000_000:
        timestamp_seconds = raw_timestamp / 1_000_000_000
    elif magnitude >= 10_000_000_000_000:
        timestamp_seconds = raw_timestamp / 1_000_000
    elif magnitude >= 10_000_000_000:
        timestamp_seconds = raw_timestamp / 1000
    else:
        timestamp_seconds = float(raw_timestamp)
    try:
        return datetime.fromtimestamp(timestamp_seconds, tz=UTC).isoformat().replace(
            "+00:00", "Z"
        )
    except (OverflowError, OSError, ValueError):
        return None


class PublicWebSocketMarketDataConnector(PublicMarketDataConnector):
    def __init__(
        self,
        *,
        timeout_ms: int,
        stale_threshold_ms: int,
        orderbook_depth_levels: int = 5,
        retry_count: int,
        retry_backoff,
        rate_limit_policies: dict[str, object] | None,
        upbit_base_url: str,
        bithumb_base_url: str,
        coinone_base_url: str,
        upbit_ws_url: str = "wss://api.upbit.com/websocket/v1",
        bithumb_ws_url: str = "wss://ws-api.bithumb.com/websocket/v1",
        coinone_ws_url: str = "wss://stream.coinone.co.kr",
    ) -> None:
        super().__init__(
            timeout_ms=timeout_ms,
            stale_threshold_ms=stale_threshold_ms,
            orderbook_depth_levels=orderbook_depth_levels,
            retry_count=retry_count,
            retry_backoff=retry_backoff,
            rate_limit_policies=rate_limit_policies,
            upbit_base_url=upbit_base_url,
            bithumb_base_url=bithumb_base_url,
            coinone_base_url=coinone_base_url,
        )
        self.upbit_ws_url = upbit_ws_url
        self.bithumb_ws_url = bithumb_ws_url
        self.coinone_ws_url = coinone_ws_url

    @property
    def supported_ws_exchanges(self) -> tuple[str, ...]:
        return ("upbit", "bithumb", "coinone")

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        normalized_exchange = exchange.strip().lower()
        normalized_market = market.strip().upper()
        if normalized_exchange == "upbit":
            snapshot = self._get_upbit_orderbook_top_ws(normalized_market)
        elif normalized_exchange == "bithumb":
            snapshot = self._get_bithumb_orderbook_top_ws(normalized_market)
        elif normalized_exchange == "coinone":
            snapshot = self._get_coinone_orderbook_top_ws(normalized_market)
        else:
            raise MarketDataError(
                status=self._unsupported_status(),
                code="EXCHANGE_NOT_SUPPORTED",
                message=(
                    "public websocket sim supports only upbit, bithumb, and coinone; "
                    f"got exchange={normalized_exchange or '(empty)'}"
                ),
            )
        self.sync_cached_orderbook_top(snapshot=snapshot)
        return dict(snapshot)

    def _unsupported_status(self):
        from http import HTTPStatus

        return HTTPStatus.BAD_REQUEST

    def _get_upbit_orderbook_top_ws(self, market: str) -> dict[str, object]:
        request_payload = [
            {"ticket": f"tp-ws-{uuid4().hex[:12]}"},
            {
                "type": "orderbook",
                "codes": [self._upbit_market_with_depth(market)],
                "is_only_snapshot": True,
            },
            {"format": "DEFAULT"},
        ]
        with _WebSocketJsonClient(self.upbit_ws_url, timeout_seconds=self.timeout_seconds) as client:
            client.send_json(request_payload)
            payload = client.recv_json()
        if not isinstance(payload, dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "upbit websocket response has invalid shape",
            )
        units = payload.get("orderbook_units")
        if not isinstance(units, list) or not units or not isinstance(units[0], dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "upbit websocket response is missing orderbook_units",
            )
        asks = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="ask_price",
            quantity_key="ask_size",
        )
        bids = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="bid_price",
            quantity_key="bid_size",
        )
        return self._build_snapshot(
            exchange="upbit",
            market=str(payload.get("code") or market),
            bids=bids,
            asks=asks,
            exchange_timestamp=_iso_from_epoch_ms(payload.get("timestamp")),
            source_type="public_ws",
        )

    def _get_bithumb_orderbook_top_ws(self, market: str) -> dict[str, object]:
        request_payload = [
            {"ticket": f"tp-ws-{uuid4().hex[:12]}"},
            {
                "type": "orderbook",
                "codes": [market],
                "isOnlySnapshot": True,
            },
            {"format": "DEFAULT"},
        ]
        with _WebSocketJsonClient(self.bithumb_ws_url, timeout_seconds=self.timeout_seconds) as client:
            client.send_json(request_payload)
            payload = client.recv_json()
        if not isinstance(payload, dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "bithumb websocket response has invalid shape",
            )
        units = payload.get("orderbook_units")
        if not isinstance(units, list) or not units or not isinstance(units[0], dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "bithumb websocket response is missing orderbook_units",
            )
        asks = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="ask_price",
            quantity_key="ask_size",
        )
        bids = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="bid_price",
            quantity_key="bid_size",
        )
        return self._build_snapshot(
            exchange="bithumb",
            market=str(payload.get("code") or market),
            bids=bids,
            asks=asks,
            exchange_timestamp=_iso_from_epoch_ms(payload.get("timestamp")),
            source_type="public_ws",
        )

    def _get_coinone_orderbook_top_ws(self, market: str) -> dict[str, object]:
        quote_currency, target_currency = self._coinone_market_parts(market)
        request_payload = {
            "request_type": "SUBSCRIBE",
            "channel": "ORDERBOOK",
            "topic": {
                "quote_currency": quote_currency,
                "target_currency": target_currency,
            },
        }
        with _WebSocketJsonClient(self.coinone_ws_url, timeout_seconds=self.timeout_seconds) as client:
            client.send_json(request_payload)
            payload = client.recv_json_until(self._coinone_orderbook_stream)
        if not isinstance(payload, dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "coinone websocket response has invalid shape",
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "coinone websocket response is missing data",
            )
        bids = data.get("b") if isinstance(data.get("b"), list) else data.get("bids")
        asks = data.get("a") if isinstance(data.get("a"), list) else data.get("asks")
        if (
            not isinstance(bids, list)
            or not bids
            or not isinstance(bids[0], dict)
            or not isinstance(asks, list)
            or not asks
            or not isinstance(asks[0], dict)
        ):
            raise MarketDataError(
                self._unsupported_status(),
                "UPSTREAM_INVALID_RESPONSE",
                "coinone websocket response is missing bids or asks",
            )
        normalized_bids = self._normalize_levels(
            list(bids[: self.orderbook_depth_levels]),
            price_key="p" if "p" in bids[0] else "price",
            quantity_key="q" if "q" in bids[0] else "qty",
        )
        normalized_asks = self._normalize_levels(
            list(asks[: self.orderbook_depth_levels]),
            price_key="p" if "p" in asks[0] else "price",
            quantity_key="q" if "q" in asks[0] else "qty",
        )
        return self._build_snapshot(
            exchange="coinone",
            market=f"{quote_currency}-{target_currency}",
            bids=normalized_bids,
            asks=normalized_asks,
            exchange_timestamp=_iso_from_epoch_ms(data.get("t") or data.get("timestamp")),
            source_type="public_ws",
        )

    def _coinone_orderbook_stream(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        response_type = str(payload.get("response_type") or payload.get("r") or "").strip().upper()
        channel = str(payload.get("channel") or payload.get("c") or "").strip().upper()
        return response_type == "DATA" and channel == "ORDERBOOK"

    def _upbit_market_with_depth(self, market: str) -> str:
        depth = self.orderbook_depth_levels
        for supported in (1, 5, 15, 30):
            if depth <= supported:
                return f"{market}.{supported}"
        return f"{market}.30"


class _WebSocketJsonClient:
    def __init__(self, url: str, *, timeout_seconds: float) -> None:
        self._url = url
        self._timeout_seconds = max(timeout_seconds, 0.5)
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._connected = False

    def __enter__(self) -> _WebSocketJsonClient:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._connected:
            return
        parsed = urlparse(self._url)
        if parsed.scheme not in {"ws", "wss"}:
            raise RuntimeError(f"unsupported websocket scheme: {parsed.scheme or '(empty)'}")
        host = parsed.hostname
        if not host:
            raise RuntimeError("websocket host is required")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=self._timeout_seconds)
        sock.settimeout(self._timeout_seconds)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            wrapped = context.wrap_socket(sock, server_hostname=host)
            wrapped.settimeout(self._timeout_seconds)
            connection: socket.socket | ssl.SSLSocket = wrapped
        else:
            connection = sock
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: work_v6_codex-public-ws/0.1\r\n\r\n"
        )
        connection.sendall(request.encode("ascii"))
        response = self._read_http_response(connection)
        if not response.startswith("HTTP/1.1 101") and not response.startswith("HTTP/1.0 101"):
            connection.close()
            raise RuntimeError(f"websocket handshake failed: {response.splitlines()[0] if response else 'empty response'}")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        headers = self._parse_headers(response)
        if headers.get("sec-websocket-accept", "") != expected_accept:
            connection.close()
            raise RuntimeError("websocket handshake accept mismatch")
        self._socket = connection
        self._connected = True

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        self._connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def send_json(self, payload: object) -> None:
        self.send_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))

    def send_text(self, payload: str) -> None:
        self._send_frame(opcode=0x1, payload=payload.encode("utf-8"))

    def recv_json(self) -> object:
        return json.loads(self.recv_text())

    def recv_json_until(self, predicate) -> object:
        deadline = _deadline_monotonic(self._timeout_seconds)
        while True:
            remaining = max(deadline - time.monotonic(), 0.1)
            if self._socket is not None:
                self._socket.settimeout(remaining)
            payload = self.recv_json()
            if predicate(payload):
                return payload

    def recv_text(self) -> str:
        fragments: list[bytes] = []
        opcode = None
        while True:
            current_opcode, payload, fin = self._recv_frame()
            if current_opcode == 0x9:
                self._send_frame(opcode=0xA, payload=payload)
                continue
            if current_opcode == 0xA:
                continue
            if current_opcode == 0x8:
                raise RuntimeError("websocket closed by server")
            if current_opcode in {0x1, 0x2} and opcode is None:
                opcode = current_opcode
                fragments.append(payload)
            elif current_opcode == 0x0 and opcode is not None:
                fragments.append(payload)
            else:
                raise RuntimeError(f"unsupported websocket opcode: {current_opcode}")
            if fin:
                break
        message = b"".join(fragments)
        return message.decode("utf-8")

    def _send_frame(self, *, opcode: int, payload: bytes) -> None:
        sock = self._require_socket()
        fin_opcode = 0x80 | (opcode & 0x0F)
        mask_key = secrets.token_bytes(4)
        payload_length = len(payload)
        if payload_length < 126:
            header = bytes([fin_opcode, 0x80 | payload_length])
        elif payload_length <= 0xFFFF:
            header = bytes([fin_opcode, 0x80 | 126]) + payload_length.to_bytes(2, "big")
        else:
            header = bytes([fin_opcode, 0x80 | 127]) + payload_length.to_bytes(8, "big")
        masked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        sock.sendall(header + mask_key + masked)

    def _recv_frame(self) -> tuple[int, bytes, bool]:
        sock = self._require_socket()
        header = self._read_exact(sock, 2)
        first, second = header[0], header[1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        payload_length = second & 0x7F
        if payload_length == 126:
            payload_length = int.from_bytes(self._read_exact(sock, 2), "big")
        elif payload_length == 127:
            payload_length = int.from_bytes(self._read_exact(sock, 8), "big")
        mask_key = self._read_exact(sock, 4) if masked else b""
        payload = self._read_exact(sock, payload_length) if payload_length else b""
        if masked:
            payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        return opcode, payload, fin

    def _read_http_response(self, sock: socket.socket | ssl.SSLSocket) -> str:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > 65536:
                raise RuntimeError("websocket handshake response too large")
        return buffer.decode("utf-8", errors="replace")

    def _parse_headers(self, response: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for line in response.split("\r\n")[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        return headers

    def _read_exact(self, sock: socket.socket | ssl.SSLSocket, size: int) -> bytes:
        payload = bytearray()
        while len(payload) < size:
            chunk = sock.recv(size - len(payload))
            if not chunk:
                raise RuntimeError("unexpected websocket eof")
            payload.extend(chunk)
        return bytes(payload)

    def _require_socket(self) -> socket.socket | ssl.SSLSocket:
        if self._socket is None:
            raise RuntimeError("websocket is not connected")
        return self._socket


def _deadline_monotonic(timeout_seconds: float) -> float:
    return time.monotonic() + max(timeout_seconds, 0.5)
