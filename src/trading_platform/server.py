from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .observability import AlertHookNotifier, MetricsRegistry
from .route_handlers import ControlPlaneRouteMixin
from .storage.read_store import MemoryReadStore, build_read_store


LOGGER = logging.getLogger(__name__)


class ControlPlaneServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        config: AppConfig,
        read_store: MemoryReadStore,
        metrics: MetricsRegistry,
        alert_hook: AlertHookNotifier,
    ):
        super().__init__(server_address, ControlPlaneRequestHandler)
        self.config = config
        self.read_store = read_store
        self.metrics = metrics
        self.alert_hook = alert_hook


class ControlPlaneRequestHandler(ControlPlaneRouteMixin, BaseHTTPRequestHandler):
    server: ControlPlaneServer

    def do_GET(self) -> None:
        started = perf_counter()
        parsed = urlparse(self.path)
        status = HTTPStatus.NOT_FOUND

        try:
            status, payload, as_text = self._dispatch_get(parsed.path, parsed.query)
            if as_text:
                self._write_text(status, payload)
            else:
                self._write_json(status, payload)
        finally:
            self.server.metrics.observe_request(
                "GET", status.value, perf_counter() - started
            )

    def do_POST(self) -> None:
        started = perf_counter()
        parsed = urlparse(self.path)
        status = HTTPStatus.NOT_FOUND

        try:
            status, payload = self._dispatch_post(parsed.path)
            self._write_json(status, payload)
        finally:
            self.server.metrics.observe_request(
                "POST", status.value, perf_counter() - started
            )

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info(
            format % args,
            extra={
                "event_name": "http_access",
                "client_ip": self.client_address[0],
                "http_method": self.command,
                "path": self.path,
            },
        )

    def _dispatch_get(self, path: str, query: str) -> tuple[HTTPStatus, dict[str, object] | str, bool]:
        if path == "/api/v1/health":
            return HTTPStatus.OK, self._health_payload(), False

        if path == "/api/v1/ready":
            status, payload = self._ready_response()
            return status, payload, False

        if path == "/metrics":
            payload = self.server.metrics.render(self.server.read_store)
            return HTTPStatus.OK, payload, True

        if path == "/api/v1/bots":
            return HTTPStatus.OK, self._bots_response(query), False

        if path == "/api/v1/strategy-runs":
            return HTTPStatus.OK, self._strategy_runs_response(query), False

        if path == "/api/v1/alerts":
            return HTTPStatus.OK, self._alerts_response(query), False

        for resolver in (
            lambda: self._match_latest_config(path),
            lambda: self._match_bot_heartbeats(path, query),
            lambda: self._match_strategy_run_detail(path),
            lambda: self._match_bot_detail(path),
        ):
            result = resolver()
            if result is not None:
                status, payload = result
                return status, payload, False

        return (
            HTTPStatus.NOT_FOUND,
            self._response(error={"code": "NOT_FOUND", "message": "route not found"}),
            False,
        )

    def _dispatch_post(self, path: str) -> tuple[HTTPStatus, dict[str, object]]:
        if path == "/api/v1/bots/register":
            return self._register_bot_response()

        if path == "/api/v1/configs":
            return self._create_config_response()

        if path == "/api/v1/strategy-runs":
            return self._create_strategy_run_response()

        for resolver in (
            lambda: self._acknowledge_alert_response(path),
            lambda: self._assign_config_response(path),
            lambda: self._strategy_run_action_response(path),
            lambda: self._record_heartbeat_response(path),
        ):
            result = resolver()
            if result is not None:
                return result

        return HTTPStatus.NOT_FOUND, self._response(
            error={"code": "NOT_FOUND", "message": "route not found"}
        )


def build_server(config: AppConfig) -> ControlPlaneServer:
    LOGGER.debug("building control plane server with config: %s", asdict(config))
    return ControlPlaneServer(
        (config.host, config.port),
        config,
        build_read_store(config),
        MetricsRegistry(),
        AlertHookNotifier(config.alert_hook_path, config.service_name),
    )
