from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import logging
import threading

from .redis_runtime import RedisRuntime
from .storage.store_protocol import ControlPlaneStoreProtocol


LOGGER = logging.getLogger(__name__)
TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected", "expired", "failed"}


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


@dataclass(frozen=True)
class RecoveryRuntimeInfo:
    enabled: bool
    interval_ms: int
    handoff_after_seconds: int
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
        read_store: ControlPlaneStoreProtocol,
        redis_runtime: RedisRuntime,
    ) -> None:
        self.enabled = enabled
        self.interval_ms = max(interval_ms, 250)
        self.handoff_after_seconds = max(handoff_after_seconds, 0)
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
            with self._lock:
                self._failure_count += 1
                self._last_error_at = _iso_now()
                self._last_error_message = str(exc)
            LOGGER.exception(
                "recovery runtime tick failed: error=%s",
                exc,
                extra={"event_name": "recovery_runtime_failed"},
            )

    def _process_trace(self, trace: dict[str, object]) -> None:
        with self._lock:
            self._processed_count += 1
        recovery_trace_id = str(trace.get("recovery_trace_id") or "")
        bot_id = str(trace.get("bot_id") or "")
        run_id = str(trace.get("run_id") or "")
        intent_id = str(trace.get("intent_id") or "")
        if not recovery_trace_id:
            self._record_skip("TRACE_ID_MISSING")
            return
        related_orders = self._related_orders(bot_id=bot_id, run_id=run_id, intent_id=intent_id)
        has_active_orders = any(
            str(order.get("status") or "").strip().lower() not in TERMINAL_ORDER_STATUSES
            for order in related_orders
        )
        residual_exposure_quote = _parse_decimal(trace.get("residual_exposure_quote"))
        if not has_active_orders and residual_exposure_quote == Decimal("0"):
            self._resolve_trace(trace, resolution_reason="no_active_orders_and_zero_residual")
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
        payload = {
            **trace,
            "status": "resolved",
            "lifecycle_state": "closed",
            "manual_handoff_required": False,
            "closed_at": _iso_now(),
            "resolution_reason": resolution_reason,
        }
        self.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
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

    def _mark_handoff_required(self, trace: dict[str, object]) -> None:
        recovery_trace_id = str(trace.get("recovery_trace_id") or "")
        bot_id = str(trace.get("bot_id") or "") or None
        alert = None
        if self.read_store.supports_mutation:
            alert = self.read_store.emit_alert(
                bot_id=bot_id,
                level="critical",
                code="ARBITRAGE_MANUAL_HANDOFF_REQUIRED",
                message="recovery trace exceeded auto-recovery window",
            )
        payload = {
            **trace,
            "status": "handoff_required",
            "lifecycle_state": "manual_handoff",
            "manual_handoff_required": True,
            "incident_code": "ARB-302 MANUAL_HANDOFF_REQUIRED",
            "alert_id": None if alert is None else alert.get("alert_id"),
            "handoff_reason": "recovery_timeout_exceeded",
        }
        self.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
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
