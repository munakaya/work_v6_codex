from __future__ import annotations

from .postgres_bot_views import (
    active_bot_count,
    active_strategy_run_count,
    get_bot_detail,
    get_strategy_run,
    latest_config,
    list_alerts,
    list_bots,
    list_heartbeats,
    list_strategy_runs,
)
from .postgres_driver import PostgresDriverAdapter
from .postgres_order_views import (
    get_order_detail,
    get_order_intent,
    list_fills,
    list_order_intents,
    list_orders,
)


class PostgresReadStore:
    backend_name = "postgres_readonly"
    supports_mutation = False

    def __init__(self, adapter: PostgresDriverAdapter) -> None:
        self.adapter = adapter

    def list_bots(self, **kwargs) -> list[dict[str, object]]:
        return list_bots(self.adapter, **kwargs)

    def get_bot_detail(self, bot_id: str) -> dict[str, object] | None:
        return get_bot_detail(self.adapter, bot_id)

    def list_strategy_runs(self, **kwargs) -> list[dict[str, object]]:
        return list_strategy_runs(self.adapter, **kwargs)

    def get_strategy_run(self, run_id: str) -> dict[str, object] | None:
        return get_strategy_run(self.adapter, run_id)

    def list_order_intents(self, **kwargs) -> list[dict[str, object]]:
        return list_order_intents(self.adapter, **kwargs)

    def get_order_intent(self, intent_id: str) -> dict[str, object] | None:
        return get_order_intent(self.adapter, intent_id)

    def list_orders(self, **kwargs) -> list[dict[str, object]]:
        return list_orders(self.adapter, **kwargs)

    def get_order_detail(self, order_id: str) -> dict[str, object] | None:
        return get_order_detail(self.adapter, order_id)

    def list_fills(self, **kwargs) -> list[dict[str, object]]:
        return list_fills(self.adapter, **kwargs)

    def list_heartbeats(
        self, bot_id: str, limit: int = 20
    ) -> list[dict[str, object]] | None:
        return list_heartbeats(self.adapter, bot_id, limit=limit)

    def list_alerts(self, **kwargs) -> list[dict[str, object]]:
        return list_alerts(self.adapter, **kwargs)

    def latest_config(self, config_scope: str) -> dict[str, object] | None:
        return latest_config(self.adapter, config_scope)

    def active_bot_count(self) -> int:
        return active_bot_count(self.adapter)

    def active_strategy_run_count(self) -> int:
        return active_strategy_run_count(self.adapter)

    def emit_alert(self, **kwargs) -> dict[str, object]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def create_config_version(self, **kwargs) -> dict[str, object]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def create_strategy_run(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def start_strategy_run(
        self, run_id: str
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def stop_strategy_run(
        self, run_id: str
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def assign_config(
        self, **kwargs
    ) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def acknowledge_alert(self, alert_id: str) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def register_bot(self, **kwargs) -> dict[str, object]:
        raise RuntimeError("mutation not supported for postgres read-only backend")

    def record_heartbeat(
        self, **kwargs
    ) -> dict[str, object] | None:
        raise RuntimeError("mutation not supported for postgres read-only backend")
