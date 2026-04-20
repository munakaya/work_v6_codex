from __future__ import annotations

from .arbitrage_models import ArbitrageDecision, OrderIntentPlan


ACTIVE_PAIR_LOCK_LIFECYCLE_STATES = {
    'manual_handoff',
    'unwind_in_progress',
    'recovery_required',
    'entry_open',
    'entry_submitting',
    'hedge_balanced',
    'intent_created',
}


def pair_lock_owner_id(*, bot_id: str, strategy_run_id: str) -> str:
    return f'{bot_id}:{strategy_run_id}'


def pair_lock_identity_from_context(
    decision_context: dict[str, object] | None,
    *,
    market: str | None = None,
) -> dict[str, object] | None:
    if not isinstance(decision_context, dict):
        return None
    quote_pair_id = str(decision_context.get('quote_pair_id') or '').strip()
    if not quote_pair_id:
        return None
    selected_pair = decision_context.get('selected_pair')
    normalized_selected_pair = selected_pair if isinstance(selected_pair, dict) else None
    normalized_market = str(market or '').strip()
    if not normalized_market and normalized_selected_pair is not None:
        normalized_market = str(normalized_selected_pair.get('market') or '').strip()
    return {
        'market': normalized_market,
        'quote_pair_id': quote_pair_id,
        'selected_pair': normalized_selected_pair,
    }


def pair_lock_identity_from_payload(payload: dict[str, object]) -> dict[str, object] | None:
    market = str(payload.get('market') or '').strip()
    decision_context = payload.get('decision_context')
    if not isinstance(decision_context, dict):
        return None
    return pair_lock_identity_from_context(decision_context, market=market)


def should_hold_pair_lock(payload: dict[str, object]) -> bool:
    lifecycle_preview = str(payload.get('lifecycle_preview') or '').strip()
    if lifecycle_preview not in ACTIVE_PAIR_LOCK_LIFECYCLE_STATES:
        return False
    return pair_lock_identity_from_payload(payload) is not None


def pair_lock_acquired_at(decision_context: dict[str, object] | None) -> str | None:
    if not isinstance(decision_context, dict):
        return None
    pair_lock = decision_context.get('pair_lock')
    if not isinstance(pair_lock, dict):
        return None
    acquired_at = str(pair_lock.get('acquired_at') or '').strip()
    return acquired_at or None


def build_pair_lock_payload(
    *,
    bot_id: str,
    strategy_run_id: str,
    owner_id: str,
    market: str,
    quote_pair_id: str,
    lifecycle_state: str,
    selected_pair: dict[str, object] | None,
    acquired_at: str,
    intent_id: str | None = None,
    recovery_trace_id: str | None = None,
) -> dict[str, object]:
    return {
        'owner_id': owner_id,
        'bot_id': bot_id,
        'strategy_run_id': strategy_run_id,
        'market': market,
        'quote_pair_id': quote_pair_id,
        'selected_pair': selected_pair,
        'lifecycle_state': lifecycle_state,
        'intent_id': intent_id,
        'recovery_trace_id': recovery_trace_id,
        'acquired_at': acquired_at,
    }


def build_pair_lock_blocked_decision(
    *,
    decision: ArbitrageDecision,
    existing_lock: dict[str, object] | None,
) -> ArbitrageDecision:
    decision_context = {
        **decision.decision_context,
        'pair_lock': {
            'state': 'blocked',
            'existing_lock': existing_lock or {},
        },
    }
    return ArbitrageDecision(
        accepted=False,
        reason_code='PAIR_LOCK_ACTIVE',
        gate_checks=decision.gate_checks,
        candidate_size=decision.candidate_size,
        executable_edge=decision.executable_edge,
        reservation_plan=decision.reservation_plan,
        order_intent_plan=None,
        decision_context=decision_context,
    )


def attach_pair_lock_context(
    *,
    decision: ArbitrageDecision,
    pair_lock_payload: dict[str, object],
    state: str = 'acquired',
) -> ArbitrageDecision:
    decision_context = {
        **decision.decision_context,
        'pair_lock': {
            'state': state,
            **pair_lock_payload,
        },
    }
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
