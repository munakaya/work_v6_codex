from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..market_data_connector import PublicMarketDataConnector
from ..market_data_freshness import choose_freshness_observed_at, snapshot_sort_datetime
from ..redis_runtime import RedisRuntime
from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_balance_sources import load_balance_snapshots

if TYPE_CHECKING:
    from ..private_exchange_connector import PrivateExchangeConnectorProtocol


ACTIVE_INTENT_STATUSES = {'created', 'submitted'}
ACTIVE_ORDER_STATUSES = {'created', 'submitted', 'new', 'open', 'partially_filled'}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')


def _snapshot_sort_timestamp(snapshot: dict[str, object] | None) -> datetime | None:
    return snapshot_sort_datetime(snapshot)


def _newer_snapshot(
    left: dict[str, object] | None,
    right: dict[str, object] | None,
) -> dict[str, object] | None:
    left_time = _snapshot_sort_timestamp(left)
    right_time = _snapshot_sort_timestamp(right)
    if left is None:
        return right
    if right is None:
        return left
    if left_time is None:
        return right
    if right_time is None:
        return left
    return left if left_time >= right_time else right


@dataclass(frozen=True)
class ArbitrageRuntimeLoadResult:
    payload: dict[str, object] | None
    skip_reason: str | None = None
    detail: str | None = None


def _cached_orderbook_snapshot(
    *,
    connector: PublicMarketDataConnector,
    redis_runtime: RedisRuntime | None,
    exchange: str,
    market: str,
) -> dict[str, object] | None:
    cached_reader = getattr(connector, 'get_cached_orderbook_top', None)
    if callable(cached_reader):
        connector_snapshot = cached_reader(exchange=exchange, market=market)
        redis_snapshot = None
        if redis_runtime is not None and redis_runtime.info.enabled:
            redis_snapshot = redis_runtime.get_market_orderbook_top(
                exchange=exchange,
                market=market,
            )
        return _newer_snapshot(
            connector_snapshot if isinstance(connector_snapshot, dict) else None,
            redis_snapshot if isinstance(redis_snapshot, dict) else None,
        )
    return connector.get_orderbook_top(exchange=exchange, market=market)


def _assigned_config_version(
    store: ControlPlaneStoreProtocol,
    bot_detail: dict[str, object],
) -> dict[str, object] | None:
    assigned = bot_detail.get('assigned_config_version')
    if not isinstance(assigned, dict):
        return None
    config_scope = str(assigned.get('config_scope') or '').strip()
    version_no = assigned.get('version_no')
    if not config_scope or not isinstance(version_no, int):
        return None
    for version in store.list_config_versions(config_scope):
        if int(version.get('version_no') or -1) == version_no:
            return version
    return None


def _snapshot_levels(
    snapshot: dict[str, object],
    *,
    side: str,
    fallback_price_key: str,
    fallback_quantity_key: str,
) -> list[dict[str, str]]:
    raw_levels = snapshot.get(side)
    if isinstance(raw_levels, list):
        normalized: list[dict[str, str]] = []
        for raw_level in raw_levels:
            if not isinstance(raw_level, dict):
                continue
            price = raw_level.get('price')
            quantity = raw_level.get('quantity')
            if price is None or quantity is None:
                continue
            normalized.append({'price': str(price), 'quantity': str(quantity)})
        if normalized:
            return normalized
    return [
        {
            'price': str(snapshot[fallback_price_key]),
            'quantity': str(snapshot[fallback_quantity_key]),
        }
    ]


def _snapshot_orderbook(snapshot: dict[str, object]) -> dict[str, object]:
    observed_at, observed_at_source = choose_freshness_observed_at(
        snapshot,
        fallback_now=_iso_now(),
    )
    return {
        'exchange_name': str(snapshot['exchange']),
        'market': str(snapshot['market']),
        'observed_at': observed_at,
        'observed_at_source': observed_at_source,
        'exchange_timestamp': snapshot.get('exchange_timestamp'),
        'received_at': snapshot.get('received_at'),
        'exchange_age_ms': snapshot.get('exchange_age_ms'),
        'source_type': snapshot.get('source_type'),
        'stale': snapshot.get('stale'),
        'freshness_observed_at': observed_at,
        'freshness_observed_at_source': observed_at_source,
        'asks': _snapshot_levels(
            snapshot,
            side='asks',
            fallback_price_key='best_ask',
            fallback_quantity_key='ask_volume',
        ),
        'bids': _snapshot_levels(
            snapshot,
            side='bids',
            fallback_price_key='best_bid',
            fallback_quantity_key='bid_volume',
        ),
        'connector_healthy': bool(snapshot.get('connector_healthy', True)),
    }


def _runtime_defaults(
    *,
    store: ControlPlaneStoreProtocol,
    bot_detail: dict[str, object],
    run: dict[str, object],
    runtime_payload: dict[str, object],
) -> dict[str, object]:
    run_id = str(run['run_id'])
    bot_id = str(run['bot_id'])
    intents = store.list_order_intents(strategy_run_id=run_id)
    duplicate_intent_active = any(
        str(item.get('status') or '') in ACTIVE_INTENT_STATUSES for item in intents
    )
    orders = store.list_orders(strategy_run_id=run_id)
    open_order_count = sum(
        1
        for item in orders
        if str(item.get('status') or '') in ACTIVE_ORDER_STATUSES
    )
    latest_heartbeat = bot_detail.get('latest_heartbeat')
    heartbeat_ordering_alive = True
    if isinstance(latest_heartbeat, dict):
        heartbeat_ordering_alive = bool(latest_heartbeat.get('is_ordering_alive', True))
    return {
        'now': _iso_now(),
        'open_order_count': open_order_count,
        'open_order_cap': int(runtime_payload.get('open_order_cap', 0) or 0),
        'unwind_in_progress': bool(runtime_payload.get('unwind_in_progress', False)),
        'connector_private_healthy': bool(
            runtime_payload.get('connector_private_healthy', heartbeat_ordering_alive)
        ),
        'duplicate_intent_active': duplicate_intent_active,
        'recent_unwind_at': runtime_payload.get('recent_unwind_at'),
        'remaining_bot_notional': runtime_payload.get('remaining_bot_notional'),
        'bot_id': bot_id,
        'strategy_run_id': run_id,
    }


def _normalized_exchange(value: object) -> str:
    return str(value or '').strip().lower()


def _candidate_exchanges(runtime_spec: dict[str, object]) -> list[str]:
    exchanges: list[str] = []
    raw_candidate_exchanges = runtime_spec.get('candidate_exchanges')
    if isinstance(raw_candidate_exchanges, list):
        for raw_exchange in raw_candidate_exchanges:
            exchange = _normalized_exchange(raw_exchange)
            if exchange and exchange not in exchanges:
                exchanges.append(exchange)
    for key in ('base_exchange', 'hedge_exchange'):
        exchange = _normalized_exchange(runtime_spec.get(key))
        if exchange and exchange not in exchanges:
            exchanges.append(exchange)
    return exchanges


def load_arbitrage_runtime_payload(
    *,
    store: ControlPlaneStoreProtocol,
    connector: PublicMarketDataConnector,
    run: dict[str, object],
    redis_runtime: RedisRuntime | None = None,
    private_exchange_connectors: dict[str, PrivateExchangeConnectorProtocol] | None = None,
) -> ArbitrageRuntimeLoadResult:
    bot_id = str(run.get('bot_id') or '').strip()
    if not bot_id:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='BOT_NOT_FOUND',
            detail='strategy run is missing bot_id',
        )
    bot_detail = store.get_bot_detail(bot_id)
    if bot_detail is None:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='BOT_NOT_FOUND',
            detail='bot detail not found',
        )
    version = _assigned_config_version(store, bot_detail)
    if version is None:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='CONFIG_NOT_FOUND',
            detail='assigned config version not found',
        )
    config_json = version.get('config_json')
    if not isinstance(config_json, dict):
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='CONFIG_INVALID',
            detail='config_json must be an object',
        )
    runtime_spec = config_json.get('arbitrage_runtime')
    if not isinstance(runtime_spec, dict):
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='RUNTIME_INPUTS_MISSING',
            detail='config_json.arbitrage_runtime is required',
        )
    if runtime_spec.get('enabled') is False:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='RUNTIME_DISABLED',
            detail='arbitrage runtime is disabled by config',
        )

    candidate_exchanges = _candidate_exchanges(runtime_spec)
    required = {
        'canonical_symbol': str(runtime_spec.get('canonical_symbol') or '').strip(),
        'market': str(runtime_spec.get('market') or '').strip(),
        'base_asset': str(runtime_spec.get('base_asset') or '').strip(),
        'quote_asset': str(runtime_spec.get('quote_asset') or '').strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if len(candidate_exchanges) < 2:
        missing.append('candidate_exchanges')
    if missing:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='RUNTIME_INPUTS_INVALID',
            detail='missing required fields: ' + ', '.join(missing),
        )

    risk_config = runtime_spec.get('risk_config')
    runtime_state_spec = runtime_spec.get('runtime_state') or {}
    if not isinstance(risk_config, dict):
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='RUNTIME_INPUTS_INVALID',
            detail='risk_config must be an object',
        )
    if not isinstance(runtime_state_spec, dict):
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='RUNTIME_INPUTS_INVALID',
            detail='runtime_state must be an object',
        )

    snapshots_by_exchange: dict[str, dict[str, object]] = {}
    missing_exchanges: list[str] = []
    for exchange in candidate_exchanges:
        snapshot = _cached_orderbook_snapshot(
            connector=connector,
            redis_runtime=redis_runtime,
            exchange=exchange,
            market=required['market'],
        )
        if snapshot is None:
            missing_exchanges.append(exchange)
            continue
        snapshots_by_exchange[exchange] = snapshot
    if missing_exchanges:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason='MARKET_SNAPSHOT_NOT_FOUND',
            detail='cached orderbook snapshot not found for: ' + ', '.join(missing_exchanges),
        )

    orderbooks_by_exchange = {
        exchange: _snapshot_orderbook(snapshot)
        for exchange, snapshot in snapshots_by_exchange.items()
    }
    balance_result = load_balance_snapshots(
        runtime_spec=runtime_spec,
        candidate_exchanges=candidate_exchanges,
        base_asset=required['base_asset'],
        quote_asset=required['quote_asset'],
        run=run,
        bot_detail=bot_detail,
        private_exchange_connectors=private_exchange_connectors,
    )
    if balance_result.snapshots_by_exchange is None:
        return ArbitrageRuntimeLoadResult(
            payload=None,
            skip_reason=balance_result.skip_reason,
            detail=balance_result.detail,
        )
    balances_by_exchange = balance_result.snapshots_by_exchange

    primary_base_exchange = _normalized_exchange(runtime_spec.get('base_exchange')) or candidate_exchanges[0]
    primary_hedge_exchange = _normalized_exchange(runtime_spec.get('hedge_exchange')) or candidate_exchanges[1]

    return ArbitrageRuntimeLoadResult(
        payload={
            'bot_id': bot_id,
            'strategy_run_id': str(run['run_id']),
            'canonical_symbol': required['canonical_symbol'],
            'market': required['market'],
            'candidate_exchanges': list(candidate_exchanges),
            'orderbooks_by_exchange': orderbooks_by_exchange,
            'balances_by_exchange': balances_by_exchange,
            'base_exchange': primary_base_exchange,
            'hedge_exchange': primary_hedge_exchange,
            'base_orderbook': orderbooks_by_exchange[primary_base_exchange],
            'hedge_orderbook': orderbooks_by_exchange[primary_hedge_exchange],
            'base_balance': balances_by_exchange[primary_base_exchange],
            'hedge_balance': balances_by_exchange[primary_hedge_exchange],
            'risk_config': dict(risk_config),
            'runtime_state': _runtime_defaults(
                store=store,
                bot_detail=bot_detail,
                run=run,
                runtime_payload=runtime_state_spec,
            ),
            'balance_sources_by_exchange': (
                balance_result.source_by_exchange
                if balance_result.source_by_exchange is not None
                else {}
            ),
        }
    )
