from __future__ import annotations

from decimal import Decimal

from trading_platform.private_exchange_connector import PrivateExchangeResult
from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy.arbitrage_models import ArbitrageDecision, ExecutableEdgeResult
from trading_platform.strategy.arbitrage_private_connectors_execution_adapter import (
    PrivateConnectorsArbitrageExecutionAdapter,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class SuccessConnector:
    def __init__(self, exchange: str, order_id: str) -> None:
        self.exchange = exchange
        self.name = f"{exchange}:private_rest"
        self._order_id = order_id

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="ok",
            data={
                "exchange_order_id": self._order_id,
                "market": request_payload.get("market"),
                "side": request_payload.get("side"),
                "status": "submitted",
                "requested_price": request_payload.get("price"),
                "requested_qty": request_payload.get("qty"),
            },
        )


class ErrorConnector(SuccessConnector):
    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="error",
            error_code="NETWORK_ERROR",
            reason="timeout",
            retryable=True,
        )


def _decision() -> ArbitrageDecision:
    edge = ExecutableEdgeResult(
        executable_buy_cost_quote=Decimal("100000"),
        executable_sell_proceeds_quote=Decimal("100500"),
        gross_profit_quote=Decimal("500"),
        executable_profit_quote=Decimal("300"),
        executable_profit_bps=Decimal("30"),
        buy_vwap=Decimal("100.1"),
        sell_vwap=Decimal("100.6"),
        fee_buy_quote=Decimal("10"),
        fee_sell_quote=Decimal("10"),
        buy_slippage_buffer_quote=Decimal("50"),
        sell_slippage_buffer_quote=Decimal("50"),
        unwind_buffer_quote=Decimal("40"),
        rebalance_buffer_quote=Decimal("40"),
        total_fee_quote=Decimal("20"),
        total_cost_adjustment_quote=Decimal("200"),
        passed=True,
    )
    return ArbitrageDecision(
        accepted=True,
        reason_code="ARBITRAGE_OPPORTUNITY_FOUND",
        executable_edge=edge,
        decision_context={"selected_pair": {"buy_exchange": "upbit", "sell_exchange": "bithumb"}},
    )


def _intent(store) -> dict[str, object]:
    run = next(
        item
        for item in store.list_strategy_runs(status="running")
        if str(item.get("strategy_name") or "") == "arbitrage"
    )
    outcome, intent = store.create_order_intent(
        strategy_run_id=str(run["run_id"]),
        market="KRW-BTC",
        buy_exchange="upbit",
        sell_exchange="bithumb",
        side_pair="buy_then_sell",
        target_qty="0.01",
        expected_profit="300",
        expected_profit_ratio="0.003",
        status="created",
        decision_context={"selected_pair": {"buy_exchange": "upbit", "sell_exchange": "bithumb"}},
    )
    _assert(outcome == "created" and intent is not None, "intent should be created")
    return intent


def _case_submitted_success() -> None:
    store = sample_read_store()
    intent = _intent(store)
    adapter = PrivateConnectorsArbitrageExecutionAdapter(
        connectors={
            "upbit": SuccessConnector("upbit", "upbit-order-1"),
            "bithumb": SuccessConnector("bithumb", "bithumb-order-1"),
        }
    )
    result = adapter.submit(
        store=store,
        decision=_decision(),
        intent=intent,
        auto_unwind_on_failure=False,
    )
    _assert(result.outcome == "submitted", "private connectors should submit successfully")
    _assert(len(result.created_orders) == 2, "submitted result should create two orders")
    _assert(result.details.get("mode") == "private_connectors", "mode mismatch")
    first_raw = result.created_orders[0].get("raw_payload")
    _assert(isinstance(first_raw, dict), "created order raw payload missing")
    _assert(first_raw.get("submission_mode") == "private_connectors", "submission mode mismatch")


def _case_second_leg_failure_is_fail_closed() -> None:
    store = sample_read_store()
    intent = _intent(store)
    adapter = PrivateConnectorsArbitrageExecutionAdapter(
        connectors={
            "upbit": SuccessConnector("upbit", "upbit-order-2"),
            "bithumb": ErrorConnector("bithumb", "bithumb-order-2"),
        }
    )
    result = adapter.submit(
        store=store,
        decision=_decision(),
        intent=intent,
        auto_unwind_on_failure=True,
    )
    _assert(result.outcome == "submit_failed", "second leg failure should fail closed")
    _assert(len(result.created_orders) == 1, "first successful leg should remain persisted")
    _assert(result.details.get("mode") == "private_connectors", "failure mode mismatch")
    _assert(result.details.get("failed_leg") == "sell", "failed leg mismatch")
    _assert(
        result.details.get("reason") == "bithumb place_order failed: NETWORK_ERROR: timeout",
        f"failure reason mismatch: {result.details}",
    )
    orders = [
        item
        for item in store.list_orders(strategy_run_id=str(intent["strategy_run_id"]))
        if str(item.get("order_intent_id") or "") == str(intent["intent_id"])
    ]
    _assert(len(orders) == 1, "only first leg order should persist on second leg failure")


def main() -> None:
    _case_submitted_success()
    _case_second_leg_failure_is_fail_closed()
    print("PASS private_connectors adapter submits two-leg limit orders through in-process connectors")
    print("PASS private_connectors adapter fail-closes after partial submit and preserves created order evidence")


if __name__ == "__main__":
    main()
