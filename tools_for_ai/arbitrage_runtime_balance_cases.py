from __future__ import annotations

from datetime import UTC, datetime

from trading_platform.private_exchange_connector import PrivateExchangeResult
from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy.arbitrage_runtime_loader import load_arbitrage_runtime_payload


class DummyConnector:
    _PRICE_BY_EXCHANGE = {
        'sample': {'best_bid': '99980000', 'best_ask': '100000000'},
        'upbit': {'best_bid': '100450000', 'best_ask': '100550000'},
        'bithumb': {'best_bid': '100420000', 'best_ask': '100520000'},
        'coinone': {'best_bid': '100400000', 'best_ask': '100500000'},
    }

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        price = self._PRICE_BY_EXCHANGE.get(
            exchange,
            {'best_bid': '101000000', 'best_ask': '101100000'},
        )
        return {
            'exchange': exchange,
            'market': market,
            'best_bid': price['best_bid'],
            'best_ask': price['best_ask'],
            'bid_volume': '1.5',
            'ask_volume': '1.5',
            'bids': [{'price': price['best_bid'], 'quantity': '1.5'}],
            'asks': [{'price': price['best_ask'], 'quantity': '1.5'}],
            'exchange_timestamp': now,
            'received_at': now,
            'exchange_age_ms': 0,
            'stale': False,
            'source_type': 'dummy',
            'connector_healthy': True,
        }


class FakePrivateConnector:
    def __init__(self, exchange: str, result: PrivateExchangeResult) -> None:
        self.exchange = exchange
        self.name = f'{exchange}:fake_private'
        self._result = result

    def get_balances(self) -> PrivateExchangeResult:
        return self._result


class ErrorPrivateConnector(FakePrivateConnector):
    pass


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _running_run() -> tuple[object, dict[str, object], dict[str, object]]:
    store = sample_read_store()
    store.order_intents.clear()
    store.orders.clear()
    store.fills.clear()
    run = next(
        item
        for item in store.list_strategy_runs(status='running')
        if str(item.get('strategy_name') or '') == 'arbitrage'
    )
    bot_detail = store.get_bot_detail(str(run['bot_id']))
    _assert(bot_detail is not None, 'bot detail missing')
    assigned = bot_detail.get('assigned_config_version')
    _assert(isinstance(assigned, dict), 'assigned config missing')
    config_scope = str(assigned['config_scope'])
    version_no = int(assigned['version_no'])
    version = next(
        item
        for item in store.list_config_versions(config_scope)
        if int(item.get('version_no') or -1) == version_no
    )
    runtime_spec = dict(version['config_json']['arbitrage_runtime'])
    return store, run, runtime_spec


def _set_runtime_spec(store, run: dict[str, object], runtime_spec: dict[str, object]) -> None:
    bot_detail = store.get_bot_detail(str(run['bot_id']))
    _assert(bot_detail is not None, 'bot detail missing while setting runtime spec')
    assigned = bot_detail['assigned_config_version']
    config_scope = str(assigned['config_scope'])
    version_no = int(assigned['version_no'])
    for version in store.config_versions[config_scope]:
        if int(version.get('version_no') or -1) != version_no:
            continue
        version['config_json']['arbitrage_runtime'] = runtime_spec
        return
    raise AssertionError('runtime config version not found')


def _balance_result(*, base_asset: str, quote_asset: str, base_free: str, quote_free: str) -> PrivateExchangeResult:
    return PrivateExchangeResult(
        outcome='ok',
        data={
            'items': [
                {'currency': base_asset, 'available': base_free, 'locked': '0'},
                {'currency': quote_asset, 'available': quote_free, 'locked': '0'},
            ],
            'count': 2,
        },
    )


def _case_live_uses_private_balances() -> None:
    store, run, runtime_spec = _running_run()
    run['mode'] = 'live'
    runtime_spec.update(
        {
            'base_exchange': 'upbit',
            'hedge_exchange': 'bithumb',
            'candidate_exchanges': ['upbit', 'bithumb'],
            'base_balance': {'available_base': '999', 'available_quote': '999999999', 'is_fresh': True},
            'hedge_balance': {'available_base': '999', 'available_quote': '999999999', 'is_fresh': True},
        }
    )
    _set_runtime_spec(store, run, runtime_spec)
    connectors = {
        'upbit': FakePrivateConnector(
            'upbit',
            _balance_result(base_asset='BTC', quote_asset='KRW', base_free='1.25', quote_free='200000000'),
        ),
        'bithumb': FakePrivateConnector(
            'bithumb',
            _balance_result(base_asset='BTC', quote_asset='KRW', base_free='0.85', quote_free='170000000'),
        ),
    }
    result = load_arbitrage_runtime_payload(
        store=store,
        connector=DummyConnector(),
        run=run,
        redis_runtime=None,
        private_exchange_connectors=connectors,
    )
    _assert(result.payload is not None, 'live mode should load payload with private balances')
    base_balance = result.payload['base_balance']
    hedge_balance = result.payload['hedge_balance']
    _assert(base_balance['available_base'] == '1.25', 'live base balance should come from private connector')
    _assert(base_balance['available_quote'] == '200000000', 'live quote balance should come from private connector')
    _assert(hedge_balance['available_base'] == '0.85', 'live hedge balance should come from private connector')
    _assert(
        result.payload['balance_sources_by_exchange'] == {'upbit': 'private_exchange', 'bithumb': 'private_exchange'},
        'live balance source metadata mismatch',
    )


def _case_live_blocks_runtime_config_injection() -> None:
    store, run, runtime_spec = _running_run()
    run['mode'] = 'live'
    runtime_spec.update(
        {
            'base_exchange': 'upbit',
            'hedge_exchange': 'bithumb',
            'candidate_exchanges': ['upbit', 'bithumb'],
            'balance_source': 'runtime_config',
        }
    )
    _set_runtime_spec(store, run, runtime_spec)
    result = load_arbitrage_runtime_payload(
        store=store,
        connector=DummyConnector(),
        run=run,
        redis_runtime=None,
        private_exchange_connectors=None,
    )
    _assert(result.payload is None, 'live mode must reject runtime_config balance_source')
    _assert(result.skip_reason == 'RUNTIME_INPUTS_INVALID', 'live balance_source block skip_reason mismatch')
    _assert(
        result.detail == 'balance_source=runtime_config is not allowed for live mode',
        'live balance_source block detail mismatch',
    )


def _case_live_fails_closed_on_private_balance_error() -> None:
    store, run, runtime_spec = _running_run()
    run['mode'] = 'live'
    runtime_spec.update(
        {
            'base_exchange': 'upbit',
            'hedge_exchange': 'bithumb',
            'candidate_exchanges': ['upbit', 'bithumb'],
        }
    )
    _set_runtime_spec(store, run, runtime_spec)
    connectors = {
        'upbit': FakePrivateConnector(
            'upbit',
            _balance_result(base_asset='BTC', quote_asset='KRW', base_free='1.0', quote_free='150000000'),
        ),
        'bithumb': ErrorPrivateConnector(
            'bithumb',
            PrivateExchangeResult(
                outcome='error',
                error_code='NETWORK_ERROR',
                reason='timeout',
                retryable=True,
            ),
        ),
    }
    result = load_arbitrage_runtime_payload(
        store=store,
        connector=DummyConnector(),
        run=run,
        redis_runtime=None,
        private_exchange_connectors=connectors,
    )
    _assert(result.payload is None, 'live mode should fail closed on private balance error')
    _assert(result.skip_reason == 'BALANCE_SNAPSHOT_UNAVAILABLE', 'live private balance failure skip_reason mismatch')
    _assert(
        result.detail == 'bithumb get_balances failed: NETWORK_ERROR: timeout',
        'live private balance failure detail mismatch',
    )


def _case_shadow_keeps_runtime_config_fallback() -> None:
    store, run, runtime_spec = _running_run()
    run['mode'] = 'shadow'
    runtime_spec['base_balance'] = {
        'available_base': '7.7',
        'available_quote': '123456789',
        'is_fresh': True,
    }
    runtime_spec['hedge_balance'] = {
        'available_base': '6.6',
        'available_quote': '987654321',
        'is_fresh': True,
    }
    _set_runtime_spec(store, run, runtime_spec)
    result = load_arbitrage_runtime_payload(
        store=store,
        connector=DummyConnector(),
        run=run,
        redis_runtime=None,
        private_exchange_connectors=None,
    )
    _assert(result.payload is not None, 'shadow mode should keep runtime_config balance fallback')
    _assert(result.payload['base_balance']['available_base'] == '7.7', 'shadow base balance fallback mismatch')
    _assert(result.payload['hedge_balance']['available_quote'] == '987654321', 'shadow hedge balance fallback mismatch')
    _assert(
        result.payload['balance_sources_by_exchange'] == {'sample': 'runtime_config', 'upbit': 'runtime_config'},
        'shadow balance source metadata mismatch',
    )


def main() -> None:
    _case_live_uses_private_balances()
    _case_live_blocks_runtime_config_injection()
    _case_live_fails_closed_on_private_balance_error()
    _case_shadow_keeps_runtime_config_fallback()
    print('PASS live runtime loader uses private exchange balances for strategy inputs')
    print('PASS live runtime loader rejects runtime_config balance injection')
    print('PASS live runtime loader fails closed when private balance refresh fails')
    print('PASS shadow runtime loader keeps runtime_config balance fallback')


if __name__ == '__main__':
    main()
