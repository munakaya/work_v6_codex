from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from .redis_runtime import RedisRuntime
from .storage.store_protocol import ControlPlaneStoreProtocol
from .strategy import ArbitrageExecutionAdapterProtocol
from .strategy.arbitrage_models import ArbitrageDecision


@dataclass(frozen=True)
class StrategyRuntimeExecutionOutcome:
    status: str
    latest_payload: dict[str, object]
    recovery_trace_id: str | None = None
    error_message: str | None = None


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _submit_failure_message(submit_result: ArbitrageSubmitResult) -> str:
    details = submit_result.details if isinstance(submit_result.details, dict) else {}
    reason = str(details.get("reason") or "").strip()
    if reason:
        return reason
    return "arbitrage runtime submit failed"


TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected", "expired", "failed"}
TERMINAL_INTENT_STATUSES = {"filled", "closed", "simulated"}


def _maybe_close_after_terminal_fill(
    *,
    store: ControlPlaneStoreProtocol,
    intent: dict[str, object],
    payload: dict[str, object],
) -> dict[str, object]:
    if str(payload.get("lifecycle_preview") or "") != "hedge_balanced":
        return payload
    intent_id = str(intent.get("intent_id") or "")
    if not intent_id:
        return payload
    latest_intent = store.get_order_intent(intent_id)
    if latest_intent is None:
        return payload
    intent_status = str(latest_intent.get("status") or "").strip().lower()
    if intent_status not in TERMINAL_INTENT_STATUSES:
        return payload
    strategy_run_id = str(latest_intent.get("strategy_run_id") or "")
    related_orders = store.list_orders(strategy_run_id=strategy_run_id or None)
    related_orders = [
        item for item in related_orders if str(item.get("order_intent_id") or "") == intent_id
    ]
    if not related_orders:
        return payload
    if any(
        str(item.get("status") or "").strip().lower() not in TERMINAL_ORDER_STATUSES
        for item in related_orders
    ):
        return payload
    return {**payload, "lifecycle_preview": "closed"}


def execute_persisted_arbitrage_intent(
    *,
    store: ControlPlaneStoreProtocol,
    redis_runtime: RedisRuntime,
    decision: ArbitrageDecision,
    intent: dict[str, object],
    run_id: str,
    bot_id: str,
    trace_id: str,
    execution_adapter: ArbitrageExecutionAdapterProtocol,
    auto_unwind_on_failure: bool,
    payload_builder,
) -> StrategyRuntimeExecutionOutcome:
    submit_result = execution_adapter.submit(
        store=store,
        decision=decision,
        intent=intent,
        auto_unwind_on_failure=auto_unwind_on_failure,
    )
    for order in submit_result.created_orders:
        redis_runtime.publish_order_event(
            event_type="order.created",
            payload={
                "order_id": order.get("order_id"),
                "order_intent_id": order.get("order_intent_id"),
                "bot_id": order.get("bot_id"),
                "exchange_name": order.get("exchange_name"),
                "status": order.get("status"),
            },
            trace_id=trace_id,
        )
    for fill in submit_result.created_fills:
        redis_runtime.publish_order_event(
            event_type="fill.created",
            payload={
                "fill_id": fill.get("fill_id"),
                "order_id": fill.get("order_id"),
                "bot_id": fill.get("bot_id"),
                "exchange_name": fill.get("exchange_name"),
                "order_status": fill.get("order_status"),
            },
            trace_id=trace_id,
        )

    payload = payload_builder(
        decision=decision,
        bot_id=bot_id,
        strategy_run_id=run_id,
        persisted_intent=intent,
        lifecycle_preview_override=submit_result.lifecycle_preview,
        submit_result=submit_result.as_payload(),
    )
    payload = _maybe_close_after_terminal_fill(
        store=store,
        intent=intent,
        payload=payload,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=run_id,
        payload=payload,
        trace_id=trace_id,
        publish_event=True,
    )

    if submit_result.outcome in {"submitted", "filled"}:
        if submit_result.outcome == "filled" and payload.get("lifecycle_preview") == "closed":
            redis_runtime.append_event(
                "strategy_events",
                event_type="strategy.arbitrage_cycle_closed",
                payload={
                    "run_id": run_id,
                    "bot_id": bot_id,
                    "intent_id": intent.get("intent_id"),
                    "order_count": len(submit_result.created_orders),
                    "fill_count": len(submit_result.created_fills),
                    "source": "runtime_loop",
                },
                trace_id=trace_id,
            )
        redis_runtime.append_event(
            "strategy_events",
            event_type=(
                "strategy.arbitrage_fills_simulated"
                if submit_result.outcome == "filled"
                else "strategy.arbitrage_orders_submitted"
            ),
            payload={
                "run_id": run_id,
                "bot_id": bot_id,
                "intent_id": intent.get("intent_id"),
                "order_count": len(submit_result.created_orders),
                "fill_count": len(submit_result.created_fills),
                "lifecycle_preview": submit_result.lifecycle_preview,
                "source": "runtime_loop",
            },
            trace_id=trace_id,
        )
        return StrategyRuntimeExecutionOutcome(
            status="submitted",
            latest_payload=payload,
        )

    error_message = _submit_failure_message(submit_result)
    alert = store.emit_alert(
        bot_id=bot_id,
        level="error",
        code="ARBITRAGE_SUBMIT_FAILED",
        message=error_message,
    )
    recovery_trace_id = f"rt_{uuid4().hex}"
    recovery_trace = {
        "recovery_trace_id": recovery_trace_id,
        "run_id": run_id,
        "bot_id": bot_id,
        "intent_id": intent.get("intent_id"),
        "status": "active",
        "lifecycle_state": submit_result.lifecycle_preview,
        "incident_code": "ARB-201 HEDGE_TIMEOUT",
        "reason_code": decision.reason_code,
        "manual_handoff_required": False,
        "auto_unwind_allowed": auto_unwind_on_failure,
        "created_at": _iso_now(),
        "alert_id": alert.get("alert_id"),
        "submit_result": submit_result.as_payload(),
    }
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=recovery_trace_id,
        payload=recovery_trace,
        trace_id=trace_id,
    )
    latest_trace = redis_runtime.get_recovery_trace(recovery_trace_id=recovery_trace_id)
    if latest_trace is not None:
        redis_runtime.sync_arbitrage_evaluation_recovery_state(
            run_id=run_id,
            recovery_trace=latest_trace,
            trace_id=trace_id,
        )
    redis_runtime.publish_alert_event(
        event_type="alert.created",
        payload={
            "alert_id": alert.get("alert_id"),
            "bot_id": alert.get("bot_id"),
            "level": alert.get("level"),
            "code": alert.get("code"),
        },
        trace_id=trace_id,
    )
    redis_runtime.append_event(
        "strategy_events",
        event_type="strategy.arbitrage_submit_failed",
        payload={
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": intent.get("intent_id"),
            "lifecycle_preview": submit_result.lifecycle_preview,
            "auto_unwind_on_failure": auto_unwind_on_failure,
            "recovery_trace_id": recovery_trace_id,
            "source": "runtime_loop",
        },
        trace_id=trace_id,
    )
    return StrategyRuntimeExecutionOutcome(
        status="submit_failed",
        latest_payload=payload,
        recovery_trace_id=recovery_trace_id,
        error_message=error_message,
    )
