from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .config import AppConfig
from .storage.dependencies import postgres_status, redis_status


LOGGER = logging.getLogger(__name__)


class ControlPlaneServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], config: AppConfig):
        super().__init__(server_address, ControlPlaneRequestHandler)
        self.config = config


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


def build_server(config: AppConfig) -> ControlPlaneServer:
    LOGGER.debug("building control plane server with config: %s", asdict(config))
    return ControlPlaneServer((config.host, config.port), config)
