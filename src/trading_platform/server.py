from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .market_data_connector import PublicMarketDataConnector
from .market_data_runtime import MarketDataRuntime
from .observability import AlertHookNotifier, MetricsRegistry
from .redis_runtime import RedisRuntime
from .route_handlers import ControlPlaneRouteMixin
from .storage.store_factory import StoreBootstrapInfo, build_read_store_bundle
from .storage.store_protocol import ControlPlaneStoreProtocol


LOGGER = logging.getLogger(__name__)


class ControlPlaneServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        config: AppConfig,
        read_store: ControlPlaneStoreProtocol,
        store_bootstrap: StoreBootstrapInfo,
        metrics: MetricsRegistry,
        alert_hook: AlertHookNotifier,
        redis_runtime: RedisRuntime,
        market_data_connector: PublicMarketDataConnector,
        market_data_runtime: MarketDataRuntime,
    ):
        super().__init__(server_address, ControlPlaneRequestHandler)
        self.config = config
        self.read_store = read_store
        self.store_bootstrap = store_bootstrap
        self.metrics = metrics
        self.alert_hook = alert_hook
        self.redis_runtime = redis_runtime
        self.market_data_connector = market_data_connector
        self.market_data_runtime = market_data_runtime


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

        if path == "/api/v1/runtime/streams":
            status, payload = self._runtime_streams_response(query)
            return status, payload, False

        if path == "/api/v1/bots":
            return HTTPStatus.OK, self._bots_response(query), False

        if path == "/api/v1/bots/events":
            status, payload = self._bot_events_response(query)
            return status, payload, False

        if path == "/api/v1/strategy-runs":
            return HTTPStatus.OK, self._strategy_runs_response(query), False

        if path == "/api/v1/strategy-runs/events":
            status, payload = self._strategy_events_response(query)
            return status, payload, False

        if path == "/api/v1/order-intents":
            return HTTPStatus.OK, self._order_intents_response(query), False

        if path == "/api/v1/orders":
            return HTTPStatus.OK, self._orders_response(query), False

        if path == "/api/v1/orders/events":
            status, payload = self._order_events_response(query)
            return status, payload, False

        if path == "/api/v1/fills":
            return HTTPStatus.OK, self._fills_response(query), False

        if path == "/api/v1/alerts":
            return HTTPStatus.OK, self._alerts_response(query), False

        if path == "/api/v1/alerts/events":
            status, payload = self._alert_events_response(query)
            return status, payload, False

        if path == "/api/v1/market-data/orderbook-top":
            status, payload = self._market_orderbook_top_response(query)
            return status, payload, False

        if path == "/api/v1/market-data/orderbook-top/cached":
            status, payload = self._cached_market_orderbook_top_response(query)
            return status, payload, False

        if path == "/api/v1/market-data/runtime":
            status, payload = self._market_runtime_response()
            return status, payload, False

        if path == "/api/v1/market-data/snapshots":
            status, payload = self._market_snapshots_response(query)
            return status, payload, False

        if path == "/api/v1/market-data/events":
            status, payload = self._market_events_response(query)
            return status, payload, False

        for resolver in (
            lambda: self._match_latest_config(path),
            lambda: self._match_config_versions(path),
            lambda: self._match_bot_heartbeats(path, query),
            lambda: self._match_strategy_run_detail(path),
            lambda: self._match_order_intent_detail(path),
            lambda: self._match_order_detail(path),
            lambda: self._match_alert_detail(path),
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

        if path == "/api/v1/order-intents":
            return self._create_order_intent_response()

        if path == "/api/v1/orders":
            return self._create_order_response()

        if path == "/api/v1/fills":
            return self._create_fill_response()

        if path == "/api/v1/market-data/poll":
            return self._market_data_poll_response()

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
    bootstrap = build_read_store_bundle(config)
    metrics = MetricsRegistry()
    redis_runtime = RedisRuntime(
        config.redis_url, config.redis_key_prefix, config.service_name
    )
    market_data_connector = PublicMarketDataConnector(
        timeout_ms=config.market_data_timeout_ms,
        stale_threshold_ms=config.market_data_stale_threshold_ms,
        upbit_base_url=config.upbit_quotation_base_url,
    )
    market_data_runtime = MarketDataRuntime(
        enabled=config.market_data_poll_enabled,
        exchange=config.market_data_poll_exchange,
        markets=config.market_data_poll_markets,
        interval_ms=config.market_data_poll_interval_ms,
        connector=market_data_connector,
        metrics=metrics,
        redis_runtime=redis_runtime,
    )
    return ControlPlaneServer(
        (config.host, config.port),
        config,
        bootstrap.store,
        bootstrap.info,
        metrics,
        AlertHookNotifier(config.alert_hook_path, config.service_name),
        redis_runtime,
        market_data_connector,
        market_data_runtime,
    )
