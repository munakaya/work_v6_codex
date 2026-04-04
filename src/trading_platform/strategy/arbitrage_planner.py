from __future__ import annotations

from decimal import Decimal

from .arbitrage_models import (
    ArbitrageDecision,
    ArbitrageInputs,
    CandidateSizeResult,
    ExecutableEdgeResult,
    GateCheckResult,
    OrderIntentPlan,
    ReservationPlan,
)


def _serialize_gate_checks(checks: tuple[GateCheckResult, ...]) -> list[dict[str, object]]:
    return [
        {
            "name": check.name,
            "passed": check.passed,
            "detail": check.detail,
        }
        for check in checks
    ]


def build_decision_context(
    *,
    inputs: ArbitrageInputs,
    reason_code: str,
    gate_checks: tuple[GateCheckResult, ...],
    candidate_size: CandidateSizeResult | None,
    executable_edge: ExecutableEdgeResult | None,
    reservation_plan: ReservationPlan | None,
) -> dict[str, object]:
    skew_ms = abs(
        int(
            (
                inputs.base_orderbook.observed_at - inputs.hedge_orderbook.observed_at
            ).total_seconds()
            * 1000
        )
    )
    computed = {
        "target_qty": str(candidate_size.target_qty) if candidate_size is not None else None,
        "buy_depth_levels": (
            candidate_size.components.get("buy_depth_levels")
            if candidate_size is not None
            else None
        ),
        "sell_depth_levels": (
            candidate_size.components.get("sell_depth_levels")
            if candidate_size is not None
            else None
        ),
        "buy_depth_notional_quote": (
            candidate_size.components.get("buy_depth_notional_quote")
            if candidate_size is not None
            else None
        ),
        "sell_depth_notional_quote": (
            candidate_size.components.get("sell_depth_notional_quote")
            if candidate_size is not None
            else None
        ),
        "executable_buy_cost_quote": (
            str(executable_edge.executable_buy_cost_quote)
            if executable_edge is not None
            else None
        ),
        "executable_sell_proceeds_quote": (
            str(executable_edge.executable_sell_proceeds_quote)
            if executable_edge is not None
            else None
        ),
        "gross_profit_quote": (
            str(executable_edge.gross_profit_quote) if executable_edge is not None else None
        ),
        "executable_profit_quote": (
            str(executable_edge.executable_profit_quote)
            if executable_edge is not None
            else None
        ),
        "executable_profit_bps": (
            str(executable_edge.executable_profit_bps)
            if executable_edge is not None
            else None
        ),
        "fee_buy_quote": (
            str(executable_edge.fee_buy_quote) if executable_edge is not None else None
        ),
        "fee_sell_quote": (
            str(executable_edge.fee_sell_quote) if executable_edge is not None else None
        ),
        "buy_slippage_buffer_quote": (
            str(executable_edge.buy_slippage_buffer_quote)
            if executable_edge is not None
            else None
        ),
        "sell_slippage_buffer_quote": (
            str(executable_edge.sell_slippage_buffer_quote)
            if executable_edge is not None
            else None
        ),
        "unwind_buffer_quote": (
            str(executable_edge.unwind_buffer_quote)
            if executable_edge is not None
            else None
        ),
        "rebalance_buffer_quote": (
            str(executable_edge.rebalance_buffer_quote)
            if executable_edge is not None
            else None
        ),
        "total_cost_adjustment_quote": (
            str(executable_edge.total_cost_adjustment_quote)
            if executable_edge is not None
            else None
        ),
        "depth_passed": _depth_passed(inputs=inputs, candidate_size=candidate_size),
    }
    reservation = {
        "reservation_passed": (
            reservation_plan.reservation_passed if reservation_plan is not None else False
        ),
        "quote_required": (
            str(reservation_plan.quote_required) if reservation_plan is not None else None
        ),
        "base_required": (
            str(reservation_plan.base_required) if reservation_plan is not None else None
        ),
        "details": reservation_plan.details if reservation_plan is not None else {},
    }
    return {
        "decision_id": f"{inputs.strategy_run_id}:{inputs.runtime_state.now.isoformat()}",
        "quote_pair_id": (
            f"{inputs.base_exchange}:{inputs.market}|{inputs.hedge_exchange}:{inputs.market}"
        ),
        "clock_skew_ms": skew_ms,
        "gate_checks": _serialize_gate_checks(gate_checks),
        "computed": computed,
        "reservation": reservation,
        "reservation_passed": reservation["reservation_passed"],
        "reason_code": reason_code,
    }


def _depth_passed(
    *,
    inputs: ArbitrageInputs,
    candidate_size: CandidateSizeResult | None,
) -> bool:
    if candidate_size is None:
        return False
    buy_depth_levels = int(candidate_size.components.get("buy_depth_levels") or "0")
    sell_depth_levels = int(candidate_size.components.get("sell_depth_levels") or "0")
    buy_depth_notional = candidate_size.components.get("buy_depth_notional_quote") or "0"
    sell_depth_notional = candidate_size.components.get("sell_depth_notional_quote") or "0"
    required_levels = max(inputs.risk_config.min_orderbook_depth_levels, 1)
    required_notional = inputs.risk_config.min_available_depth_quote
    return (
        buy_depth_levels >= required_levels
        and sell_depth_levels >= required_levels
        and Decimal(buy_depth_notional) >= required_notional
        and Decimal(sell_depth_notional) >= required_notional
    )


def build_order_intent_plan(
    *,
    inputs: ArbitrageInputs,
    executable_edge: ExecutableEdgeResult,
    candidate_size: CandidateSizeResult,
    decision_context: dict[str, object],
) -> OrderIntentPlan:
    return OrderIntentPlan(
        market=inputs.market,
        buy_exchange=inputs.base_exchange,
        sell_exchange=inputs.hedge_exchange,
        side_pair="buy_then_sell",
        target_qty=str(candidate_size.target_qty),
        expected_profit=str(executable_edge.executable_profit_quote),
        expected_profit_ratio=str(executable_edge.executable_profit_bps),
        decision_context=decision_context,
    )


def build_reject_decision(
    *,
    inputs: ArbitrageInputs,
    reason_code: str,
    gate_checks: tuple[GateCheckResult, ...],
    candidate_size: CandidateSizeResult | None,
    executable_edge: ExecutableEdgeResult | None,
    reservation_plan: ReservationPlan | None,
) -> ArbitrageDecision:
    decision_context = build_decision_context(
        inputs=inputs,
        reason_code=reason_code,
        gate_checks=gate_checks,
        candidate_size=candidate_size,
        executable_edge=executable_edge,
        reservation_plan=reservation_plan,
    )
    return ArbitrageDecision(
        accepted=False,
        reason_code=reason_code,
        gate_checks=gate_checks,
        candidate_size=candidate_size,
        executable_edge=executable_edge,
        reservation_plan=reservation_plan,
        decision_context=decision_context,
    )
