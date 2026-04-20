from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import uuid4

from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy import (
    build_pair_lock_payload,
    evaluate_arbitrage_candidate_set,
    load_candidate_strategy_inputs,
    pair_lock_identity_from_context,
    pair_lock_identity_from_payload,
    pair_lock_owner_id,
)
from trading_platform.strategy.arbitrage_runtime_loader import load_arbitrage_runtime_payload
from trading_platform.strategy_runtime import StrategyRuntime


class DummyConnector:
    _PRICE_BY_EXCHANGE = {
        "sample": {"best_bid": "99980000", "best_ask": "100000000"},
        "upbit": {"best_bid": "100450000", "best_ask": "100550000"},
        "bithumb": {"best_bid": "100420000", "best_ask": "100520000"},
        "coinone": {"best_bid": "100400000", "best_ask": "100500000"},
    }

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        price = self._PRICE_BY_EXCHANGE.get(
            exchange,
            {"best_bid": "101000000", "best_ask": "101100000"},
        )
        return {
            "exchange": exchange,
            "market": market,
            "best_bid": price["best_bid"],
            "best_ask": price["best_ask"],
            "bid_volume": "1.5",
            "ask_volume": "1.5",
            "bids": [{"price": price["best_bid"], "quantity": "1.5"}],
            "asks": [{"price": price["best_ask"], "quantity": "1.5"}],
            "exchange_timestamp": now,
            "received_at": now,
            "exchange_age_ms": 0,
            "stale": False,
            "source_type": "dummy",
            "connector_healthy": True,
        }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fresh_runtime(
    prefix: str,
    *,
    execution_enabled: bool,
    execution_mode: str,
    auto_unwind_on_failure: bool = False,
) -> tuple[StrategyRuntime, dict[str, object], DummyConnector]:
    store = sample_read_store()
    store.order_intents.clear()
    store.orders.clear()
    store.fills.clear()
    run = next(
        item
        for item in store.list_strategy_runs(status="running")
        if str(item.get("strategy_name") or "") == "arbitrage"
    )
    connector = DummyConnector()
    redis_runtime = RedisRuntime(
        os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0"),
        prefix,
        "pair-lock-runtime-case",
    )
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for pair lock runtime cases")
    runtime = StrategyRuntime(
        enabled=True,
        interval_ms=1000,
        persist_intent=True,
        execution_enabled=execution_enabled,
        execution_mode=execution_mode,
        auto_unwind_on_failure=auto_unwind_on_failure,
        read_store=store,
        connector=connector,
        redis_runtime=redis_runtime,
    )
    return runtime, run, connector


def _selected_pair_identity(
    runtime: StrategyRuntime,
    run: dict[str, object],
    connector: DummyConnector,
) -> tuple[dict[str, object], dict[str, object]]:
    load_result = load_arbitrage_runtime_payload(
        store=runtime.read_store,
        connector=connector,
        run=run,
        redis_runtime=runtime.redis_runtime,
    )
    _assert(load_result.payload is not None, "runtime payload should load for pair lock case")
    decision = evaluate_arbitrage_candidate_set(
        load_candidate_strategy_inputs(load_result.payload)
    )
    _assert(decision.accepted, "pair lock runtime case requires accepted selected_pair")
    identity = pair_lock_identity_from_context(decision.decision_context)
    _assert(identity is not None, "selected pair identity should be derivable")
    return decision.decision_context, identity


def _case_conflict_blocks_new_entry() -> None:
    runtime, run, connector = _fresh_runtime(
        f"tp_pair_lock_conflict_{uuid4().hex[:8]}",
        execution_enabled=False,
        execution_mode="simulate_success",
    )
    _, identity = _selected_pair_identity(runtime, run, connector)
    market = str(identity["market"])
    quote_pair_id = str(identity["quote_pair_id"])
    selected_pair = identity.get("selected_pair")
    foreign_payload = build_pair_lock_payload(
        bot_id="bot-foreign",
        strategy_run_id="run-foreign",
        owner_id=pair_lock_owner_id(bot_id="bot-foreign", strategy_run_id="run-foreign"),
        market=market,
        quote_pair_id=quote_pair_id,
        lifecycle_state="entry_submitting",
        selected_pair=selected_pair if isinstance(selected_pair, dict) else None,
        acquired_at=runtime.redis_runtime.now_iso(),
        intent_id="intent-foreign",
    )
    outcome, _ = runtime.redis_runtime.acquire_pair_lock(
        market=market,
        quote_pair_id=quote_pair_id,
        payload=foreign_payload,
        trace_id="pair-lock-conflict-seed",
    )
    _assert(outcome == "acquired", "foreign pair lock should be pre-acquired")

    runtime._evaluate_run(run)
    latest = runtime.redis_runtime.get_arbitrage_evaluation(run_id=str(run["run_id"]))
    _assert(latest is not None, "latest evaluation should be stored on pair lock conflict")
    _assert(latest.get("accepted") is False, "pair lock conflict must reject evaluation")
    _assert(latest.get("reason_code") == "PAIR_LOCK_ACTIVE", "pair lock reason_code mismatch")
    pair_lock_context = dict(latest.get("decision_context") or {}).get("pair_lock")
    _assert(isinstance(pair_lock_context, dict), "pair lock conflict context missing")
    _assert(pair_lock_context.get("state") == "blocked", "pair lock conflict state mismatch")
    _assert(
        runtime.read_store.list_order_intents(strategy_run_id=str(run["run_id"])) == [],
        "pair lock conflict should prevent order intent creation",
    )


def _case_submitted_lock_refreshes() -> None:
    runtime, run, _ = _fresh_runtime(
        f"tp_pair_lock_submit_{uuid4().hex[:8]}",
        execution_enabled=True,
        execution_mode="simulate_success",
    )
    runtime._evaluate_run(run)
    latest = runtime.redis_runtime.get_arbitrage_evaluation(run_id=str(run["run_id"]))
    _assert(latest is not None, "submitted case should store evaluation")
    _assert(latest.get("lifecycle_preview") == "entry_submitting", "submitted lifecycle mismatch")
    identity = pair_lock_identity_from_payload(latest)
    _assert(identity is not None, "submitted case should keep pair lock identity")
    lock_payload = runtime.redis_runtime.get_pair_lock(
        market=str(identity["market"]),
        quote_pair_id=str(identity["quote_pair_id"]),
    )
    _assert(lock_payload is not None, "submitted case should retain pair lock")
    _assert(lock_payload.get("lifecycle_state") == "entry_submitting", "submitted lock lifecycle mismatch")
    persisted_intent = dict(latest.get("persisted_intent") or {})
    _assert(
        lock_payload.get("intent_id") == persisted_intent.get("intent_id"),
        "submitted lock should point to persisted intent",
    )


def _case_filled_lock_releases() -> None:
    runtime, run, _ = _fresh_runtime(
        f"tp_pair_lock_fill_{uuid4().hex[:8]}",
        execution_enabled=True,
        execution_mode="simulate_fill",
    )
    runtime._evaluate_run(run)
    latest = runtime.redis_runtime.get_arbitrage_evaluation(run_id=str(run["run_id"]))
    _assert(latest is not None, "filled case should store evaluation")
    _assert(latest.get("lifecycle_preview") == "closed", "filled case should close lifecycle")
    identity = pair_lock_identity_from_payload(latest)
    _assert(identity is not None, "filled case should keep pair identity in payload")
    lock_payload = runtime.redis_runtime.get_pair_lock(
        market=str(identity["market"]),
        quote_pair_id=str(identity["quote_pair_id"]),
    )
    _assert(lock_payload is None, "filled and closed cycle should release pair lock")


def _case_submit_failure_keeps_recovery_lock() -> None:
    runtime, run, _ = _fresh_runtime(
        f"tp_pair_lock_failure_{uuid4().hex[:8]}",
        execution_enabled=True,
        execution_mode="simulate_failure",
        auto_unwind_on_failure=False,
    )
    runtime._evaluate_run(run)
    latest = runtime.redis_runtime.get_arbitrage_evaluation(run_id=str(run["run_id"]))
    _assert(latest is not None, "submit failure case should store evaluation")
    _assert(
        latest.get("lifecycle_preview") == "recovery_required",
        "submit failure lifecycle should move to recovery_required",
    )
    recovery_trace_id = str(latest.get("recovery_trace_id") or "")
    _assert(recovery_trace_id, "submit failure should attach recovery_trace_id")
    identity = pair_lock_identity_from_payload(latest)
    _assert(identity is not None, "submit failure should keep pair lock identity")
    lock_payload = runtime.redis_runtime.get_pair_lock(
        market=str(identity["market"]),
        quote_pair_id=str(identity["quote_pair_id"]),
    )
    _assert(lock_payload is not None, "submit failure should keep pair lock during recovery")
    _assert(
        lock_payload.get("lifecycle_state") == "recovery_required",
        "submit failure lock lifecycle mismatch",
    )
    _assert(
        lock_payload.get("recovery_trace_id") == recovery_trace_id,
        "submit failure lock should reference recovery trace",
    )


def main() -> None:
    _case_conflict_blocks_new_entry()
    _case_submitted_lock_refreshes()
    _case_filled_lock_releases()
    _case_submit_failure_keeps_recovery_lock()
    print("PASS pair lock conflict blocks duplicate selected_pair entry")
    print("PASS pair lock refreshes to entry_submitting after submit")
    print("PASS pair lock releases when filled cycle closes")
    print("PASS pair lock stays attached during recovery-required submit failure")


if __name__ == "__main__":
    main()
