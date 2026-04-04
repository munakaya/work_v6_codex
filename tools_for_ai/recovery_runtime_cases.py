from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

from trading_platform.recovery_runtime import RecoveryRuntime
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    redis_url = os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0")
    prefix = f"tp_recovery_runtime_case_{uuid4().hex[:8]}"
    redis_runtime = RedisRuntime(redis_url, prefix, "recovery-runtime-case")
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for recovery runtime cases")

    store = sample_read_store()
    run = store.list_strategy_runs()[0]
    bot_id = str(run["bot_id"])
    run_id = str(run["run_id"])
    runtime = RecoveryRuntime(
        enabled=True,
        interval_ms=1000,
        handoff_after_seconds=1,
        submit_timeout_seconds=1,
        read_store=store,
        redis_runtime=redis_runtime,
    )

    resolved_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=resolved_trace_id,
        payload={
            "recovery_trace_id": resolved_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
        },
    )
    runtime.run_once()
    resolved = redis_runtime.get_recovery_trace(recovery_trace_id=resolved_trace_id)
    _assert(resolved is not None, "resolved trace missing")
    _assert(resolved.get("status") == "resolved", "resolved case status mismatch")
    _assert(resolved.get("lifecycle_state") == "closed", "resolved case lifecycle mismatch")

    handoff_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=handoff_trace_id,
        payload={
            "recovery_trace_id": handoff_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "125000",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
        },
    )
    runtime.run_once()
    handoff = redis_runtime.get_recovery_trace(recovery_trace_id=handoff_trace_id)
    _assert(handoff is not None, "handoff trace missing")
    _assert(handoff.get("status") == "handoff_required", "handoff case status mismatch")
    _assert(
        handoff.get("lifecycle_state") == "manual_handoff",
        "handoff case lifecycle mismatch",
    )
    _assert(
        handoff.get("incident_code") == "ARB-302 MANUAL_HANDOFF_REQUIRED",
        "handoff incident mismatch",
    )

    outcome, intent = store.create_order_intent(
        strategy_run_id=run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.5",
        expected_profit="1500",
        expected_profit_ratio="0.01",
        status="created",
        decision_context={"source": "recovery_runtime_case"},
    )
    _assert(outcome == "created" and intent is not None, "intent create failed")
    buy_outcome, buy_order = store.create_order(
        order_intent_id=str(intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="recovery-case-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.5",
        status="submitted",
        raw_payload={"source": "recovery_runtime_case"},
    )
    sell_outcome, sell_order = store.create_order(
        order_intent_id=str(intent["intent_id"]),
        exchange_name="upbit",
        exchange_order_id="recovery-case-sell-1",
        market="KRW-BTC",
        side="sell",
        requested_price="100500",
        requested_qty="0.5",
        status="submitted",
        raw_payload={"source": "recovery_runtime_case"},
    )
    _assert(buy_outcome == "created" and buy_order is not None, "buy order create failed")
    _assert(
        sell_outcome == "created" and sell_order is not None, "sell order create failed"
    )
    fill_outcome, _ = store.create_fill(
        order_id=str(buy_order["order_id"]),
        exchange_trade_id="recovery-fill-buy-1",
        fill_price="100000",
        fill_qty="0.5",
        fee_asset=None,
        fee_amount="0",
        filled_at=_iso(datetime.now(UTC)),
    )
    _assert(fill_outcome == "created", "buy fill create failed")
    fill_outcome, _ = store.create_fill(
        order_id=str(sell_order["order_id"]),
        exchange_trade_id="recovery-fill-sell-1",
        fill_price="100500",
        fill_qty="0.5",
        fee_asset=None,
        fee_amount="0",
        filled_at=_iso(datetime.now(UTC)),
    )
    _assert(fill_outcome == "created", "sell fill create failed")

    terminal_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=terminal_trace_id,
        payload={
            "recovery_trace_id": terminal_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": str(intent["intent_id"]),
            "status": "active",
            "lifecycle_state": "recovery_required",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    terminal_trace = redis_runtime.get_recovery_trace(recovery_trace_id=terminal_trace_id)
    _assert(terminal_trace is not None, "terminal intent trace missing")
    _assert(
        terminal_trace.get("status") == "resolved",
        "terminal intent case status mismatch",
    )
    _assert(
        terminal_trace.get("resolution_reason") == "terminal_intent_and_no_active_orders",
        "terminal intent resolution reason mismatch",
    )

    stale_eval_run_id = "run_submit_timeout_case"
    stale_eval_bot_id = bot_id
    store.strategy_runs[stale_eval_run_id] = {
        "run_id": stale_eval_run_id,
        "bot_id": stale_eval_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    stale_outcome, stale_intent = store.create_order_intent(
        strategy_run_id=stale_eval_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.25",
        expected_profit="500",
        expected_profit_ratio="0.01",
        status="submitted",
        decision_context={"source": "submit_timeout_case"},
    )
    _assert(stale_outcome == "created" and stale_intent is not None, "stale intent create failed")
    order_outcome, stale_order = store.create_order(
        order_intent_id=str(stale_intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="submit-timeout-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.25",
        status="submitted",
        raw_payload={"source": "submit_timeout_case"},
    )
    _assert(order_outcome == "created" and stale_order is not None, "stale order create failed")
    stale_order["submitted_at"] = _iso(datetime.now(UTC) - timedelta(seconds=5))
    stale_order["created_at"] = stale_order["submitted_at"]
    stale_order["updated_at"] = stale_order["submitted_at"]
    redis_runtime.sync_arbitrage_evaluation(
        run_id=stale_eval_run_id,
        payload={
            "bot_id": stale_eval_bot_id,
            "strategy_run_id": stale_eval_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "entry_submitting",
        },
        publish_event=False,
    )
    runtime.run_once()
    timeout_traces = redis_runtime.list_recovery_traces(
        limit=10,
        run_id=stale_eval_run_id,
        status="active",
    )
    _assert(timeout_traces is not None and timeout_traces, "submit timeout trace missing")
    timeout_trace = timeout_traces[0]
    _assert(
        timeout_trace.get("incident_code") == "ARB-201 HEDGE_TIMEOUT",
        "submit timeout incident mismatch",
    )
    _assert(
        timeout_trace.get("submit_timeout_seconds") == 1,
        "submit timeout threshold mismatch",
    )
    latest_eval = redis_runtime.get_arbitrage_evaluation(run_id=stale_eval_run_id)
    _assert(latest_eval is not None, "submit timeout latest evaluation missing")
    _assert(
        latest_eval.get("lifecycle_preview") == "recovery_required",
        "submit timeout latest evaluation lifecycle mismatch",
    )

    closed_eval_run_id = "run_terminal_eval_case"
    closed_eval_bot_id = bot_id
    store.strategy_runs[closed_eval_run_id] = {
        "run_id": closed_eval_run_id,
        "bot_id": closed_eval_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    closed_outcome, closed_intent = store.create_order_intent(
        strategy_run_id=closed_eval_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.25",
        expected_profit="500",
        expected_profit_ratio="0.01",
        status="simulated",
        decision_context={"source": "terminal_eval_case"},
    )
    _assert(
        closed_outcome == "created" and closed_intent is not None,
        "terminal eval intent create failed",
    )
    closed_order_outcome, closed_order = store.create_order(
        order_intent_id=str(closed_intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="terminal-eval-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.25",
        status="filled",
        raw_payload={"source": "terminal_eval_case"},
    )
    _assert(
        closed_order_outcome == "created" and closed_order is not None,
        "terminal eval order create failed",
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=closed_eval_run_id,
        payload={
            "bot_id": closed_eval_bot_id,
            "strategy_run_id": closed_eval_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "hedge_balanced",
            "persisted_intent": {"intent_id": str(closed_intent["intent_id"])},
        },
        publish_event=False,
    )
    runtime.run_once()
    closed_eval = redis_runtime.get_arbitrage_evaluation(run_id=closed_eval_run_id)
    _assert(closed_eval is not None, "terminal eval latest evaluation missing")
    _assert(
        closed_eval.get("lifecycle_preview") == "closed",
        "terminal eval latest evaluation should be closed",
    )

    print("PASS recovery runtime resolves zero-exposure traces")
    print("PASS recovery runtime resolves terminal intents without active orders")
    print("PASS recovery runtime opens submit-timeout recovery traces")
    print("PASS recovery runtime closes terminal latest evaluations")
    print("PASS recovery runtime escalates aged traces to manual handoff")


if __name__ == "__main__":
    main()
