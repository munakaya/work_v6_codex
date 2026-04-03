from __future__ import annotations

from typing import Protocol


class ControlPlaneStoreProtocol(Protocol):
    backend_name: str
    supports_mutation: bool

    def list_bots(
        self,
        *,
        status: str | None = None,
        strategy_name: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]: ...

    def get_bot_detail(self, bot_id: str) -> dict[str, object] | None: ...

    def list_strategy_runs(
        self,
        *,
        bot_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]: ...

    def get_strategy_run(self, run_id: str) -> dict[str, object] | None: ...

    def list_order_intents(
        self,
        *,
        bot_id: str | None = None,
        strategy_run_id: str | None = None,
        status: str | None = None,
        market: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict[str, object]]: ...

    def get_order_intent(self, intent_id: str) -> dict[str, object] | None: ...

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
    ) -> tuple[str, dict[str, object] | None]: ...

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
    ) -> list[dict[str, object]]: ...

    def get_order_detail(self, order_id: str) -> dict[str, object] | None: ...

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
    ) -> tuple[str, dict[str, object] | None]: ...

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
    ) -> list[dict[str, object]]: ...

    def list_heartbeats(
        self, bot_id: str, limit: int = 20
    ) -> list[dict[str, object]] | None: ...

    def list_alerts(
        self,
        *,
        bot_id: str | None = None,
        level: str | None = None,
        acknowledged: bool | None = None,
    ) -> list[dict[str, object]]: ...

    def latest_config(self, config_scope: str) -> dict[str, object] | None: ...

    def list_config_versions(self, config_scope: str) -> list[dict[str, object]]: ...

    def get_alert_detail(self, alert_id: str) -> dict[str, object] | None: ...

    def active_bot_count(self) -> int: ...

    def active_strategy_run_count(self) -> int: ...

    def emit_alert(
        self,
        *,
        bot_id: str | None,
        level: str,
        code: str,
        message: str,
    ) -> dict[str, object]: ...

    def create_config_version(
        self,
        *,
        config_scope: str,
        config_json: dict[str, object],
        checksum: str,
        created_by: str | None,
    ) -> dict[str, object]: ...

    def create_strategy_run(
        self,
        *,
        bot_id: str,
        strategy_name: str,
        mode: str,
    ) -> tuple[str, dict[str, object] | None]: ...

    def start_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]: ...

    def stop_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]: ...

    def assign_config(
        self,
        *,
        bot_id: str,
        config_scope: str,
        version_no: int,
    ) -> dict[str, object] | None: ...

    def acknowledge_alert(self, alert_id: str) -> dict[str, object] | None: ...

    def register_bot(
        self,
        *,
        bot_key: str,
        strategy_name: str,
        mode: str,
        hostname: str | None,
    ) -> dict[str, object]: ...

    def record_heartbeat(
        self,
        *,
        bot_id: str,
        is_process_alive: bool,
        is_market_data_alive: bool,
        is_ordering_alive: bool,
        lag_ms: int | None,
        context: dict[str, object] | None,
    ) -> dict[str, object] | None: ...
