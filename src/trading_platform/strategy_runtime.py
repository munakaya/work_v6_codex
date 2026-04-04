from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import threading
from uuid import uuid4

from .market_data_connector import PublicMarketDataConnector
from .redis_runtime import RedisRuntime
from .storage.store_protocol import ControlPlaneStoreProtocol
from .strategy import (
    build_arbitrage_execution_adapter,
    evaluate_arbitrage,
    load_strategy_inputs,
    persist_order_intent_plan,
)
from .strategy.arbitrage_evaluation_payload import build_arbitrage_evaluation_payload
from .strategy.arbitrage_runtime_loader import load_arbitrage_runtime_payload
from .strategy_runtime_execution import execute_persisted_arbitrage_intent


LOGGER = logging.getLogger(__name__)
SUPPORTED_EXECUTION_MODES = {
    "simulate_success",
    "simulate_failure",
    "simulate_fill",
    "private_http",
    "private_stub",
}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StrategyRuntimeInfo:
    enabled: bool
    interval_ms: int
    persist_intent: bool
    execution_enabled: bool
    execution_mode: str
    execution_adapter: str
    auto_unwind_on_failure: bool
    running: bool
    state: str
    last_success_at: str | None
    last_error_at: str | None
    last_error_message: str | None
    last_skip_at: str | None
    last_skip_reason: str | None
    evaluated_count: int
    accepted_count: int
    rejected_count: int
    persisted_intent_count: int
    submit_attempt_count: int
    submit_success_count: int
    submit_failure_count: int
    skipped_count: int
    failure_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "interval_ms": self.interval_ms,
            "persist_intent": self.persist_intent,
            "execution_enabled": self.execution_enabled,
            "execution_mode": self.execution_mode,
            "execution_adapter": self.execution_adapter,
            "auto_unwind_on_failure": self.auto_unwind_on_failure,
            "running": self.running,
            "state": self.state,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error_message": self.last_error_message,
            "last_skip_at": self.last_skip_at,
            "last_skip_reason": self.last_skip_reason,
            "evaluated_count": self.evaluated_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "persisted_intent_count": self.persisted_intent_count,
            "submit_attempt_count": self.submit_attempt_count,
            "submit_success_count": self.submit_success_count,
            "submit_failure_count": self.submit_failure_count,
            "skipped_count": self.skipped_count,
            "failure_count": self.failure_count,
        }


class StrategyRuntime:
    def __init__(
        self,
        *,
        enabled: bool,
        interval_ms: int,
        persist_intent: bool,
        execution_enabled: bool,
        execution_mode: str,
        auto_unwind_on_failure: bool,
        read_store: ControlPlaneStoreProtocol,
        connector: PublicMarketDataConnector,
        redis_runtime: RedisRuntime,
        private_execution_url: str | None = None,
        private_execution_timeout_ms: int = 3000,
        private_execution_token: str | None = None,
        execution_adapter=None,
    ) -> None:
        self.enabled = enabled
        self.interval_ms = max(interval_ms, 250)
        self.persist_intent = persist_intent
        normalized_execution_mode = execution_mode.strip().lower() or "simulate_success"
        self.execution_mode = (
            normalized_execution_mode
            if normalized_execution_mode in SUPPORTED_EXECUTION_MODES
            else "simulate_failure"
        )
        self.execution_enabled = execution_enabled
        self.auto_unwind_on_failure = auto_unwind_on_failure
        self.read_store = read_store
        self.connector = connector
        self.redis_runtime = redis_runtime
        self.execution_adapter = execution_adapter or build_arbitrage_execution_adapter(
            self.execution_mode,
            private_execution_url=private_execution_url,
            private_execution_timeout_ms=private_execution_timeout_ms,
            private_execution_token=private_execution_token,
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._last_error_message: str | None = None
        self._last_skip_at: str | None = None
        self._last_skip_reason: str | None = None
        self._evaluated_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._persisted_intent_count = 0
        self._submit_attempt_count = 0
        self._submit_success_count = 0
        self._submit_failure_count = 0
        self._skipped_count = 0
        self._failure_count = 0

    @property
    def info(self) -> StrategyRuntimeInfo:
        with self._lock:
            return StrategyRuntimeInfo(
                enabled=self.enabled,
                interval_ms=self.interval_ms,
                persist_intent=self.persist_intent,
                execution_enabled=self.execution_enabled,
                execution_mode=self.execution_mode,
                execution_adapter=self.execution_adapter.name,
                auto_unwind_on_failure=self.auto_unwind_on_failure,
                running=self._running,
                state=self._state_name(),
                last_success_at=self._last_success_at,
                last_error_at=self._last_error_at,
                last_error_message=self._last_error_message,
                last_skip_at=self._last_skip_at,
                last_skip_reason=self._last_skip_reason,
                evaluated_count=self._evaluated_count,
                accepted_count=self._accepted_count,
                rejected_count=self._rejected_count,
                persisted_intent_count=self._persisted_intent_count,
                submit_attempt_count=self._submit_attempt_count,
                submit_success_count=self._submit_success_count,
                submit_failure_count=self._submit_failure_count,
                skipped_count=self._skipped_count,
                failure_count=self._failure_count,
            )

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="strategy-runtime",
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

    def _state_name(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._running:
            return "running"
        if self._failure_count > 0 and self._evaluated_count == 0:
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
        runs = self.read_store.list_strategy_runs(status="running")
        arbitrage_runs = [
            run for run in runs if str(run.get("strategy_name") or "") == "arbitrage"
        ]
        for run in arbitrage_runs:
            if self._stop_event.is_set():
                break
            self._evaluate_run(run)

    def _evaluate_run(self, run: dict[str, object]) -> None:
        run_id = str(run.get("run_id") or "")
        bot_id = str(run.get("bot_id") or "")
        trace_id = f"strategy-runtime-{uuid4()}"
        if self.redis_runtime.info.enabled:
            try:
                blocking_trace = self.redis_runtime.get_blocking_recovery_trace(
                    bot_id=bot_id,
                )
            except RuntimeError:
                self._record_skip(
                    "RECOVERY_TRACE_READ_FAILED",
                    "failed to read blocking recovery trace",
                )
                return
            if blocking_trace:
                blocking_status = str(blocking_trace.get("status") or "").strip().lower()
                recovery_trace_id = str(blocking_trace.get("recovery_trace_id") or "")
                if blocking_status == "handoff_required":
                    self._record_skip(
                        "MANUAL_HANDOFF_ACTIVE",
                        f"recovery_trace_id={recovery_trace_id}",
                    )
                else:
                    self._record_skip(
                        "RECOVERY_TRACE_ACTIVE",
                        f"recovery_trace_id={recovery_trace_id}",
                    )
                return
        load_result = load_arbitrage_runtime_payload(
            store=self.read_store,
            connector=self.connector,
            run=run,
        )
        if load_result.payload is None:
            self._record_skip(load_result.skip_reason or "SKIPPED", load_result.detail)
            return

        runtime_state = load_result.payload.get("runtime_state")
        if isinstance(runtime_state, dict):
            if bool(runtime_state.get("unwind_in_progress")):
                self._record_skip(
                    "UNWIND_IN_PROGRESS",
                    "existing recovery flow is active",
                )
                return
            open_order_count = int(runtime_state.get("open_order_count", 0) or 0)
            if bool(runtime_state.get("duplicate_intent_active")) or open_order_count > 0:
                self._record_skip(
                    "ACTIVE_ENTRY_PRESENT",
                    "existing intent or open orders block new evaluation",
                )
                return

        try:
            decision = evaluate_arbitrage(load_strategy_inputs(load_result.payload))
        except Exception as exc:
            self._record_failure(run_id=run_id, bot_id=bot_id, exc=exc)
            return

        payload = build_arbitrage_evaluation_payload(
            decision=decision,
            bot_id=bot_id,
            strategy_run_id=run_id,
        )
        publish_update = self._evaluation_changed(run_id=run_id, payload=payload)
        self.redis_runtime.sync_arbitrage_evaluation(
            run_id=run_id,
            payload=payload,
            trace_id=trace_id,
            publish_event=publish_update,
        )
        if publish_update:
            self.redis_runtime.append_event(
                "strategy_events",
                event_type="strategy.arbitrage_evaluated",
                payload={
                    "run_id": run_id,
                    "bot_id": bot_id,
                    "accepted": decision.accepted,
                    "reason_code": decision.reason_code,
                    "lifecycle_preview": payload.get("lifecycle_preview"),
                    "persist_intent": self.persist_intent and self.read_store.supports_mutation,
                    "source": "runtime_loop",
                },
                trace_id=trace_id,
            )
        self._record_success(decision.accepted)

        if not (
            self.persist_intent
            and self.read_store.supports_mutation
            and decision.accepted
        ):
            return

        outcome, intent = persist_order_intent_plan(
            store=self.read_store,
            decision=decision,
            strategy_run_id=run_id,
        )
        if outcome != "created" or intent is None:
            return

        payload = build_arbitrage_evaluation_payload(
            decision=decision,
            bot_id=bot_id,
            strategy_run_id=run_id,
            persisted_intent=intent,
        )
        self.redis_runtime.sync_arbitrage_evaluation(
            run_id=run_id,
            payload=payload,
            trace_id=trace_id,
            publish_event=True,
        )
        self.redis_runtime.publish_order_event(
            event_type="order_intent.created",
            payload={
                "intent_id": intent.get("intent_id"),
                "bot_id": intent.get("bot_id"),
                "strategy_run_id": intent.get("strategy_run_id"),
                "market": intent.get("market"),
            },
            trace_id=trace_id,
        )
        self.redis_runtime.append_event(
            "strategy_events",
            event_type="strategy.arbitrage_intent_persisted",
            payload={
                "run_id": run_id,
                "bot_id": bot_id,
                "intent_id": intent.get("intent_id"),
                "market": intent.get("market"),
                "source": "runtime_loop",
            },
            trace_id=trace_id,
        )
        with self._lock:
            self._persisted_intent_count += 1
            self._last_success_at = _iso_now()
            self._last_error_message = None

        if not self.execution_enabled:
            return

        with self._lock:
            self._submit_attempt_count += 1
        execution_outcome = execute_persisted_arbitrage_intent(
            store=self.read_store,
            redis_runtime=self.redis_runtime,
            decision=decision,
            intent=intent,
            run_id=run_id,
            bot_id=bot_id,
            trace_id=trace_id,
            execution_adapter=self.execution_adapter,
            auto_unwind_on_failure=self.auto_unwind_on_failure,
            payload_builder=build_arbitrage_evaluation_payload,
        )

        if execution_outcome.status == "submitted":
            with self._lock:
                self._submit_success_count += 1
                self._last_success_at = _iso_now()
            return
        with self._lock:
            self._submit_failure_count += 1
            self._last_error_message = (
                execution_outcome.error_message or "arbitrage runtime submit failed"
            )

    def _evaluation_changed(self, *, run_id: str, payload: dict[str, object]) -> bool:
        previous = self.redis_runtime.get_arbitrage_evaluation(run_id=run_id)
        if previous is None:
            return True
        return self._semantic_projection(previous) != self._semantic_projection(payload)

    def _semantic_projection(self, payload: dict[str, object]) -> dict[str, object]:
        persisted_intent = payload.get("persisted_intent")
        persisted_intent_id = None
        if isinstance(persisted_intent, dict):
            persisted_intent_id = persisted_intent.get("intent_id")
        candidate_size = payload.get("candidate_size")
        executable_edge = payload.get("executable_edge")
        reservation_plan = payload.get("reservation_plan")
        submit_result = payload.get("submit_result")
        return {
            "accepted": payload.get("accepted"),
            "reason_code": payload.get("reason_code"),
            "lifecycle_preview": payload.get("lifecycle_preview"),
            "persisted_intent_id": persisted_intent_id,
            "target_qty": (
                candidate_size.get("target_qty")
                if isinstance(candidate_size, dict)
                else None
            ),
            "executable_profit_quote": (
                executable_edge.get("executable_profit_quote")
                if isinstance(executable_edge, dict)
                else None
            ),
            "reservation_passed": (
                reservation_plan.get("reservation_passed")
                if isinstance(reservation_plan, dict)
                else None
            ),
            "submit_outcome": (
                submit_result.get("outcome")
                if isinstance(submit_result, dict)
                else None
            ),
        }

    def _record_success(self, accepted: bool) -> None:
        with self._lock:
            self._evaluated_count += 1
            if accepted:
                self._accepted_count += 1
            else:
                self._rejected_count += 1
            self._last_success_at = _iso_now()
            self._last_error_message = None

    def _record_skip(self, reason: str, detail: str | None) -> None:
        with self._lock:
            self._skipped_count += 1
            self._last_skip_at = _iso_now()
            self._last_skip_reason = reason if detail is None else f"{reason}: {detail}"
            self._last_error_message = None

    def _record_failure(self, *, run_id: str, bot_id: str, exc: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_error_at = _iso_now()
            self._last_error_message = str(exc)
        LOGGER.exception(
            "strategy runtime evaluation failed: run_id=%s bot_id=%s error=%s",
            run_id,
            bot_id,
            exc,
            extra={"event_name": "strategy_runtime_failed"},
        )
