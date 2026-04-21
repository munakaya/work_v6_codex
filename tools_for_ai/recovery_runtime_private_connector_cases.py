from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4

from trading_platform.private_exchange_connector import PrivateExchangeResult
from trading_platform.recovery_runtime import RecoveryRuntime
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store


class FakeConnector:
    def __init__(
        self,
        *,
        exchange: str,
        order_statuses: dict[str, dict[str, object]],
        balances: list[dict[str, object]],
    ) -> None:
        self.exchange = exchange
        self.name = f"{exchange}:fake"
        self._order_statuses = order_statuses
        self._balances = balances

    @property
    def info(self):
        raise NotImplementedError

    @property
    def private_ws_monitor(self):
        raise NotImplementedError

    def get_balances(self) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="ok",
            data={"items": list(self._balances), "count": len(self._balances)},
        )

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        raise NotImplementedError

    def get_order_status(self, *, exchange_order_id: str, market: str) -> PrivateExchangeResult:
        payload = self._order_statuses.get(exchange_order_id)
        if payload is None:
            return PrivateExchangeResult(
                outcome="error",
                error_code="ORDER_NOT_FOUND",
                reason="missing fake order status",
                retryable=False,
            )
        return PrivateExchangeResult(outcome="ok", data={**payload, "market": market})

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        items = [
            {**payload, "exchange_order_id": order_id}
            for order_id, payload in self._order_statuses.items()
            if str(payload.get("status") or "").strip().lower() not in {"filled", "cancelled", "rejected", "expired", "failed"}
        ]
        return PrivateExchangeResult(outcome="ok", data={"items": items, "count": len(items)})


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _make_runtime(*, connectors: dict[str, FakeConnector]) -> tuple[RecoveryRuntime, RedisRuntime, object, str, str]:
    redis_url = os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0")
    prefix = f"tp_recovery_private_connector_case_{uuid4().hex[:8]}"
    redis_runtime = RedisRuntime(redis_url, prefix, "recovery-private-connector-case")
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for recovery private connector cases")
    store = sample_read_store()
    run = next(
        item
        for item in store.list_strategy_runs(status="running")
        if str(item.get("strategy_name") or "") == "arbitrage"
    )
    runtime = RecoveryRuntime(
        enabled=True,
        interval_ms=1000,
        handoff_after_seconds=30,
        submit_timeout_seconds=5,
        reconciliation_mismatch_handoff_count=2,
        reconciliation_stale_after_seconds=30,
        read_store=store,
        redis_runtime=redis_runtime,
        private_exchange_connectors=connectors,
    )
    return runtime, redis_runtime, store, str(run["bot_id"]), str(run["run_id"])


def _seed_intent_and_orders(store, *, run_id: str, suffix: str) -> tuple[str, list[dict[str, object]]]:
    outcome, intent = store.create_order_intent(
        strategy_run_id=run_id,
        market="KRW-BTC",
        buy_exchange="upbit",
        sell_exchange="bithumb",
        side_pair="buy_then_sell",
        target_qty="0.1",
        expected_profit="1000",
        expected_profit_ratio="0.01",
        status="submitted",
        decision_context={"source": suffix},
    )
    _assert(outcome == "created" and intent is not None, f"{suffix}: intent create failed")
    created_orders = []
    for exchange_name, exchange_order_id, side in (
        ("upbit", f"upbit-{suffix}", "buy"),
        ("bithumb", f"bithumb-{suffix}", "sell"),
    ):
        order_outcome, order = store.create_order(
            order_intent_id=str(intent["intent_id"]),
            exchange_name=exchange_name,
            exchange_order_id=exchange_order_id,
            market="KRW-BTC",
            side=side,
            requested_price="100000",
            requested_qty="0.1",
            status="submitted",
            raw_payload={"source": suffix},
        )
        _assert(order_outcome == "created" and order is not None, f"{suffix}: order create failed")
        created_orders.append(order)
    return str(intent["intent_id"]), created_orders


def _case_auto_reconciliation_resolves_zero_residual() -> None:
    connectors = {
        "upbit": FakeConnector(
            exchange="upbit",
            order_statuses={
                "upbit-resolve": {
                    "status": "filled",
                    "filled_qty": "0.1",
                    "avg_fill_price": "100000",
                }
            },
            balances=[
                {"currency": "KRW", "available": "1000000", "locked": "0"},
                {"currency": "BTC", "available": "0", "locked": "0"},
            ],
        ),
        "bithumb": FakeConnector(
            exchange="bithumb",
            order_statuses={
                "bithumb-resolve": {
                    "status": "filled",
                    "filled_qty": "0.1",
                    "avg_fill_price": "100500",
                }
            },
            balances=[
                {"currency": "KRW", "available": "500000", "locked": "0"},
                {"currency": "BTC", "available": "0", "locked": "0"},
            ],
        ),
    }
    runtime, redis_runtime, store, bot_id, run_id = _make_runtime(connectors=connectors)
    intent_id, _orders = _seed_intent_and_orders(store, run_id=run_id, suffix="resolve")
    trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=trace_id,
        payload={
            "recovery_trace_id": trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": intent_id,
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    trace = redis_runtime.get_recovery_trace(recovery_trace_id=trace_id)
    _assert(trace is not None, "resolve trace missing")
    _assert(trace.get("status") == "resolved", f"resolve trace status mismatch: {trace}")
    _assert(
        trace.get("resolution_reason") == "reconciliation_matched_zero_residual",
        f"resolve trace resolution mismatch: {trace}",
    )
    _assert(
        trace.get("reconciliation_source") == "auto_private_connectors",
        f"resolve trace source mismatch: {trace}",
    )
    _assert(
        trace.get("reconciliation_open_order_count") == 0,
        f"resolve trace open order count mismatch: {trace}",
    )


def _case_auto_reconciliation_handoffs_residual_without_open_orders() -> None:
    connectors = {
        "upbit": FakeConnector(
            exchange="upbit",
            order_statuses={
                "upbit-residual": {
                    "status": "filled",
                    "filled_qty": "0.1",
                    "avg_fill_price": "100000",
                }
            },
            balances=[
                {"currency": "KRW", "available": "0", "locked": "0"},
                {"currency": "BTC", "available": "0.1", "locked": "0"},
            ],
        ),
        "bithumb": FakeConnector(
            exchange="bithumb",
            order_statuses={
                "bithumb-residual": {
                    "status": "cancelled",
                    "filled_qty": "0",
                    "avg_fill_price": "100500",
                }
            },
            balances=[
                {"currency": "KRW", "available": "500000", "locked": "0"},
                {"currency": "BTC", "available": "0", "locked": "0"},
            ],
        ),
    }
    runtime, redis_runtime, store, bot_id, run_id = _make_runtime(connectors=connectors)
    intent_id, _orders = _seed_intent_and_orders(store, run_id=run_id, suffix="residual")
    trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=trace_id,
        payload={
            "recovery_trace_id": trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": intent_id,
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "10000",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=2)),
        },
    )
    runtime.run_once()
    trace = redis_runtime.get_recovery_trace(recovery_trace_id=trace_id)
    _assert(trace is not None, "residual trace missing")
    _assert(
        trace.get("status") == "handoff_required",
        f"residual trace status mismatch: {trace}",
    )
    _assert(
        trace.get("handoff_reason") == "reconciliation_mismatch_residual_without_orders",
        f"residual trace handoff reason mismatch: {trace}",
    )
    residual = Decimal(str(trace.get("reconciliation_residual_exposure_quote") or "0"))
    _assert(residual > Decimal("0"), f"residual trace exposure mismatch: {trace}")
    _assert(
        trace.get("reconciliation_open_order_count") == 0,
        f"residual trace open order count mismatch: {trace}",
    )


def main() -> None:
    _case_auto_reconciliation_resolves_zero_residual()
    _case_auto_reconciliation_handoffs_residual_without_open_orders()
    print("PASS recovery runtime auto-reconciles private connector evidence and resolves zero residual traces")
    print("PASS recovery runtime auto-reconciles private connector evidence and hands off residual mismatch without open orders")


if __name__ == "__main__":
    main()
