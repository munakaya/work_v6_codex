from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from .arbitrage_models import (
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
        raise TypeError("datetime must be str or datetime")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_levels(levels: list[dict[str, object]]) -> tuple[OrderbookLevel, ...]:
    return tuple(
        OrderbookLevel(
            price=_parse_decimal(item["price"]),
            quantity=_parse_decimal(item["quantity"]),
        )
        for item in levels
    )


def load_strategy_inputs(payload: dict[str, object]) -> ArbitrageInputs:
    base_orderbook_payload = dict(payload["base_orderbook"])
    hedge_orderbook_payload = dict(payload["hedge_orderbook"])
    base_balance_payload = dict(payload["base_balance"])
    hedge_balance_payload = dict(payload["hedge_balance"])
    risk_payload = dict(payload["risk_config"])
    runtime_payload = dict(payload["runtime_state"])

    return ArbitrageInputs(
        bot_id=str(payload["bot_id"]),
        strategy_run_id=str(payload["strategy_run_id"]),
        canonical_symbol=str(payload["canonical_symbol"]),
        market=str(payload["market"]),
        base_exchange=str(payload["base_exchange"]),
        hedge_exchange=str(payload["hedge_exchange"]),
        base_orderbook=OrderbookSnapshot(
            exchange_name=str(base_orderbook_payload["exchange_name"]),
            market=str(base_orderbook_payload["market"]),
            observed_at=_parse_datetime(base_orderbook_payload["observed_at"]),
            asks=_load_levels(list(base_orderbook_payload["asks"])),
            bids=_load_levels(list(base_orderbook_payload["bids"])),
            connector_healthy=bool(base_orderbook_payload.get("connector_healthy", True)),
        ),
        hedge_orderbook=OrderbookSnapshot(
            exchange_name=str(hedge_orderbook_payload["exchange_name"]),
            market=str(hedge_orderbook_payload["market"]),
            observed_at=_parse_datetime(hedge_orderbook_payload["observed_at"]),
            asks=_load_levels(list(hedge_orderbook_payload["asks"])),
            bids=_load_levels(list(hedge_orderbook_payload["bids"])),
            connector_healthy=bool(hedge_orderbook_payload.get("connector_healthy", True)),
        ),
        base_balance=BalanceSnapshot(
            exchange_name=str(base_balance_payload["exchange_name"]),
            base_asset=str(base_balance_payload["base_asset"]),
            quote_asset=str(base_balance_payload["quote_asset"]),
            available_base=_parse_decimal(base_balance_payload["available_base"]),
            available_quote=_parse_decimal(base_balance_payload["available_quote"]),
            observed_at=_parse_datetime(base_balance_payload["observed_at"]),
            is_fresh=bool(base_balance_payload.get("is_fresh", True)),
        ),
        hedge_balance=BalanceSnapshot(
            exchange_name=str(hedge_balance_payload["exchange_name"]),
            base_asset=str(hedge_balance_payload["base_asset"]),
            quote_asset=str(hedge_balance_payload["quote_asset"]),
            available_base=_parse_decimal(hedge_balance_payload["available_base"]),
            available_quote=_parse_decimal(hedge_balance_payload["available_quote"]),
            observed_at=_parse_datetime(hedge_balance_payload["observed_at"]),
            is_fresh=bool(hedge_balance_payload.get("is_fresh", True)),
        ),
        risk_config=RiskConfig(
            min_profit_quote=_parse_decimal(risk_payload["min_profit_quote"]),
            min_profit_bps=_parse_decimal(risk_payload["min_profit_bps"]),
            max_clock_skew_ms=int(risk_payload["max_clock_skew_ms"]),
            max_orderbook_age_ms=int(risk_payload["max_orderbook_age_ms"]),
            max_balance_age_ms=int(risk_payload["max_balance_age_ms"]),
            max_notional_per_order=_parse_decimal(risk_payload["max_notional_per_order"]),
            max_total_notional_per_bot=_parse_decimal(
                risk_payload["max_total_notional_per_bot"]
            ),
            max_spread_bps=_parse_decimal(risk_payload["max_spread_bps"]),
            min_orderbook_depth_levels=int(
                risk_payload.get("min_orderbook_depth_levels", 1)
            ),
            min_available_depth_quote=_parse_decimal(
                risk_payload.get("min_available_depth_quote", "0")
            ),
            slippage_buffer_bps=_parse_decimal(risk_payload.get("slippage_buffer_bps", "0")),
            unwind_buffer_quote=_parse_decimal(risk_payload.get("unwind_buffer_quote", "0")),
            rebalance_buffer_quote=_parse_decimal(
                risk_payload.get("rebalance_buffer_quote", "0")
            ),
            taker_fee_bps_buy=_parse_decimal(risk_payload.get("taker_fee_bps_buy", "0")),
            taker_fee_bps_sell=_parse_decimal(risk_payload.get("taker_fee_bps_sell", "0")),
            reentry_cooldown_seconds=int(risk_payload.get("reentry_cooldown_seconds", 0)),
        ),
        runtime_state=RuntimeState(
            now=_parse_datetime(runtime_payload["now"]),
            open_order_count=int(runtime_payload.get("open_order_count", 0)),
            open_order_cap=int(runtime_payload.get("open_order_cap", 0)),
            unwind_in_progress=bool(runtime_payload.get("unwind_in_progress", False)),
            connector_private_healthy=bool(
                runtime_payload.get("connector_private_healthy", True)
            ),
            duplicate_intent_active=bool(
                runtime_payload.get("duplicate_intent_active", False)
            ),
            recent_unwind_at=(
                _parse_datetime(runtime_payload["recent_unwind_at"])
                if runtime_payload.get("recent_unwind_at") is not None
                else None
            ),
            remaining_bot_notional=(
                _parse_decimal(runtime_payload["remaining_bot_notional"])
                if runtime_payload.get("remaining_bot_notional") is not None
                else None
            ),
            bot_id=str(runtime_payload.get("bot_id", payload["bot_id"])),
            strategy_run_id=str(
                runtime_payload.get("strategy_run_id", payload["strategy_run_id"])
            ),
        ),
    )
