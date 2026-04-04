from __future__ import annotations

from math import ceil


class ControlPlaneRedisRouteMixin:
    def _redis_trace_id(self) -> str | None:
        return self.headers.get("X-Trace-Id")

    def _sync_bot_state(self, bot_id: str) -> None:
        detail = self.server.read_store.get_bot_detail(bot_id)
        if detail is None:
            return
        bot_key = detail.get("bot_key")
        if not isinstance(bot_key, str) or not bot_key:
            return
        self.server.redis_runtime.sync_bot_state(
            bot_key=bot_key,
            payload=detail,
            trace_id=self._redis_trace_id(),
        )

    def _sync_strategy_run_state(self, run: dict[str, object] | None) -> None:
        if run is None:
            return
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return
        self.server.redis_runtime.sync_strategy_run_state(
            run_id=run_id,
            payload=run,
            trace_id=self._redis_trace_id(),
        )

    def _sync_latest_config(
        self, config_scope: str, payload: dict[str, object] | None
    ) -> None:
        if payload is None:
            return
        self.server.redis_runtime.sync_latest_config(
            config_scope=config_scope,
            payload=payload,
            trace_id=self._redis_trace_id(),
        )

    def _publish_order_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.server.redis_runtime.publish_order_event(
            event_type=event_type,
            payload=payload,
            trace_id=self._redis_trace_id(),
        )

    def _publish_alert_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.server.redis_runtime.publish_alert_event(
            event_type=event_type,
            payload=payload,
            trace_id=self._redis_trace_id(),
        )

    def _sync_market_orderbook_top(self, snapshot: dict[str, object] | None) -> None:
        if snapshot is None:
            return
        exchange = snapshot.get("exchange")
        market = snapshot.get("market")
        if not isinstance(exchange, str) or not exchange:
            return
        if not isinstance(market, str) or not market:
            return
        ttl_seconds = max(
            self.server.redis_runtime.MARKET_ORDERBOOK_TTL_SECONDS,
            ceil(self.server.config.market_data_stale_threshold_ms / 1000) * 2,
        )
        self.server.redis_runtime.sync_market_orderbook_top(
            exchange=exchange,
            market=market,
            payload=snapshot,
            trace_id=self._redis_trace_id(),
            ttl_seconds=ttl_seconds,
        )
