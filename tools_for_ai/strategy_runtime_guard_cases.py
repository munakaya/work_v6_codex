from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import uuid4

from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy_runtime import StrategyRuntime


class DummyConnector:
    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return {
            "exchange": exchange,
            "market": market,
            "best_bid": "101574000",
            "best_ask": "101598000",
            "bid_volume": "0.3",
            "ask_volume": "0.4",
            "exchange_timestamp": now,
            "received_at": now,
            "exchange_age_ms": 0,
            "stale": False,
            "source_type": "dummy",
        }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _seed_trace(
    redis_runtime: RedisRuntime,
    *,
    recovery_trace_id: str,
    run_id: str,
    bot_id: str,
    status: str,
) -> None:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=recovery_trace_id,
        payload={
            "recovery_trace_id": recovery_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": status,
            "lifecycle_state": (
                "manual_handoff" if status == "handoff_required" else "recovery_required"
            ),
            "manual_handoff_required": status == "handoff_required",
            "residual_exposure_quote": "10",
            "created_at": now,
            "updated_at": now,
        },
    )


def _fresh_runtime(prefix: str) -> tuple[StrategyRuntime, dict[str, object]]:
    store = sample_read_store()
    store.order_intents.clear()
    store.orders.clear()
    store.fills.clear()
    run = next(
        item
        for item in store.list_strategy_runs(status="running")
        if str(item.get("run_id") or "") == "eb8f7c39-d23f-433f-b839-6d2e89d4bbd6"
    )
    redis_runtime = RedisRuntime(
        os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0"),
        prefix,
        "strategy-runtime-guard-case",
    )
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for strategy runtime guard cases")
    runtime = StrategyRuntime(
        enabled=True,
        interval_ms=1000,
        persist_intent=False,
        execution_enabled=False,
        execution_mode="simulate_success",
        auto_unwind_on_failure=False,
        read_store=store,
        connector=DummyConnector(),
        redis_runtime=redis_runtime,
    )
    return runtime, run


def main() -> None:
    recovery_prefix = f"tp_strategy_guard_recovery_{uuid4().hex[:8]}"
    recovery_runtime, recovery_run = _fresh_runtime(recovery_prefix)
    _seed_trace(
        recovery_runtime.redis_runtime,
        recovery_trace_id="rt_guard_active",
        run_id=str(recovery_run["run_id"]),
        bot_id=str(recovery_run["bot_id"]),
        status="active",
    )
    recovery_runtime._evaluate_run(recovery_run)
    recovery_info = recovery_runtime.info
    _assert(recovery_info.evaluated_count == 0, "active recovery trace should block evaluation")
    _assert(recovery_info.skipped_count == 1, "active recovery trace should count as skip")
    _assert(
        (recovery_info.last_skip_reason or "").startswith("RECOVERY_TRACE_ACTIVE"),
        "active recovery skip reason mismatch",
    )

    handoff_prefix = f"tp_strategy_guard_handoff_{uuid4().hex[:8]}"
    handoff_runtime, handoff_run = _fresh_runtime(handoff_prefix)
    _seed_trace(
        handoff_runtime.redis_runtime,
        recovery_trace_id="rt_guard_handoff",
        run_id=str(handoff_run["run_id"]),
        bot_id=str(handoff_run["bot_id"]),
        status="handoff_required",
    )
    handoff_runtime._evaluate_run(handoff_run)
    handoff_info = handoff_runtime.info
    _assert(handoff_info.evaluated_count == 0, "handoff trace should block evaluation")
    _assert(handoff_info.skipped_count == 1, "handoff trace should count as skip")
    _assert(
        (handoff_info.last_skip_reason or "").startswith("MANUAL_HANDOFF_ACTIVE"),
        "handoff skip reason mismatch",
    )

    print("PASS strategy runtime blocks evaluation when recovery trace is active")
    print("PASS strategy runtime blocks evaluation when manual handoff is active")


if __name__ == "__main__":
    main()
