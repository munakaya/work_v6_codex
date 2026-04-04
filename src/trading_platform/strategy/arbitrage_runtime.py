from __future__ import annotations

from decimal import Decimal

from .arbitrage_gate import validate_gate_conditions
from .arbitrage_models import ArbitrageDecision, ArbitrageInputs, CandidateSizeResult
from .arbitrage_planner import (
    build_decision_context,
    build_order_intent_plan,
    build_reject_decision,
)
from .arbitrage_pricing import compute_candidate_size, simulate_executable_edge
from .arbitrage_reservation import reserve_capacity
from ..storage.store_protocol import ControlPlaneStoreProtocol


def _is_risk_cap_blocked(inputs: ArbitrageInputs, notional: object) -> bool:
    cost = notional
    if cost > inputs.risk_config.max_notional_per_order:
        return True
    if cost > inputs.risk_config.max_total_notional_per_bot:
        return True
    remaining_bot_notional = inputs.runtime_state.remaining_bot_notional
    if remaining_bot_notional is not None and cost > remaining_bot_notional:
        return True
    return False


def _is_depth_insufficient(
    inputs: ArbitrageInputs, candidate_size: CandidateSizeResult
) -> bool:
    components = candidate_size.components
    required_levels = max(inputs.risk_config.min_orderbook_depth_levels, 1)
    required_notional = inputs.risk_config.min_available_depth_quote
    buy_depth_levels = int(components.get("buy_depth_levels") or "0")
    sell_depth_levels = int(components.get("sell_depth_levels") or "0")
    buy_depth_notional = Decimal(components.get("buy_depth_notional_quote") or "0")
    sell_depth_notional = Decimal(components.get("sell_depth_notional_quote") or "0")
    return (
        buy_depth_levels < required_levels
        or sell_depth_levels < required_levels
        or buy_depth_notional < required_notional
        or sell_depth_notional < required_notional
    )


def evaluate_arbitrage(inputs: ArbitrageInputs) -> ArbitrageDecision:
    gate_checks, gate_reason = validate_gate_conditions(inputs)
    gate_tuple = tuple(gate_checks)
    if gate_reason is not None:
        return build_reject_decision(
            inputs=inputs,
            reason_code=gate_reason,
            gate_checks=gate_tuple,
            candidate_size=None,
            executable_edge=None,
            reservation_plan=None,
        )

    candidate_size = compute_candidate_size(inputs)
    if candidate_size.target_qty <= 0:
        return build_reject_decision(
            inputs=inputs,
            reason_code="ORDERBOOK_DEPTH_INSUFFICIENT",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=None,
            reservation_plan=None,
        )

    if _is_depth_insufficient(inputs, candidate_size):
        return build_reject_decision(
            inputs=inputs,
            reason_code="ORDERBOOK_DEPTH_INSUFFICIENT",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=None,
            reservation_plan=None,
        )

    executable_edge = simulate_executable_edge(inputs, candidate_size)
    if executable_edge is None:
        return build_reject_decision(
            inputs=inputs,
            reason_code="EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=None,
            reservation_plan=None,
        )

    if executable_edge.executable_profit_quote < inputs.risk_config.min_profit_quote:
        return build_reject_decision(
            inputs=inputs,
            reason_code="EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=executable_edge,
            reservation_plan=None,
        )
    if executable_edge.executable_profit_bps < inputs.risk_config.min_profit_bps:
        return build_reject_decision(
            inputs=inputs,
            reason_code="EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=executable_edge,
            reservation_plan=None,
        )

    if _is_risk_cap_blocked(inputs, executable_edge.executable_buy_cost_quote):
        return build_reject_decision(
            inputs=inputs,
            reason_code="RISK_LIMIT_BLOCKED",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=executable_edge,
            reservation_plan=None,
        )

    spread_bps = (
        (executable_edge.sell_vwap - executable_edge.buy_vwap)
        / executable_edge.buy_vwap
        * 10000
    )
    if spread_bps > inputs.risk_config.max_spread_bps:
        return build_reject_decision(
            inputs=inputs,
            reason_code="RISK_LIMIT_BLOCKED",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=executable_edge,
            reservation_plan=None,
        )

    reservation_plan = reserve_capacity(inputs, candidate_size, executable_edge)
    if not reservation_plan.reservation_passed:
        return build_reject_decision(
            inputs=inputs,
            reason_code="RESERVATION_FAILED",
            gate_checks=gate_tuple,
            candidate_size=candidate_size,
            executable_edge=executable_edge,
            reservation_plan=reservation_plan,
        )

    decision_context = build_decision_context(
        inputs=inputs,
        reason_code="ARBITRAGE_OPPORTUNITY_FOUND",
        gate_checks=gate_tuple,
        candidate_size=candidate_size,
        executable_edge=executable_edge,
        reservation_plan=reservation_plan,
    )
    order_intent_plan = build_order_intent_plan(
        inputs=inputs,
        executable_edge=executable_edge,
        candidate_size=candidate_size,
        decision_context=decision_context,
    )
    return ArbitrageDecision(
        accepted=True,
        reason_code="ARBITRAGE_OPPORTUNITY_FOUND",
        gate_checks=gate_tuple,
        candidate_size=candidate_size,
        executable_edge=executable_edge,
        reservation_plan=reservation_plan,
        order_intent_plan=order_intent_plan,
        decision_context=decision_context,
    )


def persist_order_intent_plan(
    *,
    store: ControlPlaneStoreProtocol,
    decision: ArbitrageDecision,
    strategy_run_id: str,
) -> tuple[str, dict[str, object] | None]:
    if not decision.accepted or decision.order_intent_plan is None:
        return "rejected", None
    plan = decision.order_intent_plan
    return store.create_order_intent(
        strategy_run_id=strategy_run_id,
        market=plan.market,
        buy_exchange=plan.buy_exchange,
        sell_exchange=plan.sell_exchange,
        side_pair=plan.side_pair,
        target_qty=plan.target_qty,
        expected_profit=plan.expected_profit,
        expected_profit_ratio=plan.expected_profit_ratio,
        status="created",
        decision_context=plan.decision_context,
    )
