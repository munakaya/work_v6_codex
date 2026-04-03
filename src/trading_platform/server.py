from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .config import AppConfig
from .storage.dependencies import postgres_status, redis_status
from .storage.read_store import MemoryReadStore, build_read_store


LOGGER = logging.getLogger(__name__)


class ControlPlaneServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        config: AppConfig,
        read_store: MemoryReadStore,
    ):
        super().__init__(server_address, ControlPlaneRequestHandler)
        self.config = config
        self.read_store = read_store


class ControlPlaneRequestHandler(BaseHTTPRequestHandler):
    server: ControlPlaneServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/v1/health":
            self._write_json(HTTPStatus.OK, self._health_payload())
            return

        if parsed.path == "/api/v1/ready":
            status_code, payload = self._ready_response()
            self._write_json(status_code, payload)
            return

        if parsed.path == "/api/v1/bots":
            self._write_json(HTTPStatus.OK, self._bots_response(parsed.query))
            return

        if parsed.path == "/api/v1/alerts":
            self._write_json(HTTPStatus.OK, self._alerts_response(parsed.query))
            return

        bot_heartbeats_response = self._match_bot_heartbeats(parsed.path, parsed.query)
        if bot_heartbeats_response is not None:
            status_code, payload = bot_heartbeats_response
            self._write_json(status_code, payload)
            return

        bot_detail_response = self._match_bot_detail(parsed.path)
        if bot_detail_response is not None:
            status_code, payload = bot_detail_response
            self._write_json(status_code, payload)
            return

        self._write_json(
            HTTPStatus.NOT_FOUND,
            self._response(error={"code": "NOT_FOUND", "message": "route not found"}),
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/v1/bots/register":
            status_code, payload = self._register_bot_response()
            self._write_json(status_code, payload)
            return

        heartbeat_response = self._record_heartbeat_response(parsed.path)
        if heartbeat_response is not None:
            status_code, payload = heartbeat_response
            self._write_json(status_code, payload)
            return

        self._write_json(
            HTTPStatus.NOT_FOUND,
            self._response(error={"code": "NOT_FOUND", "message": "route not found"}),
        )

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], format % args)

    def _health_payload(self) -> dict[str, Any]:
        config = self.server.config
        return self._response(
            data={
                "status": "ok",
                "service": config.service_name,
                "version": config.service_version,
            }
        )

    def _ready_response(self) -> tuple[HTTPStatus, dict[str, Any]]:
        config = self.server.config
        dependencies = {
            "postgres": postgres_status(config.postgres_dsn).as_dict(),
            "redis": redis_status(config.redis_url).as_dict(),
        }
        ready = all(
            bool(dep["configured"]) and bool(dep["reachable"]) for dep in dependencies.values()
        )
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        payload = self._response(
            data={
                "status": "ok" if ready else "degraded",
                "service": config.service_name,
                "redis_key_prefix": config.redis_key_prefix,
                "dependencies": dependencies,
            }
        )
        return status, payload

    def _register_bot_response(self) -> tuple[HTTPStatus, dict[str, Any]]:
        body, error = self._read_json_body()
        if error is not None:
            return error

        required = ["bot_key", "strategy_name", "mode"]
        missing = [key for key in required if not body.get(key)]
        if missing:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"missing required fields: {', '.join(missing)}",
                    }
                ),
            )

        result = self.server.read_store.register_bot(
            bot_key=str(body["bot_key"]),
            strategy_name=str(body["strategy_name"]),
            mode=str(body["mode"]),
            hostname=_optional_string(body.get("hostname")),
        )
        return HTTPStatus.OK, self._response(data=result)

    def _record_heartbeat_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, Any]] | None:
        prefix = "/api/v1/bots/"
        suffix = "/heartbeat"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        bot_id = path[len(prefix) : -len(suffix)]
        if not bot_id:
            return None

        body, error = self._read_json_body()
        if error is not None:
            return error

        required = [
            "is_process_alive",
            "is_market_data_alive",
            "is_ordering_alive",
        ]
        missing = [key for key in required if key not in body]
        if missing:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"missing required fields: {', '.join(missing)}",
                    }
                ),
            )

        invalid_bool_fields = [
            key for key in required if not isinstance(body.get(key), bool)
        ]
        if invalid_bool_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"fields must be boolean: {', '.join(invalid_bool_fields)}",
                    }
                ),
            )

        result = self.server.read_store.record_heartbeat(
            bot_id=bot_id,
            is_process_alive=body["is_process_alive"],
            is_market_data_alive=body["is_market_data_alive"],
            is_ordering_alive=body["is_ordering_alive"],
            lag_ms=_optional_int(body.get("lag_ms")),
            context=_optional_object(body.get("context")),
        )
        if result is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        return HTTPStatus.ACCEPTED, self._response(data=result)

    def _bots_response(self, query: str) -> dict[str, Any]:
        params = parse_qs(query)
        bots = self.server.read_store.list_bots(
            status=_single_query_value(params, "status"),
            strategy_name=_single_query_value(params, "strategy_name"),
            mode=_single_query_value(params, "mode"),
        )
        return self._response(data={"items": bots, "count": len(bots)})

    def _alerts_response(self, query: str) -> dict[str, Any]:
        params = parse_qs(query)
        acknowledged = _optional_bool(_single_query_value(params, "acknowledged"))
        alerts = self.server.read_store.list_alerts(
            bot_id=_single_query_value(params, "bot_id"),
            level=_single_query_value(params, "level"),
            acknowledged=acknowledged,
        )
        return self._response(data={"items": alerts, "count": len(alerts)})

    def _match_bot_detail(self, path: str) -> tuple[HTTPStatus, dict[str, Any]] | None:
        prefix = "/api/v1/bots/"
        if not path.startswith(prefix):
            return None

        suffix = path[len(prefix) :]
        if "/" in suffix or not suffix:
            return None

        detail = self.server.read_store.get_bot_detail(suffix)
        if detail is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data=detail)

    def _match_bot_heartbeats(
        self, path: str, query: str
    ) -> tuple[HTTPStatus, dict[str, Any]] | None:
        prefix = "/api/v1/bots/"
        suffix = "/heartbeats"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        bot_id = path[len(prefix) : -len(suffix)]
        if not bot_id:
            return None

        params = parse_qs(query)
        limit = _query_limit(params)
        heartbeats = self.server.read_store.list_heartbeats(bot_id, limit=limit)
        if heartbeats is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data={"items": heartbeats, "count": len(heartbeats)})

    def _response(
        self,
        data: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "success": error is None,
            "data": data,
            "error": error,
            "request_id": str(uuid4()),
        }

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(
        self,
    ) -> tuple[dict[str, Any], tuple[HTTPStatus, dict[str, Any]] | None]:
        length_header = self.headers.get("Content-Length")
        if not length_header:
            return {}, (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={"code": "INVALID_REQUEST", "message": "missing request body"}
                ),
            )

        try:
            length = int(length_header)
        except ValueError:
            return {}, (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "invalid content length",
                    }
                ),
            )

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}, (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={"code": "INVALID_JSON", "message": "request body is not valid json"}
                ),
            )

        if not isinstance(payload, dict):
            return {}, (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={"code": "INVALID_REQUEST", "message": "request body must be an object"}
                ),
            )
        return payload, None


def build_server(config: AppConfig) -> ControlPlaneServer:
    LOGGER.debug("building control plane server with config: %s", asdict(config))
    return ControlPlaneServer((config.host, config.port), config, build_read_store(config))


def _single_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _query_limit(params: dict[str, list[str]], default: int = 20) -> int:
    raw = _single_query_value(params, "limit")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, 100))


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


def _optional_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return None
