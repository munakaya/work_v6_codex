from __future__ import annotations

from .postgres_mutation_ops import (
    acknowledge_config_assignment,
    acknowledge_alert,
    assign_config,
    create_config_version,
    create_strategy_run,
    emit_alert,
    record_heartbeat,
    register_bot,
    start_strategy_run,
    stop_strategy_run,
)
from .postgres_order_mutation_ops import (
    create_fill,
    create_order,
    create_order_intent,
    update_order_status,
)
from .postgres_read_store import PostgresReadStore


class PostgresMutableStore(PostgresReadStore):
    backend_name = "postgres_mutable"
    supports_mutation = True

    def emit_alert(self, **kwargs) -> dict[str, object]:
        return emit_alert(self.adapter, **kwargs)

    def create_config_version(self, **kwargs) -> dict[str, object]:
        return create_config_version(self.adapter, **kwargs)

    def create_strategy_run(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        return create_strategy_run(self.adapter, **kwargs)

    def start_strategy_run(
        self, run_id: str
    ) -> tuple[str, dict[str, object] | None]:
        return start_strategy_run(self.adapter, run_id)

    def stop_strategy_run(
        self, run_id: str
    ) -> tuple[str, dict[str, object] | None]:
        return stop_strategy_run(self.adapter, run_id)

    def create_order_intent(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        return create_order_intent(self.adapter, **kwargs)

    def create_order(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        return create_order(self.adapter, **kwargs)

    def create_fill(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        return create_fill(self.adapter, **kwargs)

    def update_order_status(
        self, **kwargs
    ) -> tuple[str, dict[str, object] | None]:
        return update_order_status(self.adapter, **kwargs)

    def assign_config(self, **kwargs) -> dict[str, object] | None:
        return assign_config(self.adapter, **kwargs)

    def acknowledge_config_assignment(self, **kwargs) -> dict[str, object] | None:
        return acknowledge_config_assignment(self.adapter, **kwargs)

    def acknowledge_alert(self, alert_id: str) -> dict[str, object] | None:
        return acknowledge_alert(self.adapter, alert_id)

    def register_bot(self, **kwargs) -> dict[str, object]:
        return register_bot(self.adapter, **kwargs)

    def record_heartbeat(self, **kwargs) -> dict[str, object] | None:
        return record_heartbeat(self.adapter, **kwargs)
