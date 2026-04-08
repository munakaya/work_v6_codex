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
from .private_exchange_connector import (
    PrivateExchangeConnectorProtocol,
    build_private_exchange_connectors,
)
from .request_guard import WriteRequestGuard, WriteRequestGuardConfig
from .recovery_runtime import RecoveryRuntime
from .redis_runtime import RedisRuntime
from .rate_limit import ExponentialBackoffPolicy, RateLimitPolicy
from .route_handlers import ControlPlaneRouteMixin
from .storage.store_factory import StoreBootstrapInfo, build_read_store_bundle
from .storage.store_protocol import ControlPlaneStoreProtocol
from .strategy_runtime import StrategyRuntime


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
        private_exchange_connectors: dict[str, PrivateExchangeConnectorProtocol],
        market_data_runtime: MarketDataRuntime,
        strategy_runtime: StrategyRuntime,
        recovery_runtime: RecoveryRuntime,
    ):
        super().__init__(server_address, ControlPlaneRequestHandler)
        self.config = config
        self.read_store = read_store
        self.store_bootstrap = store_bootstrap
        self.metrics = metrics
        self.alert_hook = alert_hook
        self.redis_runtime = redis_runtime
        self.market_data_connector = market_data_connector
        self.private_exchange_connectors = private_exchange_connectors
        self.market_data_runtime = market_data_runtime
        self.strategy_runtime = strategy_runtime
        self.recovery_runtime = recovery_runtime
        self.write_request_guard = WriteRequestGuard(
            WriteRequestGuardConfig(
                admin_token=config.admin_token,
                window_ms=config.control_plane_write_rate_limit_window_ms,
                max_requests=config.control_plane_write_rate_limit_max_requests,
            )
        )


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
        headers: dict[str, str] | None = None

        try:
            blocked = self._write_request_block_response(parsed.path)
            if blocked is not None:
                status, payload, headers = blocked
            else:
                status, payload = self._dispatch_post(parsed.path)
            self._write_json(status, payload, headers=headers)
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

        if path == "/api/v1/runtime/private-connectors":
            status, payload = self._runtime_private_connectors_response(query)
            return status, payload, False

        if path == "/api/v1/recovery-traces":
            status, payload = self._recovery_traces_response(query)
            return status, payload, False

        if path == "/api/v1/bots":
            return HTTPStatus.OK, self._bots_response(query), False

        if path == "/api/v1/bots/events":
            status, payload = self._bot_events_response(query)
            return status, payload, False

        if path == "/api/v1/strategy-runs":
            return HTTPStatus.OK, self._strategy_runs_response(query), False

        if path == "/api/v1/strategy-runs/latest-evaluations":
            status, payload = self._latest_strategy_evaluations_response(query)
            return status, payload, False

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
            lambda: self._match_latest_strategy_evaluation(path),
            lambda: self._match_recovery_trace_detail(path),
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
            lambda: self._recovery_trace_action_response(path),
            lambda: self._evaluate_arbitrage_response(path),
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

    def _write_request_block_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object], dict[str, str] | None] | None:
        if not self._is_guarded_post_route(path):
            return None

        retry_after_ms = self.server.write_request_guard.check_rate_limit(
            self.client_address[0]
        )
        if retry_after_ms is not None:
            retry_after_seconds = max(1, (retry_after_ms + 999) // 1000)
            return (
                HTTPStatus.TOO_MANY_REQUESTS,
                self._response(
                    error={
                        "code": "WRITE_RATE_LIMITED",
                        "message": "too many write requests",
                        "retry_after_ms": retry_after_ms,
                    }
                ),
                {"Retry-After": str(retry_after_seconds)},
            )

        if not self.server.write_request_guard.authenticate(
            self.headers.get("Authorization")
        ):
            return (
                HTTPStatus.UNAUTHORIZED,
                self._response(
                    error={
                        "code": "ADMIN_AUTH_REQUIRED",
                        "message": "write API requires a valid bearer token",
                    }
                ),
                {"WWW-Authenticate": "Bearer"},
            )

        return None

    def _is_guarded_post_route(self, path: str) -> bool:
        return path.startswith("/api/v1/")


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
        retry_count=config.market_data_retry_count,
        retry_backoff=ExponentialBackoffPolicy(
            initial_delay_ms=config.market_data_retry_backoff_initial_ms,
            max_delay_ms=config.market_data_retry_backoff_max_ms,
        ),
        rate_limit_policies={
            "upbit": RateLimitPolicy(
                name="upbit_public_rest",
                rate_per_sec=config.upbit_public_rest_rate_limit_per_sec,
                burst=config.upbit_public_rest_burst,
            ),
            "bithumb": RateLimitPolicy(
                name="bithumb_public_rest",
                rate_per_sec=config.bithumb_public_rest_rate_limit_per_sec,
                burst=config.bithumb_public_rest_burst,
            ),
            "coinone": RateLimitPolicy(
                name="coinone_public_rest",
                rate_per_sec=config.coinone_public_rest_rate_limit_per_sec,
                burst=config.coinone_public_rest_burst,
            ),
        },
        upbit_base_url=config.upbit_quotation_base_url,
        bithumb_base_url=config.bithumb_public_base_url,
        coinone_base_url=config.coinone_public_base_url,
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
    private_exchange_connectors = build_private_exchange_connectors(config=config)
    strategy_runtime = StrategyRuntime(
        enabled=config.strategy_runtime_enabled,
        interval_ms=config.strategy_runtime_interval_ms,
        persist_intent=config.strategy_runtime_persist_intent,
        execution_enabled=config.strategy_runtime_execution_enabled,
        execution_mode=config.strategy_runtime_execution_mode,
        private_execution_url=config.strategy_private_execution_url,
        private_execution_timeout_ms=config.strategy_private_execution_timeout_ms,
        private_execution_token=config.strategy_private_execution_token,
        auto_unwind_on_failure=config.strategy_runtime_auto_unwind_on_failure,
        read_store=bootstrap.store,
        connector=market_data_connector,
        redis_runtime=redis_runtime,
    )
    recovery_runtime = RecoveryRuntime(
        enabled=config.recovery_runtime_enabled,
        interval_ms=config.recovery_runtime_interval_ms,
        handoff_after_seconds=config.recovery_runtime_handoff_after_seconds,
        submit_timeout_seconds=config.recovery_runtime_submit_timeout_seconds,
        reconciliation_mismatch_handoff_count=(
            config.recovery_runtime_reconciliation_mismatch_handoff_count
        ),
        reconciliation_stale_after_seconds=(
            config.recovery_runtime_reconciliation_stale_after_seconds
        ),
        read_store=bootstrap.store,
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
        private_exchange_connectors,
        market_data_runtime,
        strategy_runtime,
        recovery_runtime,
    )
