from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .config_alert_views import get_alert_detail, list_config_versions as build_config_versions
from .order_views import get_order_detail as build_order_detail
from .order_views import list_fills as filter_fills
from .order_views import list_orders as filter_orders


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sample_time(minutes_ago: int) -> str:
    return _iso(datetime.now(UTC) - timedelta(minutes=minutes_ago))


class MemoryReadStore:
    backend_name = "memory"
    supports_mutation = True

    def __init__(
        self,
        *,
        bots: list[dict[str, object]],
        bot_details: dict[str, dict[str, object]],
        strategy_runs: dict[str, dict[str, object]],
        order_intents: dict[str, dict[str, object]],
        orders: dict[str, dict[str, object]],
        fills: list[dict[str, object]],
        heartbeats: dict[str, list[dict[str, object]]],
        alerts: list[dict[str, object]],
        config_versions: dict[str, list[dict[str, object]]],
        backend_name: str = "memory",
        supports_mutation: bool = True,
    ) -> None:
        self.backend_name = backend_name
        self.supports_mutation = supports_mutation
        self.bots = bots
        self.bot_details = bot_details
        self.strategy_runs = strategy_runs
        self.order_intents = order_intents
        self.orders = orders
        self.fills = fills
        self.heartbeats = heartbeats
        self.alerts = alerts
        self.config_versions = config_versions

    def list_bots(
        self,
        *,
        status: str | None = None,
        strategy_name: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]:
        bots = self.bots
        if status:
            bots = [bot for bot in bots if bot["status"] == status]
        if strategy_name:
            bots = [bot for bot in bots if bot["strategy_name"] == strategy_name]
        if mode:
            bots = [bot for bot in bots if bot["mode"] == mode]
        return bots

    def get_bot_detail(self, bot_id: str) -> dict[str, object] | None:
        return self.bot_details.get(bot_id)

    def list_strategy_runs(
        self,
        *,
        bot_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]:
        runs = list(self.strategy_runs.values())
        if bot_id:
            runs = [run for run in runs if run.get("bot_id") == bot_id]
        if status:
            runs = [run for run in runs if run.get("status") == status]
        if mode:
            runs = [run for run in runs if run.get("mode") == mode]
        return sorted(
            runs,
            key=lambda run: str(
                run.get("started_at") or run.get("created_at") or run.get("stopped_at") or ""
            ),
            reverse=True,
        )

    def get_strategy_run(self, run_id: str) -> dict[str, object] | None:
        return self.strategy_runs.get(run_id)

    def list_order_intents(
        self,
        *,
        bot_id: str | None = None,
        strategy_run_id: str | None = None,
        status: str | None = None,
        market: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict[str, object]]:
        intents = list(self.order_intents.values())
        if bot_id:
            intents = [intent for intent in intents if intent.get("bot_id") == bot_id]
        if strategy_run_id:
            intents = [
                intent
                for intent in intents
                if intent.get("strategy_run_id") == strategy_run_id
            ]
        if status:
            intents = [intent for intent in intents if intent.get("status") == status]
        if market:
            intents = [intent for intent in intents if intent.get("market") == market]
        if created_from:
            intents = [
                intent
                for intent in intents
                if str(intent.get("created_at", "")) >= created_from
            ]
        if created_to:
            intents = [
                intent
                for intent in intents
                if str(intent.get("created_at", "")) <= created_to
            ]
        return sorted(
            intents,
            key=lambda intent: str(intent.get("created_at", "")),
            reverse=True,
        )

    def get_order_intent(self, intent_id: str) -> dict[str, object] | None:
        return self.order_intents.get(intent_id)

    def create_order_intent(
        self,
        *,
        strategy_run_id: str,
        market: str,
        buy_exchange: str,
        sell_exchange: str,
        side_pair: str,
        target_qty: str,
        expected_profit: str | None,
        expected_profit_ratio: str | None,
        status: str,
        decision_context: dict[str, object] | None,
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for base memory store")

    def list_orders(
        self,
        *,
        bot_id: str | None = None,
        exchange_name: str | None = None,
        status: str | None = None,
        market: str | None = None,
        strategy_run_id: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict[str, object]]:
        return filter_orders(
            self.orders,
            bot_id=bot_id,
            exchange_name=exchange_name,
            status=status,
            market=market,
            strategy_run_id=strategy_run_id,
            created_from=created_from,
            created_to=created_to,
        )

    def get_order_detail(self, order_id: str) -> dict[str, object] | None:
        return build_order_detail(self.orders, self.order_intents, self.fills, order_id)

    def create_order(
        self,
        *,
        order_intent_id: str,
        exchange_name: str,
        exchange_order_id: str | None,
        market: str,
        side: str,
        requested_price: str | None,
        requested_qty: str,
        status: str,
        raw_payload: dict[str, object] | None,
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for base memory store")

    def list_fills(
        self,
        *,
        bot_id: str | None = None,
        exchange_name: str | None = None,
        market: str | None = None,
        strategy_run_id: str | None = None,
        order_id: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict[str, object]]:
        return filter_fills(
            self.fills,
            bot_id=bot_id,
            exchange_name=exchange_name,
            market=market,
            strategy_run_id=strategy_run_id,
            order_id=order_id,
            created_from=created_from,
            created_to=created_to,
        )

    def list_heartbeats(self, bot_id: str, limit: int = 20) -> list[dict[str, object]] | None:
        entries = self.heartbeats.get(bot_id)
        if entries is None:
            return None
        return entries[:limit]

    def list_alerts(
        self,
        *,
        bot_id: str | None = None,
        level: str | None = None,
        acknowledged: bool | None = None,
    ) -> list[dict[str, object]]:
        alerts = self.alerts
        if bot_id:
            alerts = [alert for alert in alerts if alert.get("bot_id") == bot_id]
        if level:
            alerts = [alert for alert in alerts if alert["level"] == level]
        if acknowledged is not None:
            alerts = [
                alert
                for alert in alerts
                if (alert.get("acknowledged_at") is not None) == acknowledged
            ]
        return alerts

    def latest_config(self, config_scope: str) -> dict[str, object] | None:
        versions = self.config_versions.get(config_scope)
        if not versions:
            return None
        return versions[0]

    def list_config_versions(self, config_scope: str) -> list[dict[str, object]]:
        return build_config_versions(self.config_versions, config_scope)

    def get_alert_detail(self, alert_id: str) -> dict[str, object] | None:
        return get_alert_detail(self.alerts, alert_id)

    def active_bot_count(self) -> int:
        return sum(1 for bot in self.bots if bot.get("status") == "running")

    def active_strategy_run_count(self) -> int:
        return sum(1 for run in self.strategy_runs.values() if run.get("status") == "running")

    def emit_alert(
        self,
        *,
        bot_id: str | None,
        level: str,
        code: str,
        message: str,
    ) -> dict[str, object]:
        raise RuntimeError("mutation not supported for base memory store")

    def create_config_version(
        self,
        *,
        config_scope: str,
        config_json: dict[str, object],
        checksum: str,
        created_by: str | None,
    ) -> dict[str, object]:
        raise RuntimeError("mutation not supported for base memory store")

    def create_strategy_run(
        self,
        *,
        bot_id: str,
        strategy_name: str,
        mode: str,
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for base memory store")

    def start_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for base memory store")

    def stop_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for base memory store")

    def assign_config(
        self,
        *,
        bot_id: str,
        config_scope: str,
        version_no: int,
    ) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for base memory store")

    def acknowledge_alert(self, alert_id: str) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for base memory store")

    def register_bot(
        self,
        *,
        bot_key: str,
        strategy_name: str,
        mode: str,
        hostname: str | None,
    ) -> dict[str, object]:
        raise RuntimeError("mutation not supported for base memory store")

    def record_heartbeat(
        self,
        *,
        bot_id: str,
        is_process_alive: bool,
        is_market_data_alive: bool,
        is_ordering_alive: bool,
        lag_ms: int | None,
        context: dict[str, object] | None,
    ) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for base memory store")
