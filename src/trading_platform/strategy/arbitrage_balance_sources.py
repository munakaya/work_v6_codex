from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..private_exchange_connector import PrivateExchangeConnectorProtocol


@dataclass(frozen=True)
class BalanceSnapshotLoadResult:
    snapshots_by_exchange: dict[str, dict[str, object]] | None
    source_by_exchange: dict[str, str] | None = None
    skip_reason: str | None = None
    detail: str | None = None


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')


def _normalized_exchange(value: object) -> str:
    return str(value or '').strip().lower()


def _runtime_mode(
    *,
    run: dict[str, object],
    bot_detail: dict[str, object],
) -> str:
    run_mode = str(run.get('mode') or '').strip().lower()
    if run_mode:
        return run_mode
    return str(bot_detail.get('mode') or '').strip().lower() or 'dry_run'


def _configured_balance_source(
    runtime_spec: dict[str, object],
    *,
    runtime_mode: str,
) -> str:
    configured = str(runtime_spec.get('balance_source') or '').strip().lower()
    if configured:
        return configured
    if runtime_mode == 'live':
        return 'private_exchange'
    return 'runtime_config'


def _balance_payload(
    *,
    exchange_name: str,
    base_asset: str,
    quote_asset: str,
    available_base: object,
    available_quote: object,
    observed_at: str | None = None,
    is_fresh: bool = True,
    source_type: str,
) -> dict[str, object]:
    return {
        'exchange_name': exchange_name,
        'base_asset': base_asset,
        'quote_asset': quote_asset,
        'available_base': str(available_base),
        'available_quote': str(available_quote),
        'observed_at': str(observed_at or _iso_now()),
        'is_fresh': bool(is_fresh),
        'source_type': source_type,
    }


def _config_balance_specs(
    runtime_spec: dict[str, object],
    *,
    candidate_exchanges: list[str],
) -> tuple[dict[str, dict[str, object]] | None, str | None]:
    raw_exchange_balances = runtime_spec.get('exchange_balances')
    if isinstance(raw_exchange_balances, dict):
        normalized_input = {
            _normalized_exchange(exchange): payload
            for exchange, payload in raw_exchange_balances.items()
        }
        normalized: dict[str, dict[str, object]] = {}
        missing = [
            exchange
            for exchange in candidate_exchanges
            if not isinstance(normalized_input.get(exchange), dict)
        ]
        if missing:
            return None, 'missing exchange_balances for: ' + ', '.join(missing)
        for exchange in candidate_exchanges:
            normalized[exchange] = dict(normalized_input[exchange])
        return normalized, None

    base_exchange = _normalized_exchange(runtime_spec.get('base_exchange'))
    hedge_exchange = _normalized_exchange(runtime_spec.get('hedge_exchange'))
    base_balance_spec = runtime_spec.get('base_balance')
    hedge_balance_spec = runtime_spec.get('hedge_balance')
    if not base_exchange or not hedge_exchange:
        return None, 'base_exchange and hedge_exchange are required when exchange_balances is absent'
    if not isinstance(base_balance_spec, dict) or not isinstance(hedge_balance_spec, dict):
        return None, 'base_balance and hedge_balance must be objects'
    normalized = {
        base_exchange: dict(base_balance_spec),
        hedge_exchange: dict(hedge_balance_spec),
    }
    missing = [exchange for exchange in candidate_exchanges if exchange not in normalized]
    if missing:
        return None, 'missing exchange-specific balances for: ' + ', '.join(missing)
    return normalized, None


def _load_runtime_config_balance_snapshots(
    *,
    runtime_spec: dict[str, object],
    candidate_exchanges: list[str],
    base_asset: str,
    quote_asset: str,
) -> BalanceSnapshotLoadResult:
    balance_specs, balance_error = _config_balance_specs(
        runtime_spec,
        candidate_exchanges=candidate_exchanges,
    )
    if balance_specs is None:
        return BalanceSnapshotLoadResult(
            snapshots_by_exchange=None,
            skip_reason='RUNTIME_INPUTS_INVALID',
            detail=balance_error,
        )
    snapshots_by_exchange: dict[str, dict[str, object]] = {}
    source_by_exchange: dict[str, str] = {}
    for exchange, payload in balance_specs.items():
        available_base = payload.get('available_base')
        available_quote = payload.get('available_quote')
        if available_base is None or available_quote is None:
            return BalanceSnapshotLoadResult(
                snapshots_by_exchange=None,
                skip_reason='RUNTIME_INPUTS_INVALID',
                detail=f'balance payload must include available_base and available_quote: {exchange}',
            )
        snapshots_by_exchange[exchange] = _balance_payload(
            exchange_name=exchange,
            base_asset=base_asset,
            quote_asset=quote_asset,
            available_base=available_base,
            available_quote=available_quote,
            observed_at=str(payload.get('observed_at') or _iso_now()),
            is_fresh=bool(payload.get('is_fresh', True)),
            source_type='runtime_config',
        )
        source_by_exchange[exchange] = 'runtime_config'
    return BalanceSnapshotLoadResult(
        snapshots_by_exchange=snapshots_by_exchange,
        source_by_exchange=source_by_exchange,
    )


def _index_balance_items(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for item in items:
        currency = str(item.get('currency') or '').strip().upper()
        if not currency or currency in indexed:
            continue
        indexed[currency] = item
    return indexed


def _load_private_exchange_balance_snapshots(
    *,
    private_exchange_connectors: dict[str, PrivateExchangeConnectorProtocol] | None,
    candidate_exchanges: list[str],
    base_asset: str,
    quote_asset: str,
) -> BalanceSnapshotLoadResult:
    if private_exchange_connectors is None:
        return BalanceSnapshotLoadResult(
            snapshots_by_exchange=None,
            skip_reason='BALANCE_SNAPSHOT_UNAVAILABLE',
            detail='private_exchange_connectors are required for private_exchange balance source',
        )
    snapshots_by_exchange: dict[str, dict[str, object]] = {}
    source_by_exchange: dict[str, str] = {}
    normalized_base_asset = base_asset.strip().upper()
    normalized_quote_asset = quote_asset.strip().upper()
    for exchange in candidate_exchanges:
        connector = private_exchange_connectors.get(exchange)
        if connector is None:
            return BalanceSnapshotLoadResult(
                snapshots_by_exchange=None,
                skip_reason='BALANCE_SNAPSHOT_UNAVAILABLE',
                detail=f'private balance connector not configured for: {exchange}',
            )
        result = connector.get_balances()
        if result.outcome != 'ok':
            error_code = str(result.error_code or result.outcome or 'unknown')
            reason = str(result.reason or 'private balance fetch failed')
            return BalanceSnapshotLoadResult(
                snapshots_by_exchange=None,
                skip_reason='BALANCE_SNAPSHOT_UNAVAILABLE',
                detail=f'{exchange} get_balances failed: {error_code}: {reason}',
            )
        data = result.data if isinstance(result.data, dict) else {}
        items = data.get('items') if isinstance(data.get('items'), list) else None
        if items is None:
            return BalanceSnapshotLoadResult(
                snapshots_by_exchange=None,
                skip_reason='BALANCE_SNAPSHOT_UNAVAILABLE',
                detail=f'{exchange} get_balances returned invalid payload',
            )
        indexed = _index_balance_items([item for item in items if isinstance(item, dict)])
        base_item = indexed.get(normalized_base_asset, {})
        quote_item = indexed.get(normalized_quote_asset, {})
        snapshots_by_exchange[exchange] = _balance_payload(
            exchange_name=exchange,
            base_asset=base_asset,
            quote_asset=quote_asset,
            available_base=base_item.get('available', '0'),
            available_quote=quote_item.get('available', '0'),
            observed_at=_iso_now(),
            is_fresh=True,
            source_type='private_exchange',
        )
        source_by_exchange[exchange] = 'private_exchange'
    return BalanceSnapshotLoadResult(
        snapshots_by_exchange=snapshots_by_exchange,
        source_by_exchange=source_by_exchange,
    )


def load_balance_snapshots(
    *,
    runtime_spec: dict[str, object],
    candidate_exchanges: list[str],
    base_asset: str,
    quote_asset: str,
    run: dict[str, object],
    bot_detail: dict[str, object],
    private_exchange_connectors: dict[str, PrivateExchangeConnectorProtocol] | None = None,
) -> BalanceSnapshotLoadResult:
    runtime_mode = _runtime_mode(run=run, bot_detail=bot_detail)
    balance_source = _configured_balance_source(runtime_spec, runtime_mode=runtime_mode)
    if runtime_mode == 'live' and balance_source == 'runtime_config':
        return BalanceSnapshotLoadResult(
            snapshots_by_exchange=None,
            skip_reason='RUNTIME_INPUTS_INVALID',
            detail='balance_source=runtime_config is not allowed for live mode',
        )
    if balance_source == 'private_exchange':
        return _load_private_exchange_balance_snapshots(
            private_exchange_connectors=private_exchange_connectors,
            candidate_exchanges=candidate_exchanges,
            base_asset=base_asset,
            quote_asset=quote_asset,
        )
    if balance_source == 'runtime_config':
        return _load_runtime_config_balance_snapshots(
            runtime_spec=runtime_spec,
            candidate_exchanges=candidate_exchanges,
            base_asset=base_asset,
            quote_asset=quote_asset,
        )
    return BalanceSnapshotLoadResult(
        snapshots_by_exchange=None,
        skip_reason='RUNTIME_INPUTS_INVALID',
        detail=f'unsupported balance_source: {balance_source}',
    )
