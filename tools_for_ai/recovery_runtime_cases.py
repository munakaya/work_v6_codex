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
        reconciliation_mismatch_handoff_count=2,
        reconciliation_stale_after_seconds=1,
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

    missing_observed_at_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=missing_observed_at_trace_id,
        payload={
            "recovery_trace_id": missing_observed_at_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "reconciliation_result": "matched",
            "reconciliation_open_order_count": 0,
            "reconciliation_residual_exposure_quote": "0",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    missing_observed_at_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=missing_observed_at_trace_id
    )
    _assert(
        missing_observed_at_trace is not None,
        "missing observed_at reconciliation trace missing",
    )
    _assert(
        missing_observed_at_trace.get("status") == "handoff_required",
        "matched reconciliation without observed_at should hand off",
    )
    _assert(
        missing_observed_at_trace.get("handoff_reason")
        == "reconciliation_observation_missing",
        "missing observed_at handoff reason mismatch",
    )

    stale_reconciliation_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=stale_reconciliation_trace_id,
        payload={
            "recovery_trace_id": stale_reconciliation_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "reconciliation_result": "matched",
            "reconciliation_open_order_count": 0,
            "reconciliation_residual_exposure_quote": "0",
            "reconciliation_observed_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    stale_reconciliation_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=stale_reconciliation_trace_id
    )
    _assert(stale_reconciliation_trace is not None, "stale reconciliation trace missing")
    _assert(
        stale_reconciliation_trace.get("status") == "handoff_required",
        "stale matched reconciliation should hand off",
    )
    _assert(
        stale_reconciliation_trace.get("handoff_reason")
        == "reconciliation_observation_stale",
        "stale matched reconciliation handoff reason mismatch",
    )

    failed_open_order_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=failed_open_order_trace_id,
        payload={
            "recovery_trace_id": failed_open_order_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "50",
            "reconciliation_result": "mismatch",
            "reconciliation_open_order_count": 1,
            "reconciliation_residual_exposure_quote": "50",
            "reconciliation_mismatch_streak": 1,
            "reconciliation_observed_order_statuses": [
                {"order_id": "ord-failed-1", "status": "failed"}
            ],
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    failed_open_order_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=failed_open_order_trace_id
    )
    _assert(failed_open_order_trace is not None, "failed open order trace missing")
    _assert(
        failed_open_order_trace.get("status") == "handoff_required",
        "terminal failed open-order reconciliation should hand off",
    )
    _assert(
        failed_open_order_trace.get("handoff_reason")
        == "reconciliation_open_orders_terminal_failure",
        "terminal failed open-order handoff reason mismatch",
    )

    intent_balance_outcome, intent_balance = store.create_order_intent(
        strategy_run_id=run_id,
        market="KRW-BTC",
        buy_exchange="upbit",
        sell_exchange="bithumb",
        side_pair="buy_then_sell",
        target_qty="0.1",
        expected_profit="1000",
        expected_profit_ratio="0.01",
        status="submitted",
        decision_context={"source": "recovery_balance_case"},
    )
    _assert(
        intent_balance_outcome == "created" and intent_balance is not None,
        "balance guard intent create failed",
    )
    balance_locked_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=balance_locked_trace_id,
        payload={
            "recovery_trace_id": balance_locked_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": str(intent_balance["intent_id"]),
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "reconciliation_result": "matched",
            "reconciliation_open_order_count": 0,
            "reconciliation_residual_exposure_quote": "0",
            "reconciliation_observed_at": _iso(datetime.now(UTC)),
            "reconciliation_observed_balances": [
                {
                    "exchange_name": "upbit",
                    "asset": "KRW",
                    "free": "1000000",
                    "locked": "50000",
                },
                {
                    "exchange_name": "bithumb",
                    "asset": "BTC",
                    "free": "0.2",
                    "locked": "0",
                },
            ],
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    balance_locked_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=balance_locked_trace_id
    )
    _assert(balance_locked_trace is not None, "balance locked trace missing")
    _assert(
        balance_locked_trace.get("status") == "handoff_required",
        "matched reconciliation with locked balances should hand off",
    )
    _assert(
        balance_locked_trace.get("handoff_reason") == "reconciliation_balance_locked",
        "locked balance handoff reason mismatch",
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

    unwind_run_id = "run_unwind_resolution_case"
    unwind_bot_id = bot_id
    store.strategy_runs[unwind_run_id] = {
        "run_id": unwind_run_id,
        "bot_id": unwind_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    unwind_outcome, unwind_intent = store.create_order_intent(
        strategy_run_id=unwind_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.20",
        expected_profit=None,
        expected_profit_ratio=None,
        status="created",
        decision_context={"source": "unwind_resolution_case"},
    )
    _assert(
        unwind_outcome == "created" and unwind_intent is not None,
        "unwind intent create failed",
    )
    unwind_order_outcome, unwind_order = store.create_order(
        order_intent_id=str(unwind_intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="unwind-resolution-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.20",
        status="new",
        raw_payload={"source": "unwind_resolution_case"},
    )
    _assert(
        unwind_order_outcome == "created" and unwind_order is not None,
        "unwind order create failed",
    )
    fill_outcome, unwind_fill = store.create_fill(
        order_id=str(unwind_order["order_id"]),
        exchange_trade_id="unwind-resolution-fill-1",
        fill_price="100000",
        fill_qty="0.20",
        fee_asset=None,
        fee_amount=None,
        filled_at=_iso(datetime.now(UTC)),
    )
    _assert(fill_outcome == "created" and unwind_fill is not None, "unwind fill create failed")
    unwind_trace_id = "rt_unwind_resolution_case"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=unwind_trace_id,
        payload={
            "recovery_trace_id": unwind_trace_id,
            "run_id": unwind_run_id,
            "bot_id": unwind_bot_id,
            "intent_id": "original_entry_intent",
            "linked_unwind_action_id": str(unwind_intent["intent_id"]),
            "linked_unwind_order_id": str(unwind_order["order_id"]),
            "status": "active",
            "lifecycle_state": "unwind_in_progress",
            "manual_handoff_required": False,
            "incident_code": "ARB-202 UNWIND_IN_PROGRESS",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=3)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=unwind_run_id,
        payload={
            "bot_id": unwind_bot_id,
            "strategy_run_id": unwind_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "unwind_in_progress",
            "persisted_intent": {"intent_id": "original_entry_intent"},
            "recovery_trace_id": unwind_trace_id,
            "recovery_status": "active",
            "recovery_lifecycle_state": "unwind_in_progress",
        },
        publish_event=False,
    )
    runtime.run_once()
    unwind_trace = redis_runtime.get_recovery_trace(recovery_trace_id=unwind_trace_id)
    _assert(unwind_trace is not None, "unwind recovery trace missing")
    _assert(
        unwind_trace.get("status") == "resolved",
        "linked unwind trace should resolve after unwind fill",
    )
    unwind_eval = redis_runtime.get_arbitrage_evaluation(run_id=unwind_run_id)
    _assert(unwind_eval is not None, "unwind latest evaluation missing")
    _assert(
        unwind_eval.get("lifecycle_preview") == "closed",
        "unwind latest evaluation should be closed after unwind fill",
    )

    failed_unwind_run_id = "run_unwind_failure_case"
    failed_unwind_bot_id = bot_id
    store.strategy_runs[failed_unwind_run_id] = {
        "run_id": failed_unwind_run_id,
        "bot_id": failed_unwind_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    failed_unwind_outcome, failed_unwind_intent = store.create_order_intent(
        strategy_run_id=failed_unwind_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.10",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "unwind_failure_case"},
    )
    _assert(
        failed_unwind_outcome == "created" and failed_unwind_intent is not None,
        "failed unwind intent create failed",
    )
    failed_unwind_order_outcome, failed_unwind_order = store.create_order(
        order_intent_id=str(failed_unwind_intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="unwind-failure-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.10",
        status="cancelled",
        raw_payload={"source": "unwind_failure_case"},
    )
    _assert(
        failed_unwind_order_outcome == "created" and failed_unwind_order is not None,
        "failed unwind order create failed",
    )
    failed_unwind_trace_id = "rt_unwind_failure_case"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=failed_unwind_trace_id,
        payload={
            "recovery_trace_id": failed_unwind_trace_id,
            "run_id": failed_unwind_run_id,
            "bot_id": failed_unwind_bot_id,
            "intent_id": "original_entry_intent_failure_case",
            "linked_unwind_action_id": str(failed_unwind_intent["intent_id"]),
            "linked_unwind_order_id": str(failed_unwind_order["order_id"]),
            "status": "active",
            "lifecycle_state": "unwind_in_progress",
            "manual_handoff_required": False,
            "incident_code": "ARB-202 UNWIND_IN_PROGRESS",
            "residual_exposure_quote": "10",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=1)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=failed_unwind_run_id,
        payload={
            "bot_id": failed_unwind_bot_id,
            "strategy_run_id": failed_unwind_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "unwind_in_progress",
            "persisted_intent": {"intent_id": "original_entry_intent_failure_case"},
            "recovery_trace_id": failed_unwind_trace_id,
            "recovery_status": "active",
            "recovery_lifecycle_state": "unwind_in_progress",
        },
        publish_event=False,
    )
    runtime.run_once()
    failed_unwind_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=failed_unwind_trace_id
    )
    _assert(failed_unwind_trace is not None, "failed unwind recovery trace missing")
    _assert(
        failed_unwind_trace.get("status") == "handoff_required",
        "failed unwind trace should require manual handoff",
    )
    _assert(
        failed_unwind_trace.get("lifecycle_state") == "manual_handoff",
        "failed unwind lifecycle should switch to manual_handoff",
    )
    _assert(
        failed_unwind_trace.get("handoff_reason") == "unwind_order_terminal_without_resolution",
        "failed unwind handoff reason mismatch",
    )
    failed_unwind_eval = redis_runtime.get_arbitrage_evaluation(run_id=failed_unwind_run_id)
    _assert(failed_unwind_eval is not None, "failed unwind latest evaluation missing")
    _assert(
        failed_unwind_eval.get("lifecycle_preview") == "manual_handoff",
        "failed unwind latest evaluation should switch to manual_handoff",
    )

    stale_unwind_run_id = "run_unwind_timeout_case"
    stale_unwind_bot_id = bot_id
    store.strategy_runs[stale_unwind_run_id] = {
        "run_id": stale_unwind_run_id,
        "bot_id": stale_unwind_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    stale_unwind_outcome, stale_unwind_intent = store.create_order_intent(
        strategy_run_id=stale_unwind_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.11",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "unwind_timeout_case"},
    )
    _assert(
        stale_unwind_outcome == "created" and stale_unwind_intent is not None,
        "stale unwind intent create failed",
    )
    stale_unwind_order_outcome, stale_unwind_order = store.create_order(
        order_intent_id=str(stale_unwind_intent["intent_id"]),
        exchange_name="sample",
        exchange_order_id="unwind-timeout-buy-1",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.11",
        status="submitted",
        raw_payload={"source": "unwind_timeout_case"},
    )
    _assert(
        stale_unwind_order_outcome == "created" and stale_unwind_order is not None,
        "stale unwind order create failed",
    )
    stale_unwind_order["submitted_at"] = _iso(datetime.now(UTC) - timedelta(seconds=5))
    stale_unwind_order["created_at"] = stale_unwind_order["submitted_at"]
    stale_unwind_order["updated_at"] = stale_unwind_order["submitted_at"]
    stale_unwind_trace_id = "rt_unwind_timeout_case"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=stale_unwind_trace_id,
        payload={
            "recovery_trace_id": stale_unwind_trace_id,
            "run_id": stale_unwind_run_id,
            "bot_id": stale_unwind_bot_id,
            "intent_id": "original_entry_intent_timeout_case",
            "linked_unwind_action_id": str(stale_unwind_intent["intent_id"]),
            "linked_unwind_order_id": str(stale_unwind_order["order_id"]),
            "status": "active",
            "lifecycle_state": "unwind_in_progress",
            "manual_handoff_required": False,
            "incident_code": "ARB-202 UNWIND_IN_PROGRESS",
            "residual_exposure_quote": "11",
            "created_at": _iso(datetime.now(UTC)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=stale_unwind_run_id,
        payload={
            "bot_id": stale_unwind_bot_id,
            "strategy_run_id": stale_unwind_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "unwind_in_progress",
            "persisted_intent": {"intent_id": "original_entry_intent_timeout_case"},
            "recovery_trace_id": stale_unwind_trace_id,
            "recovery_status": "active",
            "recovery_lifecycle_state": "unwind_in_progress",
        },
        publish_event=False,
    )
    runtime.run_once()
    stale_unwind_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id=stale_unwind_trace_id
    )
    _assert(stale_unwind_trace is not None, "stale unwind recovery trace missing")
    _assert(
        stale_unwind_trace.get("status") == "handoff_required",
        "stale unwind trace should require manual handoff",
    )
    _assert(
        stale_unwind_trace.get("lifecycle_state") == "manual_handoff",
        "stale unwind lifecycle should switch to manual_handoff",
    )
    _assert(
        stale_unwind_trace.get("handoff_reason") == "unwind_order_timeout_exceeded",
        "stale unwind handoff reason mismatch",
    )
    stale_unwind_eval = redis_runtime.get_arbitrage_evaluation(run_id=stale_unwind_run_id)
    _assert(stale_unwind_eval is not None, "stale unwind latest evaluation missing")
    _assert(
        stale_unwind_eval.get("lifecycle_preview") == "manual_handoff",
        "stale unwind latest evaluation should switch to manual_handoff",
    )

    reconciliation_run_id = "run_reconciliation_resolution_case"
    reconciliation_bot_id = bot_id
    store.strategy_runs[reconciliation_run_id] = {
        "run_id": reconciliation_run_id,
        "bot_id": reconciliation_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    reconciliation_outcome, reconciliation_intent = store.create_order_intent(
        strategy_run_id=reconciliation_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.13",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "reconciliation_resolution_case"},
    )
    _assert(
        reconciliation_outcome == "created" and reconciliation_intent is not None,
        "reconciliation intent create failed",
    )
    redis_runtime.sync_recovery_trace(
        recovery_trace_id="rt_reconciliation_resolution_case",
        payload={
            "recovery_trace_id": "rt_reconciliation_resolution_case",
            "run_id": reconciliation_run_id,
            "bot_id": reconciliation_bot_id,
            "intent_id": str(reconciliation_intent["intent_id"]),
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "15",
            "reconciliation_result": "matched",
            "reconciliation_open_order_count": 0,
            "reconciliation_residual_exposure_quote": "0",
            "reconciliation_observed_at": _iso(datetime.now(UTC)),
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=reconciliation_run_id,
        payload={
            "bot_id": reconciliation_bot_id,
            "strategy_run_id": reconciliation_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "recovery_required",
            "persisted_intent": {"intent_id": str(reconciliation_intent["intent_id"])},
            "recovery_trace_id": "rt_reconciliation_resolution_case",
            "recovery_status": "active",
            "recovery_lifecycle_state": "recovery_required",
        },
        publish_event=False,
    )
    runtime.run_once()
    reconciliation_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id="rt_reconciliation_resolution_case"
    )
    _assert(reconciliation_trace is not None, "reconciliation trace missing")
    _assert(
        reconciliation_trace.get("status") == "resolved",
        "reconciliation trace should resolve when matched with zero residual",
    )
    _assert(
        reconciliation_trace.get("resolution_reason") == "reconciliation_matched_zero_residual",
        "reconciliation resolution reason mismatch",
    )
    _assert(
        str(reconciliation_trace.get("residual_exposure_quote") or "") == "0",
        "reconciliation resolution should zero residual exposure",
    )
    reconciliation_eval = redis_runtime.get_arbitrage_evaluation(run_id=reconciliation_run_id)
    _assert(reconciliation_eval is not None, "reconciliation latest evaluation missing")
    _assert(
        reconciliation_eval.get("lifecycle_preview") == "closed",
        "reconciliation latest evaluation should close after matched reconciliation",
    )

    mismatch_handoff_run_id = "run_reconciliation_handoff_case"
    mismatch_handoff_bot_id = bot_id
    store.strategy_runs[mismatch_handoff_run_id] = {
        "run_id": mismatch_handoff_run_id,
        "bot_id": mismatch_handoff_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    mismatch_handoff_outcome, mismatch_handoff_intent = store.create_order_intent(
        strategy_run_id=mismatch_handoff_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.17",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "reconciliation_handoff_case"},
    )
    _assert(
        mismatch_handoff_outcome == "created" and mismatch_handoff_intent is not None,
        "reconciliation handoff intent create failed",
    )
    redis_runtime.sync_recovery_trace(
        recovery_trace_id="rt_reconciliation_handoff_case",
        payload={
            "recovery_trace_id": "rt_reconciliation_handoff_case",
            "run_id": mismatch_handoff_run_id,
            "bot_id": mismatch_handoff_bot_id,
            "intent_id": str(mismatch_handoff_intent["intent_id"]),
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "17",
            "reconciliation_result": "mismatch",
            "reconciliation_open_order_count": 0,
            "reconciliation_residual_exposure_quote": "17",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=mismatch_handoff_run_id,
        payload={
            "bot_id": mismatch_handoff_bot_id,
            "strategy_run_id": mismatch_handoff_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "recovery_required",
            "persisted_intent": {"intent_id": str(mismatch_handoff_intent["intent_id"])},
            "recovery_trace_id": "rt_reconciliation_handoff_case",
            "recovery_status": "active",
            "recovery_lifecycle_state": "recovery_required",
        },
        publish_event=False,
    )
    runtime.run_once()
    mismatch_handoff_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id="rt_reconciliation_handoff_case"
    )
    _assert(mismatch_handoff_trace is not None, "reconciliation handoff trace missing")
    _assert(
        mismatch_handoff_trace.get("status") == "handoff_required",
        "reconciliation mismatch with residual and no orders should hand off",
    )
    _assert(
        mismatch_handoff_trace.get("handoff_reason")
        == "reconciliation_mismatch_residual_without_orders",
        "reconciliation mismatch handoff reason mismatch",
    )
    mismatch_handoff_eval = redis_runtime.get_arbitrage_evaluation(
        run_id=mismatch_handoff_run_id
    )
    _assert(mismatch_handoff_eval is not None, "reconciliation handoff latest evaluation missing")
    _assert(
        mismatch_handoff_eval.get("lifecycle_preview") == "manual_handoff",
        "reconciliation mismatch should switch latest evaluation to manual_handoff",
    )

    repeated_mismatch_run_id = "run_reconciliation_repeated_mismatch_case"
    repeated_mismatch_bot_id = bot_id
    store.strategy_runs[repeated_mismatch_run_id] = {
        "run_id": repeated_mismatch_run_id,
        "bot_id": repeated_mismatch_bot_id,
        "strategy_name": "arbitrage",
        "mode": "shadow",
        "status": "running",
        "created_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
        "stopped_at": None,
        "decision_count": 1,
    }
    repeated_mismatch_outcome, repeated_mismatch_intent = store.create_order_intent(
        strategy_run_id=repeated_mismatch_run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.19",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "reconciliation_repeated_mismatch_case"},
    )
    _assert(
        repeated_mismatch_outcome == "created" and repeated_mismatch_intent is not None,
        "repeated mismatch intent create failed",
    )
    redis_runtime.sync_recovery_trace(
        recovery_trace_id="rt_reconciliation_repeated_mismatch_case",
        payload={
            "recovery_trace_id": "rt_reconciliation_repeated_mismatch_case",
            "run_id": repeated_mismatch_run_id,
            "bot_id": repeated_mismatch_bot_id,
            "intent_id": str(repeated_mismatch_intent["intent_id"]),
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "19",
            "reconciliation_result": "mismatch",
            "reconciliation_open_order_count": 1,
            "reconciliation_residual_exposure_quote": "19",
            "reconciliation_mismatch_streak": 2,
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC)),
        },
        trace_id=None,
    )
    redis_runtime.sync_arbitrage_evaluation(
        run_id=repeated_mismatch_run_id,
        payload={
            "bot_id": repeated_mismatch_bot_id,
            "strategy_run_id": repeated_mismatch_run_id,
            "accepted": True,
            "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "lifecycle_preview": "recovery_required",
            "persisted_intent": {"intent_id": str(repeated_mismatch_intent["intent_id"])},
            "recovery_trace_id": "rt_reconciliation_repeated_mismatch_case",
            "recovery_status": "active",
            "recovery_lifecycle_state": "recovery_required",
        },
        publish_event=False,
    )
    runtime.run_once()
    repeated_mismatch_trace = redis_runtime.get_recovery_trace(
        recovery_trace_id="rt_reconciliation_repeated_mismatch_case"
    )
    _assert(repeated_mismatch_trace is not None, "repeated mismatch trace missing")
    _assert(
        repeated_mismatch_trace.get("status") == "handoff_required",
        "repeated mismatch trace should require manual handoff",
    )
    _assert(
        repeated_mismatch_trace.get("handoff_reason") == "reconciliation_mismatch_repeated",
        "repeated mismatch handoff reason mismatch",
    )
    repeated_mismatch_eval = redis_runtime.get_arbitrage_evaluation(
        run_id=repeated_mismatch_run_id
    )
    _assert(
        repeated_mismatch_eval is not None
        and repeated_mismatch_eval.get("lifecycle_preview") == "manual_handoff",
        "repeated mismatch latest evaluation should switch to manual_handoff",
    )

    print("PASS recovery runtime resolves zero-exposure traces")
    print("PASS recovery runtime resolves terminal intents without active orders")
    print("PASS recovery runtime opens submit-timeout recovery traces")
    print("PASS recovery runtime closes terminal latest evaluations")
    print("PASS recovery runtime resolves linked unwind actions after terminal fills")
    print("PASS recovery runtime escalates failed unwind orders to manual handoff")
    print("PASS recovery runtime escalates stale unwind orders to manual handoff")
    print("PASS recovery runtime hands off matched reconciliation with locked balances")
    print("PASS recovery runtime resolves matched reconciliation traces")
    print("PASS recovery runtime hands off unresolved reconciliation mismatch")
    print("PASS recovery runtime hands off repeated reconciliation mismatches")
    print("PASS recovery runtime escalates aged traces to manual handoff")


if __name__ == "__main__":
    main()
