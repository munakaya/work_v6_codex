from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import logging
import threading
from uuid import uuid4

from .redis_runtime import RedisRuntime
from .storage.store_protocol import ControlPlaneStoreProtocol


LOGGER = logging.getLogger(__name__)
TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected", "expired", "failed"}
TERMINAL_FAILURE_ORDER_STATUSES = {"cancelled", "rejected", "expired", "failed"}
TERMINAL_INTENT_STATUSES = {"filled", "closed", "simulated", "cancelled", "expired", "rejected"}
TERMINAL_SYNC_CANDIDATE_STATES = {
    "entry_submitting",
    "entry_open",
    "hedge_balanced",
    "unwind_in_progress",
}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def _observed_order_statuses(value: object) -> list[dict[str, str]] | None:
    if value is None or not isinstance(value, list):
        return None
    statuses: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        order_id = item.get("order_id")
        status = item.get("status")
        if not isinstance(order_id, str) or not isinstance(status, str):
            return None
        normalized_order_id = order_id.strip()
        normalized = status.strip().lower()
        if not normalized_order_id or not normalized:
            return None
        if normalized_order_id in seen:
            return None
        seen.add(normalized_order_id)
        statuses.append({"order_id": normalized_order_id, "status": normalized})
    return statuses


def _observed_string_ids(value: object) -> list[str] | None:
    if value is None or not isinstance(value, list):
        return None
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        normalized = item.strip()
        if not normalized or normalized in seen:
            return None
        seen.add(normalized)
        items.append(normalized)
    return items


def _observed_balances(value: object) -> list[dict[str, object]] | None:
    if value is None or not isinstance(value, list):
        return None
    balances: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        exchange_name = item.get("exchange_name")
        asset = item.get("asset")
        free = _parse_decimal(item.get("free"))
        locked = _parse_decimal(item.get("locked"))
        if (
            not isinstance(exchange_name, str)
            or not exchange_name.strip()
            or not isinstance(asset, str)
            or not asset.strip()
            or free is None
            or locked is None
            or free < 0
            or locked < 0
        ):
            return None
        key = (exchange_name.strip(), asset.strip().upper())
        if key in seen:
            return None
        seen.add(key)
        balances.append(
            {
                "exchange_name": key[0],
                "asset": key[1],
                "free": free,
                "locked": locked,
            }
        )
    return balances


@dataclass(frozen=True)
class RecoveryRuntimeInfo:
    enabled: bool
    interval_ms: int
    handoff_after_seconds: int
    submit_timeout_seconds: int
    reconciliation_mismatch_handoff_count: int
    reconciliation_stale_after_seconds: int
    running: bool
    state: str
    last_success_at: str | None
    last_error_at: str | None
    last_error_message: str | None
    last_resolution_at: str | None
    last_handoff_at: str | None
    processed_count: int
    resolved_count: int
    handoff_count: int
    skipped_count: int
    failure_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "interval_ms": self.interval_ms,
            "handoff_after_seconds": self.handoff_after_seconds,
            "submit_timeout_seconds": self.submit_timeout_seconds,
            "reconciliation_mismatch_handoff_count": self.reconciliation_mismatch_handoff_count,
            "reconciliation_stale_after_seconds": self.reconciliation_stale_after_seconds,
            "running": self.running,
            "state": self.state,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error_message": self.last_error_message,
            "last_resolution_at": self.last_resolution_at,
            "last_handoff_at": self.last_handoff_at,
            "processed_count": self.processed_count,
            "resolved_count": self.resolved_count,
            "handoff_count": self.handoff_count,
            "skipped_count": self.skipped_count,
            "failure_count": self.failure_count,
        }


class RecoveryRuntime:
    def __init__(
        self,
        *,
        enabled: bool,
        interval_ms: int,
        handoff_after_seconds: int,
        submit_timeout_seconds: int = 15,
        reconciliation_mismatch_handoff_count: int = 2,
        reconciliation_stale_after_seconds: int = 15,
        read_store: ControlPlaneStoreProtocol,
        redis_runtime: RedisRuntime,
    ) -> None:
        self.enabled = enabled
        self.interval_ms = max(interval_ms, 250)
        self.handoff_after_seconds = max(handoff_after_seconds, 0)
        self.submit_timeout_seconds = max(submit_timeout_seconds, 1)
        self.reconciliation_mismatch_handoff_count = max(
            reconciliation_mismatch_handoff_count, 1
        )
        self.reconciliation_stale_after_seconds = max(
            reconciliation_stale_after_seconds, 1
        )
        self.read_store = read_store
        self.redis_runtime = redis_runtime
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._last_error_message: str | None = None
        self._last_resolution_at: str | None = None
        self._last_handoff_at: str | None = None
        self._processed_count = 0
        self._resolved_count = 0
        self._handoff_count = 0
        self._skipped_count = 0
        self._failure_count = 0

    @property
    def info(self) -> RecoveryRuntimeInfo:
        with self._lock:
            return RecoveryRuntimeInfo(
                enabled=self.enabled,
                interval_ms=self.interval_ms,
                handoff_after_seconds=self.handoff_after_seconds,
                submit_timeout_seconds=self.submit_timeout_seconds,
                reconciliation_mismatch_handoff_count=self.reconciliation_mismatch_handoff_count,
                reconciliation_stale_after_seconds=self.reconciliation_stale_after_seconds,
                running=self._running,
                state=self._state_name(),
                last_success_at=self._last_success_at,
                last_error_at=self._last_error_at,
                last_error_message=self._last_error_message,
                last_resolution_at=self._last_resolution_at,
                last_handoff_at=self._last_handoff_at,
                processed_count=self._processed_count,
                resolved_count=self._resolved_count,
                handoff_count=self._handoff_count,
                skipped_count=self._skipped_count,
                failure_count=self._failure_count,
            )

    def start(self) -> None:
        if not self.enabled or not self.redis_runtime.info.enabled or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="recovery-runtime",
            daemon=True,
        )
        with self._lock:
            self._running = True
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(self.interval_ms / 1000, 1.0) + 1.0)
        with self._lock:
            self._running = False
        self._thread = None

    def run_once(self) -> None:
        self._tick()

    def _state_name(self) -> str:
        if not self.enabled:
            return "disabled"
        if not self.redis_runtime.info.enabled:
            return "redis_unavailable"
        if self._running:
            return "running"
        if self._failure_count > 0 and self._processed_count == 0:
            return "degraded"
        return "idle"

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._tick()
                if self._stop_event.wait(self.interval_ms / 1000):
                    break
        finally:
            with self._lock:
                self._running = False

    def _tick(self) -> None:
        if not self.redis_runtime.info.enabled:
            self._record_skip("REDIS_RUNTIME_UNAVAILABLE")
            return
        try:
            self._sync_terminal_latest_evaluations()
            self._open_submit_timeout_traces()
            traces = self.redis_runtime.list_recovery_traces(limit=100, status="active")
            if traces is None:
                raise RuntimeError("failed to list active recovery traces")
            for trace in traces:
                if self._stop_event.is_set():
                    break
                self._process_trace(trace)
            with self._lock:
                self._last_success_at = _iso_now()
                self._last_error_message = None
        except Exception as exc:
            if self._stop_event.is_set():
                with self._lock:
                    self._last_error_message = None
                return
            with self._lock:
                self._failure_count += 1
                self._last_error_at = _iso_now()
                self._last_error_message = str(exc)
            LOGGER.exception(
                "recovery runtime tick failed: error=%s",
                exc,
                extra={"event_name": "recovery_runtime_failed"},
            )

    def _sync_terminal_latest_evaluations(self) -> None:
        evaluations = self.redis_runtime.list_arbitrage_evaluations(limit=100)
        if evaluations is None:
            raise RuntimeError("failed to list arbitrage evaluations")
        for item in evaluations:
            lifecycle = str(item.get("lifecycle_preview") or "").strip().lower()
            if lifecycle not in TERMINAL_SYNC_CANDIDATE_STATES:
                continue
            run_id = str(item.get("strategy_run_id") or "").strip()
            bot_id = str(item.get("bot_id") or "").strip()
            persisted_intent = item.get("persisted_intent")
            if not isinstance(persisted_intent, dict):
                continue
            intent_id = str(persisted_intent.get("intent_id") or "").strip()
            if not run_id or not bot_id or not intent_id:
                continue
            blocking_trace = self.redis_runtime.get_blocking_recovery_trace(
                bot_id=bot_id or None,
                run_id=run_id or None,
            )
            if blocking_trace is not None:
                continue
            if not self._intent_is_terminal(intent_id=intent_id):
                continue
            related_orders = self._related_orders(
                bot_id=bot_id,
                run_id=run_id,
                intent_id=intent_id,
            )
            if not related_orders:
                continue
            if any(
                str(order.get("status") or "").strip().lower() not in TERMINAL_ORDER_STATUSES
                for order in related_orders
            ):
                continue
            self.redis_runtime.sync_arbitrage_evaluation(
                run_id=run_id,
                payload={**item, "lifecycle_preview": "closed"},
                trace_id=None,
                publish_event=True,
            )
            self.redis_runtime.append_event(
                "strategy_events",
                event_type="strategy.arbitrage_cycle_closed",
                payload={
                    "run_id": run_id,
                    "bot_id": bot_id,
                    "intent_id": intent_id,
                    "order_count": len(related_orders),
                    "source": "recovery_runtime",
                },
            )

    def _open_submit_timeout_traces(self) -> None:
        evaluations = self.redis_runtime.list_arbitrage_evaluations(limit=100)
        if evaluations is None:
            raise RuntimeError("failed to list arbitrage evaluations")
        for item in evaluations:
            lifecycle = str(item.get("lifecycle_preview") or "").strip().lower()
            if lifecycle != "entry_submitting":
                continue
            run_id = str(item.get("strategy_run_id") or "").strip()
            bot_id = str(item.get("bot_id") or "").strip()
            if not run_id or not bot_id:
                continue
            existing = self.redis_runtime.get_blocking_recovery_trace(
                bot_id=bot_id or None,
                run_id=run_id or None,
            )
            if existing is not None:
                continue
            oldest_submitted_at = self._oldest_open_order_timestamp(bot_id=bot_id, run_id=run_id)
            if oldest_submitted_at is None:
                continue
            age_seconds = max(0, int((datetime.now(UTC) - oldest_submitted_at).total_seconds()))
            if age_seconds < self.submit_timeout_seconds:
                continue
            self._create_submit_timeout_trace(
                bot_id=bot_id,
                run_id=run_id,
                oldest_submitted_at=oldest_submitted_at,
                age_seconds=age_seconds,
            )

    def _process_trace(self, trace: dict[str, object]) -> None:
        with self._lock:
            self._processed_count += 1
        recovery_trace_id = str(trace.get("recovery_trace_id") or "")
        bot_id = str(trace.get("bot_id") or "")
        run_id = str(trace.get("run_id") or "")
        intent_id = self._trace_intent_id(trace)
        if not recovery_trace_id:
            self._record_skip("TRACE_ID_MISSING")
            return
        related_orders = self._related_orders(bot_id=bot_id, run_id=run_id, intent_id=intent_id)
        has_active_orders = any(
            str(order.get("status") or "").strip().lower() not in TERMINAL_ORDER_STATUSES
            for order in related_orders
        )
        intent_terminal = self._intent_is_terminal(intent_id=intent_id)
        residual_exposure_quote = _parse_decimal(trace.get("residual_exposure_quote"))
        reconciliation_stale_handoff = self._reconciliation_stale_handoff_reason(trace)
        if reconciliation_stale_handoff is not None:
            handoff_reason, summary = reconciliation_stale_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        reconciliation_invalid_evidence_handoff = self._reconciliation_invalid_evidence_handoff_reason(
            trace
        )
        if reconciliation_invalid_evidence_handoff is not None:
            handoff_reason, summary = reconciliation_invalid_evidence_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        reconciliation_evidence_handoff = self._reconciliation_evidence_handoff_reason(trace)
        if reconciliation_evidence_handoff is not None:
            handoff_reason, summary = reconciliation_evidence_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        reconciliation_status_handoff = self._reconciliation_status_handoff_reason(trace)
        if reconciliation_status_handoff is not None:
            handoff_reason, summary = reconciliation_status_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        reconciliation_balance_handoff = self._reconciliation_balance_handoff_reason(trace)
        if reconciliation_balance_handoff is not None:
            handoff_reason, summary = reconciliation_balance_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        reconciliation_resolution_reason = self._reconciliation_resolution_reason(trace)
        if reconciliation_resolution_reason is not None:
            self._resolve_trace(trace, resolution_reason=reconciliation_resolution_reason)
            return
        reconciliation_handoff = self._reconciliation_handoff_reason(trace)
        if reconciliation_handoff is not None:
            handoff_reason, summary = reconciliation_handoff
            self._mark_handoff_required(
                trace,
                handoff_reason=handoff_reason,
                summary=summary,
            )
            return
        if not has_active_orders and residual_exposure_quote == Decimal("0"):
            self._resolve_trace(trace, resolution_reason="no_active_orders_and_zero_residual")
            return
        if not has_active_orders and intent_terminal:
            self._resolve_trace(trace, resolution_reason="terminal_intent_and_no_active_orders")
            return
        unwind_failure_status = self._linked_unwind_terminal_failure_status(trace)
        if unwind_failure_status is not None:
            self._mark_handoff_required(
                trace,
                handoff_reason="unwind_order_terminal_without_resolution",
                summary=f"linked unwind order became terminal without resolution: {unwind_failure_status}",
            )
            return
        stale_unwind_order = self._linked_unwind_order_stale(trace)
        if stale_unwind_order is not None:
            unwind_status, age_seconds = stale_unwind_order
            self._mark_handoff_required(
                trace,
                handoff_reason="unwind_order_timeout_exceeded",
                summary=(
                    "linked unwind order remained non-terminal beyond submit timeout: "
                    f"status={unwind_status} age_seconds={age_seconds}"
                ),
            )
            return
        age_seconds = self._trace_age_seconds(trace)
        if (
            age_seconds is not None
            and age_seconds > self.handoff_after_seconds
            and not bool(trace.get("manual_handoff_required"))
        ):
            self._mark_handoff_required(trace)
            return
        self._record_skip("NO_STATE_CHANGE")

    def _related_orders(
        self, *, bot_id: str, run_id: str, intent_id: str
    ) -> list[dict[str, object]]:
        orders = self.read_store.list_orders(bot_id=bot_id or None, strategy_run_id=run_id or None)
        if intent_id:
            orders = [item for item in orders if str(item.get("order_intent_id") or "") == intent_id]
        return orders

    def _intent_is_terminal(self, *, intent_id: str) -> bool:
        if not intent_id:
            return False
        intent = self.read_store.get_order_intent(intent_id)
        if intent is None:
            return False
        status = str(intent.get("status") or "").strip().lower()
        return status in TERMINAL_INTENT_STATUSES

    def _trace_intent_id(self, trace: dict[str, object]) -> str:
        linked_unwind_action_id = str(trace.get("linked_unwind_action_id") or "").strip()
        if linked_unwind_action_id:
            return linked_unwind_action_id
        return str(trace.get("intent_id") or "").strip()

    def _oldest_open_order_timestamp(self, *, bot_id: str, run_id: str) -> datetime | None:
        orders = self.read_store.list_orders(bot_id=bot_id or None, strategy_run_id=run_id or None)
        open_orders = [
            item
            for item in orders
            if str(item.get("status") or "").strip().lower() not in TERMINAL_ORDER_STATUSES
        ]
        timestamps = [
            _parse_iso_datetime(item.get("submitted_at"))
            or _parse_iso_datetime(item.get("created_at"))
            or _parse_iso_datetime(item.get("updated_at"))
            for item in open_orders
        ]
        timestamps = [item for item in timestamps if item is not None]
        if not timestamps:
            return None
        return min(timestamps)

    def _linked_unwind_terminal_failure_status(self, trace: dict[str, object]) -> str | None:
        linked_order_id = str(trace.get("linked_unwind_order_id") or "").strip()
        if not linked_order_id:
            return None
        order = self.read_store.get_order_detail(linked_order_id)
        if order is None:
            return None
        status = str(order.get("status") or "").strip().lower()
        if status in TERMINAL_FAILURE_ORDER_STATUSES:
            return status
        return None

    def _linked_unwind_order_stale(self, trace: dict[str, object]) -> tuple[str, int] | None:
        linked_order_id = str(trace.get("linked_unwind_order_id") or "").strip()
        if not linked_order_id:
            return None
        order = self.read_store.get_order_detail(linked_order_id)
        if order is None:
            return None
        status = str(order.get("status") or "").strip().lower()
        if status in TERMINAL_ORDER_STATUSES:
            return None
        observed_at = (
            _parse_iso_datetime(order.get("updated_at"))
            or _parse_iso_datetime(order.get("submitted_at"))
            or _parse_iso_datetime(order.get("created_at"))
        )
        if observed_at is None:
            return None
        age_seconds = max(0, int((datetime.now(UTC) - observed_at).total_seconds()))
        if age_seconds < self.submit_timeout_seconds:
            return None
        return status, age_seconds

    def _reconciliation_resolution_reason(self, trace: dict[str, object]) -> str | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if reconciliation_open_order_count is None or reconciliation_open_order_count < 0:
            return None
        if reconciliation_residual is None:
            return None
        if reconciliation_open_order_count == 0 and reconciliation_residual == Decimal("0"):
            return "reconciliation_matched_zero_residual"
        return None

    def _reconciliation_balance_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_open_order_count is None
            or reconciliation_open_order_count != 0
            or reconciliation_residual is None
            or reconciliation_residual != Decimal("0")
        ):
            return None
        relevant_exchanges = self._trace_relevant_exchanges(trace)
        if len(relevant_exchanges) < 2:
            return (
                "reconciliation_context_missing",
                "reconciliation matched result is missing complete intent exchange context",
            )
        relevant_assets = self._trace_relevant_assets(trace)
        if not relevant_assets:
            return (
                "reconciliation_market_context_missing",
                "reconciliation matched result is missing intent market asset context",
            )
        observed_balances = _observed_balances(
            trace.get("reconciliation_observed_balances")
        )
        if not observed_balances:
            missing_balance_keys = sorted(
                (exchange, asset)
                for exchange in relevant_exchanges
                for asset in relevant_assets
            )
            return (
                "reconciliation_balance_evidence_incomplete",
                "reconciliation matched result is missing observed balances for exchange/assets: "
                + ", ".join(f"{exchange}:{asset}" for exchange, asset in missing_balance_keys),
            )
        relevant_balance_rows = [
            balance
            for balance in observed_balances
            if str(balance["exchange_name"]).strip() in relevant_exchanges
            and (
                str(balance["asset"]).strip().upper() in relevant_assets
            )
        ]
        required_balance_keys = {
            (exchange, asset)
            for exchange in relevant_exchanges
            for asset in relevant_assets
        }
        observed_balance_keys = {
            (
                str(balance["exchange_name"]).strip(),
                str(balance["asset"]).strip().upper(),
            )
            for balance in relevant_balance_rows
        }
        missing_balance_keys = sorted(required_balance_keys - observed_balance_keys)
        if missing_balance_keys:
            return (
                "reconciliation_balance_evidence_incomplete",
                "reconciliation matched result is missing observed balances for exchange/assets: "
                + ", ".join(
                    (
                        f"{exchange}:{asset}"
                        if asset
                        else exchange
                    )
                    for exchange, asset in missing_balance_keys
                ),
            )
        locked_entries = [
            balance
            for balance in relevant_balance_rows
            if balance["locked"] > Decimal("0")
        ]
        if not locked_entries:
            return None
        summary_parts = [
            f"{entry['exchange_name']}:{entry['asset']} locked={entry['locked']}"
            for entry in locked_entries
        ]
        return (
            "reconciliation_balance_locked",
            "reconciliation matched result still has locked balances: "
            + ", ".join(summary_parts),
        )

    def _reconciliation_stale_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_open_order_count is None
            or reconciliation_open_order_count != 0
            or reconciliation_residual is None
            or reconciliation_residual != Decimal("0")
        ):
            return None
        observed_at = _parse_iso_datetime(trace.get("reconciliation_observed_at"))
        if observed_at is None:
            return (
                "reconciliation_observation_missing",
                "reconciliation matched result is missing observation timestamp",
            )
        age_seconds = max(0, int((datetime.now(UTC) - observed_at).total_seconds()))
        if age_seconds < self.reconciliation_stale_after_seconds:
            return None
        return (
            "reconciliation_observation_stale",
            "reconciliation matched result is older than automatic resolution threshold",
        )

    def _reconciliation_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "mismatch":
            return None
        reconciliation_mismatch_streak = _parse_int(
            trace.get("reconciliation_mismatch_streak")
        )
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_mismatch_streak is not None
            and reconciliation_mismatch_streak >= self.reconciliation_mismatch_handoff_count
        ):
            return (
                "reconciliation_mismatch_repeated",
                "reconciliation mismatch repeated beyond automatic recovery threshold",
            )
        observed_order_statuses = _observed_order_statuses(
            trace.get("reconciliation_observed_order_statuses")
        )
        if (
            reconciliation_open_order_count is not None
            and reconciliation_open_order_count > 0
            and observed_order_statuses
            and len(observed_order_statuses) >= reconciliation_open_order_count
            and all(
                str(status["status"]).strip().lower() in TERMINAL_FAILURE_ORDER_STATUSES
                for status in observed_order_statuses
            )
        ):
            return (
                "reconciliation_open_orders_terminal_failure",
                "reconciliation reports open orders but observed order statuses are all terminal failures",
            )
        if reconciliation_open_order_count is None or reconciliation_open_order_count < 0:
            return None
        if reconciliation_residual is None:
            return None
        if reconciliation_open_order_count == 0 and reconciliation_residual > Decimal("0"):
            return (
                "reconciliation_mismatch_residual_without_orders",
                "reconciliation reports no open orders while residual exposure remains",
            )
        return None

    def _reconciliation_evidence_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_open_order_count is None
            or reconciliation_open_order_count != 0
            or reconciliation_residual is None
            or reconciliation_residual != Decimal("0")
        ):
            return None
        has_fill_ids = bool(_observed_string_ids(trace.get("reconciliation_observed_fill_ids")))
        has_order_statuses = bool(
            _observed_order_statuses(trace.get("reconciliation_observed_order_statuses"))
        )
        has_balances = bool(_observed_balances(trace.get("reconciliation_observed_balances")))
        if has_fill_ids or has_order_statuses or has_balances:
            return None
        return (
            "reconciliation_evidence_missing",
            "reconciliation matched result is missing fill, status, or balance evidence",
        )

    def _reconciliation_invalid_evidence_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_open_order_count is None
            or reconciliation_open_order_count != 0
            or reconciliation_residual is None
            or reconciliation_residual != Decimal("0")
        ):
            return None
        invalid_fields: list[str] = []
        if (
            "reconciliation_observed_order_ids" in trace
            and trace.get("reconciliation_observed_order_ids") is not None
            and _observed_string_ids(trace.get("reconciliation_observed_order_ids")) is None
        ):
            invalid_fields.append("observed_order_ids")
        if (
            "reconciliation_observed_fill_ids" in trace
            and trace.get("reconciliation_observed_fill_ids") is not None
            and _observed_string_ids(trace.get("reconciliation_observed_fill_ids")) is None
        ):
            invalid_fields.append("observed_fill_ids")
        if (
            "reconciliation_observed_order_statuses" in trace
            and trace.get("reconciliation_observed_order_statuses") is not None
            and _observed_order_statuses(trace.get("reconciliation_observed_order_statuses")) is None
        ):
            invalid_fields.append("observed_order_statuses")
        if (
            "reconciliation_observed_balances" in trace
            and trace.get("reconciliation_observed_balances") is not None
            and _observed_balances(trace.get("reconciliation_observed_balances")) is None
        ):
            invalid_fields.append("observed_balances")
        if not invalid_fields:
            return None
        return (
            "reconciliation_evidence_invalid",
            "reconciliation matched result contains invalid evidence fields: "
            + ", ".join(invalid_fields),
        )

    def _reconciliation_status_handoff_reason(
        self, trace: dict[str, object]
    ) -> tuple[str, str] | None:
        reconciliation_result = str(trace.get("reconciliation_result") or "").strip().lower()
        if reconciliation_result != "matched":
            return None
        reconciliation_open_order_count = _parse_int(
            trace.get("reconciliation_open_order_count")
        )
        reconciliation_residual = _parse_decimal(
            trace.get("reconciliation_residual_exposure_quote")
        )
        if (
            reconciliation_open_order_count is None
            or reconciliation_open_order_count != 0
            or reconciliation_residual is None
            or reconciliation_residual != Decimal("0")
        ):
            return None
        observed_order_statuses = _observed_order_statuses(
            trace.get("reconciliation_observed_order_statuses")
        )
        if not observed_order_statuses:
            return None
        terminal_failure_statuses = sorted(
            {
                str(item["status"]).strip().lower()
                for item in observed_order_statuses
                if str(item["status"]).strip().lower() in TERMINAL_FAILURE_ORDER_STATUSES
            }
        )
        if terminal_failure_statuses:
            return (
                "reconciliation_terminal_failure_status_conflict",
                "reconciliation matched result conflicts with terminal failure order statuses: "
                + ", ".join(terminal_failure_statuses),
            )
        nonterminal_statuses = sorted(
            {
                str(item["status"]).strip().lower()
                for item in observed_order_statuses
                if str(item["status"]).strip().lower() not in TERMINAL_ORDER_STATUSES
            }
        )
        if not nonterminal_statuses:
            return None
        return (
            "reconciliation_open_order_status_conflict",
            "reconciliation matched result conflicts with non-terminal observed order statuses: "
            + ", ".join(nonterminal_statuses),
        )

    def _trace_relevant_exchanges(self, trace: dict[str, object]) -> set[str]:
        intent_id = self._trace_intent_id(trace)
        if not intent_id:
            return set()
        intent = self.read_store.get_order_intent(intent_id)
        if intent is None:
            return set()
        return {
            str(exchange).strip()
            for exchange in (
                intent.get("buy_exchange"),
                intent.get("sell_exchange"),
            )
            if isinstance(exchange, str) and exchange.strip()
        }

    def _trace_relevant_assets(self, trace: dict[str, object]) -> set[str]:
        intent_id = self._trace_intent_id(trace)
        if not intent_id:
            return set()
        intent = self.read_store.get_order_intent(intent_id)
        if intent is None:
            return set()
        market = str(intent.get("market") or "").strip().upper()
        if not market:
            return set()
        for separator in ("-", "/"):
            parts = [part.strip() for part in market.split(separator) if part.strip()]
            if len(parts) == 2:
                return {parts[0], parts[1]}
        return set()

    def _create_submit_timeout_trace(
        self,
        *,
        bot_id: str,
        run_id: str,
        oldest_submitted_at: datetime,
        age_seconds: int,
    ) -> None:
        recovery_trace_id = f"rt_{uuid4().hex}"
        now_iso = _iso_now()
        payload = {
            "recovery_trace_id": recovery_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": None,
            "status": "active",
            "lifecycle_state": "recovery_required",
            "incident_code": "ARB-201 HEDGE_TIMEOUT",
            "reason_code": "ORDER_SUBMIT_FAILED",
            "manual_handoff_required": False,
            "auto_unwind_allowed": False,
            "opened_at": now_iso,
            "created_at": now_iso,
            "oldest_submitted_at": oldest_submitted_at.isoformat().replace("+00:00", "Z"),
            "submit_timeout_seconds": self.submit_timeout_seconds,
            "submit_timeout_age_seconds": age_seconds,
            "summary": "entry_submitting exceeded submit timeout window",
        }
        self.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
            trace_id=None,
        )
        latest_trace = self.redis_runtime.get_recovery_trace(recovery_trace_id=recovery_trace_id)
        if latest_trace is not None:
            self.redis_runtime.sync_arbitrage_evaluation_recovery_state(
                run_id=run_id,
                recovery_trace=latest_trace,
                trace_id=None,
            )
        self.redis_runtime.append_event(
            "strategy_events",
            event_type="strategy.recovery_trace.submit_timeout_opened",
            payload={
                "recovery_trace_id": recovery_trace_id,
                "run_id": run_id,
                "bot_id": bot_id,
                "incident_code": "ARB-201 HEDGE_TIMEOUT",
                "submit_timeout_age_seconds": age_seconds,
            },
        )
        if self.read_store.supports_mutation:
            self.read_store.emit_alert(
                bot_id=bot_id,
                level="error",
                code="ARBITRAGE_SUBMIT_TIMEOUT",
                message="entry_submitting exceeded submit timeout window",
            )

    def _trace_age_seconds(self, trace: dict[str, object]) -> int | None:
        now = datetime.now(UTC)
        opened_at = _parse_iso_datetime(trace.get("opened_at")) or _parse_iso_datetime(
            trace.get("created_at")
        )
        if opened_at is None:
            return None
        return max(0, int((now - opened_at).total_seconds()))

    def _resolve_trace(self, trace: dict[str, object], *, resolution_reason: str) -> None:
        recovery_trace_id = str(trace.get("recovery_trace_id") or "")
        resolved_residual_exposure = trace.get("residual_exposure_quote")
        if resolution_reason == "reconciliation_matched_zero_residual":
            resolved_residual_exposure = (
                str(trace.get("reconciliation_residual_exposure_quote"))
                if trace.get("reconciliation_residual_exposure_quote") is not None
                else "0"
            )
        payload = {
            **trace,
            "status": "resolved",
            "lifecycle_state": "closed",
            "manual_handoff_required": False,
            "residual_exposure_quote": resolved_residual_exposure,
            "closed_at": _iso_now(),
            "resolution_reason": resolution_reason,
        }
        self.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
            trace_id=None,
        )
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            latest_trace = self.redis_runtime.get_recovery_trace(
                recovery_trace_id=recovery_trace_id
            )
            if latest_trace is not None:
                self.redis_runtime.sync_arbitrage_evaluation_recovery_state(
                    run_id=run_id,
                    recovery_trace=latest_trace,
                    trace_id=None,
                )
        self.redis_runtime.append_event(
            "strategy_events",
            event_type="strategy.recovery_trace.resolved",
            payload={
                "recovery_trace_id": recovery_trace_id,
                "run_id": payload.get("run_id"),
                "bot_id": payload.get("bot_id"),
                "resolution_reason": resolution_reason,
            },
        )
        with self._lock:
            self._resolved_count += 1
            self._last_resolution_at = _iso_now()

    def _mark_handoff_required(
        self,
        trace: dict[str, object],
        *,
        handoff_reason: str = "recovery_timeout_exceeded",
        summary: str | None = None,
    ) -> None:
        recovery_trace_id = str(trace.get("recovery_trace_id") or "")
        bot_id = str(trace.get("bot_id") or "") or None
        alert = None
        if self.read_store.supports_mutation:
            alert = self.read_store.emit_alert(
                bot_id=bot_id,
                level="critical",
                code="ARBITRAGE_MANUAL_HANDOFF_REQUIRED",
                message=summary or "recovery trace exceeded auto-recovery window",
            )
        payload = {
            **trace,
            "status": "handoff_required",
            "lifecycle_state": "manual_handoff",
            "manual_handoff_required": True,
            "incident_code": "ARB-302 MANUAL_HANDOFF_REQUIRED",
            "alert_id": None if alert is None else alert.get("alert_id"),
            "handoff_reason": handoff_reason,
            "summary": summary or str(trace.get("summary") or ""),
        }
        self.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
            trace_id=None,
        )
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            latest_trace = self.redis_runtime.get_recovery_trace(
                recovery_trace_id=recovery_trace_id
            )
            if latest_trace is not None:
                self.redis_runtime.sync_arbitrage_evaluation_recovery_state(
                    run_id=run_id,
                    recovery_trace=latest_trace,
                    trace_id=None,
                )
        if alert is not None:
            self.redis_runtime.publish_alert_event(
                event_type="alert.created",
                payload={
                    "alert_id": alert.get("alert_id"),
                    "bot_id": alert.get("bot_id"),
                    "level": alert.get("level"),
                    "code": alert.get("code"),
                },
            )
        self.redis_runtime.append_event(
            "strategy_events",
            event_type="strategy.recovery_trace.handoff_required",
            payload={
                "recovery_trace_id": recovery_trace_id,
                "run_id": payload.get("run_id"),
                "bot_id": payload.get("bot_id"),
                "incident_code": payload.get("incident_code"),
            },
        )
        with self._lock:
            self._handoff_count += 1
            self._last_handoff_at = _iso_now()

    def _record_skip(self, reason: str) -> None:
        with self._lock:
            self._skipped_count += 1
