from __future__ import annotations

from uuid import uuid4

from ..config_apply_policy import summarize_config_assignment_policy
from .order_mutation_views import create_order as build_order_create
from .order_mutation_views import create_fill as build_fill_create
from .order_mutation_views import update_order_status as build_order_status_update
from .order_mutation_views import create_order_intent as build_order_intent_create
from .read_store import MemoryReadStore, _clone, _sample_time


class MemoryMutableStore(MemoryReadStore):
    supports_mutation = True

    def emit_alert(
        self,
        *,
        bot_id: str | None,
        level: str,
        code: str,
        message: str,
    ) -> dict[str, object]:
        with self._lock:
            alert = {
                "alert_id": str(uuid4()),
                "bot_id": bot_id,
                "level": level,
                "code": code,
                "message": message,
                "created_at": _sample_time(0),
                "acknowledged_at": None,
            }
            self.alerts.insert(0, alert)
            if bot_id is not None:
                detail = self.bot_details.get(bot_id)
                if detail is not None:
                    detail.setdefault("recent_alerts", []).insert(0, alert)
            return _clone(alert)

    def create_config_version(
        self,
        *,
        config_scope: str,
        config_json: dict[str, object],
        checksum: str,
        created_by: str | None,
    ) -> dict[str, object]:
        with self._lock:
            versions = self.config_versions.setdefault(config_scope, [])
            next_version = versions[0]["version_no"] + 1 if versions else 1
            version = {
                "config_version_id": str(uuid4()),
                "config_scope": config_scope,
                "version_no": next_version,
                "config_json": config_json,
                "checksum": checksum,
                "created_by": created_by,
                "created_at": _sample_time(0),
            }
            versions.insert(0, version)
            return _clone(version)

    def create_strategy_run(
        self,
        *,
        bot_id: str,
        strategy_name: str,
        mode: str,
    ) -> tuple[str, dict[str, object] | None]:
        with self._lock:
            detail = self.bot_details.get(bot_id)
            if detail is None:
                return "not_found", None

            existing_active_run = next(
                (
                    run
                    for run in self.strategy_runs.values()
                    if run.get("bot_id") == bot_id and run.get("status") in {"created", "running"}
                ),
                None,
            )
            if existing_active_run is not None:
                return "conflict", _clone(existing_active_run)

            run = {
                "run_id": str(uuid4()),
                "bot_id": bot_id,
                "strategy_name": strategy_name,
                "mode": mode,
                "status": "created",
                "created_at": _sample_time(0),
                "started_at": None,
                "stopped_at": None,
                "decision_count": 0,
            }
            self.strategy_runs[run["run_id"]] = run
            detail["latest_strategy_run"] = run
            return "created", _clone(run)

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
        with self._lock:
            outcome, intent = build_order_intent_create(
                strategy_runs=self.strategy_runs,
                order_intents=self.order_intents,
                strategy_run_id=strategy_run_id,
                market=market,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                side_pair=side_pair,
                target_qty=target_qty,
                expected_profit=expected_profit,
                expected_profit_ratio=expected_profit_ratio,
                status=status,
                decision_context=decision_context,
            )
            return outcome, None if intent is None else _clone(intent)

    def start_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]:
        with self._lock:
            run = self.strategy_runs.get(run_id)
            if run is None:
                return "not_found", None
            if run["status"] != "created":
                return "conflict", _clone(run)

            running_for_bot = next(
                (
                    item
                    for item in self.strategy_runs.values()
                    if item.get("bot_id") == run.get("bot_id")
                    and item.get("run_id") != run_id
                    and item.get("status") == "running"
                ),
                None,
            )
            if running_for_bot is not None:
                return "conflict", _clone(run)

            run["status"] = "running"
            run["started_at"] = _sample_time(0)
            run["stopped_at"] = None
            detail = self.bot_details.get(str(run["bot_id"]))
            if detail is not None:
                detail["latest_strategy_run"] = run
            return "started", _clone(run)

    def stop_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]:
        with self._lock:
            run = self.strategy_runs.get(run_id)
            if run is None:
                return "not_found", None
            if run["status"] != "running":
                return "conflict", _clone(run)

            run["status"] = "stopped"
            run["stopped_at"] = _sample_time(0)
            detail = self.bot_details.get(str(run["bot_id"]))
            if detail is not None:
                detail["latest_strategy_run"] = run
            return "stopped", _clone(run)

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
        with self._lock:
            outcome, order = build_order_create(
                order_intents=self.order_intents,
                orders=self.orders,
                order_intent_id=order_intent_id,
                exchange_name=exchange_name,
                exchange_order_id=exchange_order_id,
                market=market,
                side=side,
                requested_price=requested_price,
                requested_qty=requested_qty,
                status=status,
                raw_payload=raw_payload,
            )
            return outcome, None if order is None else _clone(order)

    def create_fill(
        self,
        *,
        order_id: str,
        exchange_trade_id: str | None,
        fill_price: str,
        fill_qty: str,
        fee_asset: str | None,
        fee_amount: str | None,
        filled_at: str,
    ) -> tuple[str, dict[str, object] | None]:
        with self._lock:
            outcome, fill = build_fill_create(
                orders=self.orders,
                order_intents=self.order_intents,
                fills=self.fills,
                order_id=order_id,
                exchange_trade_id=exchange_trade_id,
                fill_price=fill_price,
                fill_qty=fill_qty,
                fee_asset=fee_asset,
                fee_amount=fee_amount,
                filled_at=filled_at,
            )
            return outcome, None if fill is None else _clone(fill)

    def update_order_status(
        self,
        *,
        order_id: str,
        status: str,
    ) -> tuple[str, dict[str, object] | None]:
        with self._lock:
            outcome, order = build_order_status_update(
                orders=self.orders,
                order_id=order_id,
                status=status,
            )
            return outcome, None if order is None else _clone(order)

    def assign_config(
        self,
        *,
        bot_id: str,
        config_scope: str,
        version_no: int,
    ) -> dict[str, object] | None:
        with self._lock:
            detail = self.bot_details.get(bot_id)
            if detail is None:
                return None

            versions = self.config_versions.get(config_scope, [])
            version = next(
                (item for item in versions if item["version_no"] == version_no),
                None,
            )
            if version is None:
                return None
            previous_version = None
            assigned_current = detail.get("assigned_config_version")
            if isinstance(assigned_current, dict):
                previous_scope = str(assigned_current.get("config_scope") or "").strip()
                previous_version_no = assigned_current.get("version_no")
                if previous_scope and isinstance(previous_version_no, int):
                    previous_version = next(
                        (
                            item
                            for item in self.config_versions.get(previous_scope, [])
                            if int(item.get("version_no") or -1) == previous_version_no
                        ),
                        None,
                    )
            policy = summarize_config_assignment_policy(
                previous_version.get("config_json")
                if isinstance(previous_version, dict)
                else None,
                version["config_json"],
            )

            assigned = {
                "config_scope": config_scope,
                "version_no": version_no,
                "config_version_id": version["config_version_id"],
                "assigned_at": _sample_time(0),
                "apply_status": "pending",
                "acknowledged_at": None,
                "ack_message": None,
                "changed_sections": list(policy["changed_sections"]),
                "hot_reloadable_sections": list(policy["hot_reloadable_sections"]),
                "restart_required_sections": list(policy["restart_required_sections"]),
                "apply_policy": str(policy["apply_policy"]),
            }
            detail["assigned_config_version"] = assigned
            for bot in self.bots:
                if bot["bot_id"] == bot_id:
                    bot["assigned_config_version"] = assigned
                    break

            self.emit_alert(
                bot_id=bot_id,
                level="info",
                code="CONFIG_ASSIGNED",
                message=f"config {config_scope} v{version_no} assigned",
            )
            return _clone(assigned)

    def acknowledge_config_assignment(
        self,
        *,
        bot_id: str,
        ack_status: str,
        ack_message: str | None,
    ) -> dict[str, object] | None:
        with self._lock:
            detail = self.bot_details.get(bot_id)
            if detail is None:
                return None
            assigned = detail.get("assigned_config_version")
            if not isinstance(assigned, dict):
                return None
            normalized_status = ack_status.strip().lower()
            if normalized_status not in {"applied", "rejected", "restart_required"}:
                return None
            assigned["apply_status"] = normalized_status
            assigned["ack_message"] = ack_message
            assigned["acknowledged_at"] = _sample_time(0)
            for bot in self.bots:
                if bot["bot_id"] == bot_id:
                    bot["assigned_config_version"] = assigned
                    break
            self.emit_alert(
                bot_id=bot_id,
                level="info" if normalized_status == "applied" else "warn",
                code={
                    "applied": "CONFIG_APPLIED",
                    "rejected": "CONFIG_REJECTED",
                    "restart_required": "CONFIG_RESTART_REQUIRED",
                }[normalized_status],
                message=(
                    f"config {assigned['config_scope']} v{assigned['version_no']} {normalized_status}"
                ),
            )
            return _clone(assigned)

    def acknowledge_alert(self, alert_id: str) -> dict[str, object] | None:
        with self._lock:
            acknowledged_at = _sample_time(0)
            for alert in self.alerts:
                if alert["alert_id"] == alert_id:
                    alert["acknowledged_at"] = acknowledged_at
                    return _clone({
                        "alert_id": alert_id,
                        "acknowledged_at": acknowledged_at,
                    })
            return None

    def register_bot(
        self,
        *,
        bot_key: str,
        strategy_name: str,
        mode: str,
        hostname: str | None,
    ) -> dict[str, object]:
        with self._lock:
            default_versions = self.config_versions.get("default", [])
            latest_default = default_versions[0] if default_versions else None
            assigned_config_version = (
                {
                    "config_scope": "default",
                    "version_no": latest_default["version_no"],
                    "config_version_id": latest_default["config_version_id"],
                    "apply_status": "applied",
                    "acknowledged_at": _sample_time(0),
                    "ack_message": "initial default config assignment",
                    "changed_sections": ["initial_assignment"],
                    "hot_reloadable_sections": [],
                    "restart_required_sections": ["initial_assignment"],
                    "apply_policy": "restart_required",
                }
                if latest_default is not None
                else {
                    "config_scope": "default",
                    "version_no": 1,
                    "apply_status": "applied",
                    "acknowledged_at": _sample_time(0),
                    "ack_message": "initial default config assignment",
                    "changed_sections": ["initial_assignment"],
                    "hot_reloadable_sections": [],
                    "restart_required_sections": ["initial_assignment"],
                    "apply_policy": "restart_required",
                }
            )

            existing = next((bot for bot in self.bots if bot["bot_key"] == bot_key), None)
            if existing is not None:
                existing["strategy_name"] = strategy_name
                existing["mode"] = mode
                existing["hostname"] = hostname
                existing["status"] = "running"
                existing["last_seen_at"] = _sample_time(0)
                detail = self.bot_details[str(existing["bot_id"])]
                detail.update(existing)
                return _clone({
                    "bot_id": existing["bot_id"],
                    "assigned_config_version": existing["assigned_config_version"],
                    "status": existing["status"],
                })

            bot_id = str(uuid4())
            bot = {
                "bot_id": bot_id,
                "bot_key": bot_key,
                "strategy_name": strategy_name,
                "mode": mode,
                "status": "running",
                "hostname": hostname,
                "last_seen_at": _sample_time(0),
                "assigned_config_version": assigned_config_version,
            }
            self.bots.append(bot)
            self.bot_details[bot_id] = {
                **bot,
                "latest_heartbeat": None,
                "latest_strategy_run": None,
                "recent_alerts": [],
            }
            self.heartbeats[bot_id] = []
            return _clone({
                "bot_id": bot_id,
                "assigned_config_version": assigned_config_version,
                "status": bot["status"],
            })

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
        with self._lock:
            detail = self.bot_details.get(bot_id)
            if detail is None:
                return None

            heartbeat = {
                "created_at": _sample_time(0),
                "is_process_alive": is_process_alive,
                "is_market_data_alive": is_market_data_alive,
                "is_ordering_alive": is_ordering_alive,
                "lag_ms": lag_ms,
                "payload": context or {},
            }
            history = self.heartbeats.setdefault(bot_id, [])
            history.insert(0, heartbeat)
            detail["latest_heartbeat"] = heartbeat
            detail["last_seen_at"] = heartbeat["created_at"]

            for bot in self.bots:
                if bot["bot_id"] == bot_id:
                    bot["last_seen_at"] = heartbeat["created_at"]
                    bot["status"] = "running" if is_process_alive else "failed"
                    detail["status"] = bot["status"]
                    break

            return _clone({
                "bot_id": bot_id,
                "status": detail["status"],
                "recorded_at": heartbeat["created_at"],
            })
