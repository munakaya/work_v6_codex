from __future__ import annotations

from decimal import Decimal

from .arbitrage_input_loader import load_candidate_strategy_inputs
from .arbitrage_models import (
    ArbitrageCandidateInputs,
    ArbitrageDecision,
    ArbitrageInputs,
    OrderIntentPlan,
)
from .arbitrage_runtime import evaluate_arbitrage


def _pair_inputs(
    candidate_inputs: ArbitrageCandidateInputs,
    *,
    buy_exchange: str,
    sell_exchange: str,
) -> ArbitrageInputs:
    return ArbitrageInputs(
        bot_id=candidate_inputs.bot_id,
        strategy_run_id=candidate_inputs.strategy_run_id,
        canonical_symbol=candidate_inputs.canonical_symbol,
        market=candidate_inputs.market,
        base_exchange=buy_exchange,
        hedge_exchange=sell_exchange,
        base_orderbook=candidate_inputs.orderbooks_by_exchange[buy_exchange],
        hedge_orderbook=candidate_inputs.orderbooks_by_exchange[sell_exchange],
        base_balance=candidate_inputs.balances_by_exchange[buy_exchange],
        hedge_balance=candidate_inputs.balances_by_exchange[sell_exchange],
        risk_config=candidate_inputs.risk_config,
        runtime_state=candidate_inputs.runtime_state,
    )


def _max_orderbook_age_ms(inputs: ArbitrageInputs) -> int:
    now = inputs.runtime_state.now
    return max(
        max(0, int((now - inputs.base_orderbook.observed_at).total_seconds() * 1000)),
        max(0, int((now - inputs.hedge_orderbook.observed_at).total_seconds() * 1000)),
    )


def _profit_quote(decision: ArbitrageDecision) -> Decimal:
    if decision.executable_edge is None:
        return Decimal('-1000000000000000000')
    return decision.executable_edge.executable_profit_quote


def _profit_bps(decision: ArbitrageDecision) -> Decimal:
    if decision.executable_edge is None:
        return Decimal('-1000000000000000000')
    return decision.executable_edge.executable_profit_bps


def _candidate_summary(
    *,
    inputs: ArbitrageInputs,
    decision: ArbitrageDecision,
    selection_status: str,
) -> dict[str, object]:
    executable_edge = decision.executable_edge
    return {
        'buy_exchange': inputs.base_exchange,
        'sell_exchange': inputs.hedge_exchange,
        'quote_pair_id': str(decision.decision_context.get('quote_pair_id') or ''),
        'accepted': decision.accepted,
        'selection_status': selection_status,
        'reason_code': decision.reason_code,
        'executable_profit_quote': (
            str(executable_edge.executable_profit_quote)
            if executable_edge is not None
            else None
        ),
        'executable_profit_bps': (
            str(executable_edge.executable_profit_bps)
            if executable_edge is not None
            else None
        ),
        'max_orderbook_age_ms': _max_orderbook_age_ms(inputs),
        'clock_skew_ms': int(decision.decision_context.get('clock_skew_ms') or 0),
    }


def _selection_context(
    *,
    decision: ArbitrageDecision,
    candidate_exchanges: tuple[str, ...],
    selected_summary: dict[str, object] | None,
    top_rejected_summary: dict[str, object] | None,
    candidate_summaries: list[dict[str, object]],
) -> dict[str, object]:
    selection = {
        'candidate_exchanges': list(candidate_exchanges),
        'selected_pair': selected_summary,
        'top_rejected_candidate': top_rejected_summary,
        'evaluated_pairs': candidate_summaries,
        'rejected_candidates': [
            item
            for item in candidate_summaries
            if item['selection_status'] in {'accepted_unselected', 'rejected', 'top_rejected'}
        ],
        'accepted_candidate_count': sum(1 for item in candidate_summaries if item['accepted']),
    }
    return {
        **decision.decision_context,
        'candidate_exchanges': list(candidate_exchanges),
        'selected_pair': selected_summary,
        'selection': selection,
    }


def _with_selection_context(
    *,
    decision: ArbitrageDecision,
    candidate_exchanges: tuple[str, ...],
    selected_summary: dict[str, object] | None,
    top_rejected_summary: dict[str, object] | None,
    candidate_summaries: list[dict[str, object]],
) -> ArbitrageDecision:
    decision_context = _selection_context(
        decision=decision,
        candidate_exchanges=candidate_exchanges,
        selected_summary=selected_summary,
        top_rejected_summary=top_rejected_summary,
        candidate_summaries=candidate_summaries,
    )
    order_intent_plan = decision.order_intent_plan
    if order_intent_plan is not None:
        order_intent_plan = OrderIntentPlan(
            market=order_intent_plan.market,
            buy_exchange=order_intent_plan.buy_exchange,
            sell_exchange=order_intent_plan.sell_exchange,
            side_pair=order_intent_plan.side_pair,
            target_qty=order_intent_plan.target_qty,
            expected_profit=order_intent_plan.expected_profit,
            expected_profit_ratio=order_intent_plan.expected_profit_ratio,
            decision_context=decision_context,
        )
    return ArbitrageDecision(
        accepted=decision.accepted,
        reason_code=decision.reason_code,
        gate_checks=decision.gate_checks,
        candidate_size=decision.candidate_size,
        executable_edge=decision.executable_edge,
        reservation_plan=decision.reservation_plan,
        order_intent_plan=order_intent_plan,
        decision_context=decision_context,
    )


def _accepted_rank(entry: tuple[ArbitrageInputs, ArbitrageDecision]) -> tuple[Decimal, Decimal, int, int]:
    inputs, decision = entry
    return (
        _profit_quote(decision),
        _profit_bps(decision),
        -_max_orderbook_age_ms(inputs),
        -int(decision.decision_context.get('clock_skew_ms') or 0),
    )


def _fallback_rank(entry: tuple[ArbitrageInputs, ArbitrageDecision]) -> tuple[Decimal, Decimal, int, int]:
    inputs, decision = entry
    return (
        _profit_quote(decision),
        _profit_bps(decision),
        -_max_orderbook_age_ms(inputs),
        -int(decision.decision_context.get('clock_skew_ms') or 0),
    )


def evaluate_arbitrage_candidate_set(
    candidate_inputs: ArbitrageCandidateInputs,
) -> ArbitrageDecision:
    if len(candidate_inputs.candidate_exchanges) < 2:
        raise ValueError('candidate_exchanges must include at least two exchanges')

    evaluated: list[tuple[ArbitrageInputs, ArbitrageDecision]] = []
    for buy_exchange in candidate_inputs.candidate_exchanges:
        for sell_exchange in candidate_inputs.candidate_exchanges:
            if buy_exchange == sell_exchange:
                continue
            inputs = _pair_inputs(
                candidate_inputs,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
            )
            evaluated.append((inputs, evaluate_arbitrage(inputs)))

    accepted = [entry for entry in evaluated if entry[1].accepted]
    has_selected_pair = bool(accepted)
    if has_selected_pair:
        selected_inputs, selected_decision = max(accepted, key=_accepted_rank)
    else:
        selected_inputs, selected_decision = max(evaluated, key=_fallback_rank)

    selected_quote_pair_id = str(selected_decision.decision_context.get('quote_pair_id') or '')
    candidate_summaries: list[dict[str, object]] = []
    selected_summary: dict[str, object] | None = None
    top_rejected_summary: dict[str, object] | None = None
    for inputs, decision in evaluated:
        quote_pair_id = str(decision.decision_context.get('quote_pair_id') or '')
        selection_status = 'rejected'
        if quote_pair_id == selected_quote_pair_id and inputs == selected_inputs:
            selection_status = 'selected' if has_selected_pair else 'top_rejected'
        elif decision.accepted:
            selection_status = 'accepted_unselected'
        summary = _candidate_summary(
            inputs=inputs,
            decision=decision,
            selection_status=selection_status,
        )
        candidate_summaries.append(summary)
        if selection_status == 'selected':
            selected_summary = summary
        if selection_status == 'top_rejected':
            top_rejected_summary = summary

    return _with_selection_context(
        decision=selected_decision,
        candidate_exchanges=candidate_inputs.candidate_exchanges,
        selected_summary=selected_summary,
        top_rejected_summary=top_rejected_summary,
        candidate_summaries=candidate_summaries,
    )


def evaluate_arbitrage_candidate_payload(payload: dict[str, object]) -> ArbitrageDecision:
    return evaluate_arbitrage_candidate_set(load_candidate_strategy_inputs(payload))
