from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from .arbitrage_models import (
    ArbitrageCandidateInputs,
    ArbitrageInputs,
    BalanceSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
    RiskConfig,
    RuntimeState,
)


def _parse_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not isinstance(value, str):
        raise TypeError('datetime must be str or datetime')
    normalized = value.replace('Z', '+00:00')
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_levels(levels: list[dict[str, object]]) -> tuple[OrderbookLevel, ...]:
    return tuple(
        OrderbookLevel(
            price=_parse_decimal(item['price']),
            quantity=_parse_decimal(item['quantity']),
        )
        for item in levels
    )


def _load_orderbook_snapshot(payload: dict[str, object]) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        exchange_name=str(payload['exchange_name']),
        market=str(payload['market']),
        observed_at=_parse_datetime(payload['observed_at']),
        asks=_load_levels(list(payload['asks'])),
        bids=_load_levels(list(payload['bids'])),
        connector_healthy=bool(payload.get('connector_healthy', True)),
    )


def _load_balance_snapshot(payload: dict[str, object]) -> BalanceSnapshot:
    return BalanceSnapshot(
        exchange_name=str(payload['exchange_name']),
        base_asset=str(payload['base_asset']),
        quote_asset=str(payload['quote_asset']),
        available_base=_parse_decimal(payload['available_base']),
        available_quote=_parse_decimal(payload['available_quote']),
        observed_at=_parse_datetime(payload['observed_at']),
        is_fresh=bool(payload.get('is_fresh', True)),
    )


def _load_risk_config(payload: dict[str, object]) -> RiskConfig:
    return RiskConfig(
        min_profit_quote=_parse_decimal(payload['min_profit_quote']),
        min_profit_bps=_parse_decimal(payload['min_profit_bps']),
        max_clock_skew_ms=int(payload['max_clock_skew_ms']),
        max_orderbook_age_ms=int(payload['max_orderbook_age_ms']),
        max_balance_age_ms=int(payload['max_balance_age_ms']),
        max_notional_per_order=_parse_decimal(payload['max_notional_per_order']),
        max_total_notional_per_bot=_parse_decimal(payload['max_total_notional_per_bot']),
        max_spread_bps=_parse_decimal(payload['max_spread_bps']),
        min_orderbook_depth_levels=int(payload.get('min_orderbook_depth_levels', 1)),
        min_available_depth_quote=_parse_decimal(
            payload.get('min_available_depth_quote', '0')
        ),
        slippage_buffer_bps=_parse_decimal(payload.get('slippage_buffer_bps', '0')),
        unwind_buffer_quote=_parse_decimal(payload.get('unwind_buffer_quote', '0')),
        rebalance_buffer_quote=_parse_decimal(payload.get('rebalance_buffer_quote', '0')),
        taker_fee_bps_buy=_parse_decimal(payload.get('taker_fee_bps_buy', '0')),
        taker_fee_bps_sell=_parse_decimal(payload.get('taker_fee_bps_sell', '0')),
        reentry_cooldown_seconds=int(payload.get('reentry_cooldown_seconds', 0)),
    )


def _load_runtime_state(
    payload: dict[str, object],
    *,
    bot_id: str,
    strategy_run_id: str,
) -> RuntimeState:
    return RuntimeState(
        now=_parse_datetime(payload['now']),
        open_order_count=int(payload.get('open_order_count', 0)),
        open_order_cap=int(payload.get('open_order_cap', 0)),
        unwind_in_progress=bool(payload.get('unwind_in_progress', False)),
        connector_private_healthy=bool(payload.get('connector_private_healthy', True)),
        duplicate_intent_active=bool(payload.get('duplicate_intent_active', False)),
        recent_unwind_at=(
            _parse_datetime(payload['recent_unwind_at'])
            if payload.get('recent_unwind_at') is not None
            else None
        ),
        remaining_bot_notional=(
            _parse_decimal(payload['remaining_bot_notional'])
            if payload.get('remaining_bot_notional') is not None
            else None
        ),
        bot_id=str(payload.get('bot_id', bot_id)),
        strategy_run_id=str(payload.get('strategy_run_id', strategy_run_id)),
    )


def load_strategy_inputs(payload: dict[str, object]) -> ArbitrageInputs:
    base_orderbook_payload = dict(payload['base_orderbook'])
    hedge_orderbook_payload = dict(payload['hedge_orderbook'])
    base_balance_payload = dict(payload['base_balance'])
    hedge_balance_payload = dict(payload['hedge_balance'])
    risk_payload = dict(payload['risk_config'])
    runtime_payload = dict(payload['runtime_state'])
    bot_id = str(payload['bot_id'])
    strategy_run_id = str(payload['strategy_run_id'])

    return ArbitrageInputs(
        bot_id=bot_id,
        strategy_run_id=strategy_run_id,
        canonical_symbol=str(payload['canonical_symbol']),
        market=str(payload['market']),
        base_exchange=str(payload['base_exchange']),
        hedge_exchange=str(payload['hedge_exchange']),
        base_orderbook=_load_orderbook_snapshot(base_orderbook_payload),
        hedge_orderbook=_load_orderbook_snapshot(hedge_orderbook_payload),
        base_balance=_load_balance_snapshot(base_balance_payload),
        hedge_balance=_load_balance_snapshot(hedge_balance_payload),
        risk_config=_load_risk_config(risk_payload),
        runtime_state=_load_runtime_state(
            runtime_payload,
            bot_id=bot_id,
            strategy_run_id=strategy_run_id,
        ),
    )


def load_candidate_strategy_inputs(payload: dict[str, object]) -> ArbitrageCandidateInputs:
    candidate_exchanges = payload.get('candidate_exchanges')
    orderbooks_payload = payload.get('orderbooks_by_exchange')
    balances_payload = payload.get('balances_by_exchange')
    bot_id = str(payload['bot_id'])
    strategy_run_id = str(payload['strategy_run_id'])
    risk_payload = dict(payload['risk_config'])
    runtime_payload = dict(payload['runtime_state'])

    if not isinstance(candidate_exchanges, list):
        pair_inputs = load_strategy_inputs(payload)
        return ArbitrageCandidateInputs(
            bot_id=pair_inputs.bot_id,
            strategy_run_id=pair_inputs.strategy_run_id,
            canonical_symbol=pair_inputs.canonical_symbol,
            market=pair_inputs.market,
            candidate_exchanges=(pair_inputs.base_exchange, pair_inputs.hedge_exchange),
            orderbooks_by_exchange={
                pair_inputs.base_exchange: pair_inputs.base_orderbook,
                pair_inputs.hedge_exchange: pair_inputs.hedge_orderbook,
            },
            balances_by_exchange={
                pair_inputs.base_exchange: pair_inputs.base_balance,
                pair_inputs.hedge_exchange: pair_inputs.hedge_balance,
            },
            risk_config=pair_inputs.risk_config,
            runtime_state=pair_inputs.runtime_state,
        )

    if not isinstance(orderbooks_payload, dict) or not isinstance(balances_payload, dict):
        raise TypeError('orderbooks_by_exchange and balances_by_exchange must be objects')

    normalized_orderbooks = {
        str(exchange).strip().lower(): payload
        for exchange, payload in orderbooks_payload.items()
    }
    normalized_balances = {
        str(exchange).strip().lower(): payload
        for exchange, payload in balances_payload.items()
    }

    normalized_exchanges: list[str] = []
    for raw_exchange in candidate_exchanges:
        exchange = str(raw_exchange).strip().lower()
        if not exchange or exchange in normalized_exchanges:
            continue
        normalized_exchanges.append(exchange)
    if len(normalized_exchanges) < 2:
        raise ValueError('candidate_exchanges must include at least two exchanges')

    orderbooks_by_exchange: dict[str, OrderbookSnapshot] = {}
    balances_by_exchange: dict[str, BalanceSnapshot] = {}
    for exchange in normalized_exchanges:
        raw_orderbook = normalized_orderbooks.get(exchange)
        raw_balance = normalized_balances.get(exchange)
        if not isinstance(raw_orderbook, dict):
            raise KeyError(f'missing orderbook snapshot for {exchange}')
        if not isinstance(raw_balance, dict):
            raise KeyError(f'missing balance snapshot for {exchange}')
        orderbooks_by_exchange[exchange] = _load_orderbook_snapshot(dict(raw_orderbook))
        balances_by_exchange[exchange] = _load_balance_snapshot(dict(raw_balance))

    return ArbitrageCandidateInputs(
        bot_id=bot_id,
        strategy_run_id=strategy_run_id,
        canonical_symbol=str(payload['canonical_symbol']),
        market=str(payload['market']),
        candidate_exchanges=tuple(normalized_exchanges),
        orderbooks_by_exchange=orderbooks_by_exchange,
        balances_by_exchange=balances_by_exchange,
        risk_config=_load_risk_config(risk_payload),
        runtime_state=_load_runtime_state(
            runtime_payload,
            bot_id=bot_id,
            strategy_run_id=strategy_run_id,
        ),
    )
