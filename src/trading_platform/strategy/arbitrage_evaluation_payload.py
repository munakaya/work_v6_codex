from __future__ import annotations

from .arbitrage_models import ArbitrageDecision
from .arbitrage_state_machine import (
    classify_submit_failure_transition,
    derive_arbitrage_lifecycle_state,
)


def _candidate_size_payload(decision: ArbitrageDecision) -> dict[str, object] | None:
    if decision.candidate_size is None:
        return None
    return {
        "target_qty": str(decision.candidate_size.target_qty),
        "components": decision.candidate_size.components,
    }


def _executable_edge_payload(decision: ArbitrageDecision) -> dict[str, object] | None:
    if decision.executable_edge is None:
        return None
    return {
        "executable_buy_cost_quote": str(
            decision.executable_edge.executable_buy_cost_quote
        ),
        "executable_sell_proceeds_quote": str(
            decision.executable_edge.executable_sell_proceeds_quote
        ),
        "gross_profit_quote": str(decision.executable_edge.gross_profit_quote),
        "executable_profit_quote": str(decision.executable_edge.executable_profit_quote),
        "executable_profit_bps": str(decision.executable_edge.executable_profit_bps),
        "fee_buy_quote": str(decision.executable_edge.fee_buy_quote),
        "fee_sell_quote": str(decision.executable_edge.fee_sell_quote),
        "buy_slippage_buffer_quote": str(
            decision.executable_edge.buy_slippage_buffer_quote
        ),
        "sell_slippage_buffer_quote": str(
            decision.executable_edge.sell_slippage_buffer_quote
        ),
        "unwind_buffer_quote": str(decision.executable_edge.unwind_buffer_quote),
        "rebalance_buffer_quote": str(decision.executable_edge.rebalance_buffer_quote),
        "total_fee_quote": str(decision.executable_edge.total_fee_quote),
        "total_cost_adjustment_quote": str(
            decision.executable_edge.total_cost_adjustment_quote
        ),
    }


def _reservation_plan_payload(decision: ArbitrageDecision) -> dict[str, object] | None:
    if decision.reservation_plan is None:
        return None
    return {
        "reservation_passed": decision.reservation_plan.reservation_passed,
        "reason_code": decision.reservation_plan.reason_code,
        "quote_required": str(decision.reservation_plan.quote_required),
        "base_required": str(decision.reservation_plan.base_required),
        "reserved_notional": str(decision.reservation_plan.reserved_notional),
        "details": decision.reservation_plan.details,
    }


def _submit_failure_preview(decision: ArbitrageDecision) -> dict[str, object] | None:
    if not decision.accepted:
        return None
    reservation_passed = bool(
        decision.reservation_plan and decision.reservation_plan.reservation_passed
    )
    without_auto_unwind = classify_submit_failure_transition(
        decision_accepted=True,
        reservation_passed=reservation_passed,
        submit_failed=True,
        auto_unwind_allowed=False,
    )
    with_auto_unwind = classify_submit_failure_transition(
        decision_accepted=True,
        reservation_passed=reservation_passed,
        submit_failed=True,
        auto_unwind_allowed=True,
    )
    return {
        "without_auto_unwind": without_auto_unwind["next_state"],
        "with_auto_unwind": with_auto_unwind["next_state"],
    }


def build_arbitrage_evaluation_payload(
    *,
    decision: ArbitrageDecision,
    bot_id: str,
    strategy_run_id: str,
    persisted_intent: dict[str, object] | None = None,
    lifecycle_preview_override: str | None = None,
    submit_result: dict[str, object] | None = None,
) -> dict[str, object]:
    lifecycle_preview = lifecycle_preview_override or derive_arbitrage_lifecycle_state(
        decision_accepted=decision.accepted,
        has_order_intents=persisted_intent is not None,
        has_submitted_orders=False,
        has_open_orders=False,
        hedge_balanced=False,
        recovery_required=False,
        unwind_in_progress=False,
        manual_handoff=False,
    )
    payload = {
        "bot_id": bot_id,
        "strategy_run_id": strategy_run_id,
        "accepted": decision.accepted,
        "reason_code": decision.reason_code,
        "lifecycle_preview": lifecycle_preview,
        "decision_context": decision.decision_context,
        "candidate_size": _candidate_size_payload(decision),
        "executable_edge": _executable_edge_payload(decision),
        "reservation_plan": _reservation_plan_payload(decision),
    }
    submit_failure_preview = _submit_failure_preview(decision)
    if submit_failure_preview is not None:
        payload["submit_failure_preview"] = submit_failure_preview
    if persisted_intent is not None:
        payload["persisted_intent"] = persisted_intent
    if submit_result is not None:
        payload["submit_result"] = submit_result
    return payload
