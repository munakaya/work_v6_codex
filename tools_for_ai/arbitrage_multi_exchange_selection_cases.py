from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from trading_platform.strategy import (
    evaluate_arbitrage_candidate_set,
    load_candidate_strategy_inputs,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _base_payload() -> dict[str, object]:
    now = datetime.now(UTC)
    now_text = now.isoformat().replace('+00:00', 'Z')
    return {
        'bot_id': 'bot-arb-001',
        'strategy_run_id': 'run-arb-001',
        'canonical_symbol': 'BTC-KRW',
        'market': 'BTC-KRW',
        'candidate_exchanges': ['upbit', 'bithumb', 'coinone'],
        'orderbooks_by_exchange': {
            'upbit': {
                'exchange_name': 'upbit',
                'market': 'BTC-KRW',
                'observed_at': now_text,
                'asks': [{'price': '100', 'quantity': '2.0'}],
                'bids': [{'price': '99', 'quantity': '2.0'}],
                'connector_healthy': True,
            },
            'bithumb': {
                'exchange_name': 'bithumb',
                'market': 'BTC-KRW',
                'observed_at': now_text,
                'asks': [{'price': '104', 'quantity': '2.0'}],
                'bids': [{'price': '105', 'quantity': '2.0'}],
                'connector_healthy': True,
            },
            'coinone': {
                'exchange_name': 'coinone',
                'market': 'BTC-KRW',
                'observed_at': now_text,
                'asks': [{'price': '107', 'quantity': '2.0'}],
                'bids': [{'price': '108', 'quantity': '2.0'}],
                'connector_healthy': True,
            },
        },
        'balances_by_exchange': {
            'upbit': {
                'exchange_name': 'upbit',
                'base_asset': 'BTC',
                'quote_asset': 'KRW',
                'available_base': '2.0',
                'available_quote': '500',
                'observed_at': now_text,
                'is_fresh': True,
            },
            'bithumb': {
                'exchange_name': 'bithumb',
                'base_asset': 'BTC',
                'quote_asset': 'KRW',
                'available_base': '2.0',
                'available_quote': '500',
                'observed_at': now_text,
                'is_fresh': True,
            },
            'coinone': {
                'exchange_name': 'coinone',
                'base_asset': 'BTC',
                'quote_asset': 'KRW',
                'available_base': '2.0',
                'available_quote': '500',
                'observed_at': now_text,
                'is_fresh': True,
            },
        },
        'risk_config': {
            'min_profit_quote': '1',
            'min_profit_bps': '1',
            'max_clock_skew_ms': 500,
            'max_orderbook_age_ms': 5000,
            'max_balance_age_ms': 5000,
            'max_notional_per_order': '500',
            'max_total_notional_per_bot': '500',
            'max_spread_bps': '1500',
            'slippage_buffer_bps': '0',
            'unwind_buffer_quote': '0',
            'rebalance_buffer_quote': '0',
            'taker_fee_bps_buy': '0',
            'taker_fee_bps_sell': '0',
            'reentry_cooldown_seconds': 30,
        },
        'runtime_state': {
            'now': now_text,
            'open_order_count': 0,
            'open_order_cap': 5,
            'unwind_in_progress': False,
            'connector_private_healthy': True,
            'duplicate_intent_active': False,
            'recent_unwind_at': None,
            'remaining_bot_notional': '500',
        },
    }


def _case_select_best_pair() -> None:
    decision = evaluate_arbitrage_candidate_set(
        load_candidate_strategy_inputs(_base_payload())
    )
    selection = dict(decision.decision_context.get('selection') or {})
    selected_pair = dict(selection.get('selected_pair') or {})
    rejected_candidates = list(selection.get('rejected_candidates') or [])
    _assert(decision.accepted is True, 'multi-exchange selection should accept best candidate')
    _assert(decision.reason_code == 'ARBITRAGE_OPPORTUNITY_FOUND', 'selected reason code mismatch')
    _assert(selected_pair.get('buy_exchange') == 'upbit', 'best selected buy exchange mismatch')
    _assert(selected_pair.get('sell_exchange') == 'coinone', 'best selected sell exchange mismatch')
    _assert(
        selected_pair.get('selection_status') == 'selected',
        'selected pair status should be selected',
    )
    _assert(
        decision.order_intent_plan is not None
        and decision.order_intent_plan.buy_exchange == 'upbit'
        and decision.order_intent_plan.sell_exchange == 'coinone',
        'order intent plan should use the selected best pair',
    )
    _assert(
        any(item.get('selection_status') == 'accepted_unselected' for item in rejected_candidates),
        'selection should keep accepted but unselected candidates for analysis',
    )
    _assert(
        int(selection.get('accepted_candidate_count') or 0) >= 2,
        'selection should record multiple accepted candidates before ranking',
    )


def _case_all_rejected_records_top_reject() -> None:
    payload = deepcopy(_base_payload())
    stale_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat().replace('+00:00', 'Z')
    for exchange in payload['orderbooks_by_exchange'].values():
        exchange['observed_at'] = stale_at
    decision = evaluate_arbitrage_candidate_set(load_candidate_strategy_inputs(payload))
    selection = dict(decision.decision_context.get('selection') or {})
    _assert(decision.accepted is False, 'stale multi-exchange candidates should reject')
    _assert(selection.get('selected_pair') is None, 'reject path should not report selected_pair')
    top_rejected = dict(selection.get('top_rejected_candidate') or {})
    _assert(top_rejected.get('selection_status') == 'top_rejected', 'top rejected candidate missing')
    _assert(top_rejected.get('reason_code') == 'ORDERBOOK_STALE', 'top rejected reason mismatch')


def main() -> None:
    _case_select_best_pair()
    _case_all_rejected_records_top_reject()
    print('PASS multi-exchange selection chooses the best accepted pair and preserves unselected candidates')
    print('PASS multi-exchange reject path keeps top rejected candidate without selected_pair')


if __name__ == '__main__':
    main()
