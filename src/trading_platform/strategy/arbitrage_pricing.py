from __future__ import annotations

from decimal import Decimal

from .arbitrage_models import ArbitrageInputs, CandidateSizeResult, ExecutableEdgeResult


def _sum_depth_qty(levels: tuple[object, ...]) -> Decimal:
    total = Decimal("0")
    for level in levels:
        total += level.quantity
    return total


def _vwap(levels: tuple[object, ...], target_qty: Decimal) -> Decimal | None:
    remaining = target_qty
    total_notional = Decimal("0")
    for level in levels:
        take_qty = min(level.quantity, remaining)
        total_notional += take_qty * level.price
        remaining -= take_qty
        if remaining <= 0:
            break
    if remaining > 0:
        return None
    return total_notional / target_qty


def compute_candidate_size(inputs: ArbitrageInputs) -> CandidateSizeResult:
    config = inputs.risk_config
    if not inputs.base_orderbook.asks or not inputs.hedge_orderbook.bids:
        return CandidateSizeResult(
            target_qty=Decimal("0"),
            components={"error": "missing_orderbook_depth"},
        )
    best_buy_ask = inputs.base_orderbook.asks[0].price
    if best_buy_ask <= 0:
        return CandidateSizeResult(
            target_qty=Decimal("0"),
            components={"error": "non_positive_best_ask"},
        )
    buy_quote_limit_qty = inputs.base_balance.available_quote / best_buy_ask
    sell_base_limit_qty = inputs.hedge_balance.available_base
    buy_depth_qty = _sum_depth_qty(inputs.base_orderbook.asks)
    sell_depth_qty = _sum_depth_qty(inputs.hedge_orderbook.bids)
    order_notional_qty = config.max_notional_per_order / best_buy_ask

    components = {
        "buy_quote_limit_qty": str(buy_quote_limit_qty),
        "sell_base_limit_qty": str(sell_base_limit_qty),
        "buy_depth_qty": str(buy_depth_qty),
        "sell_depth_qty": str(sell_depth_qty),
        "max_notional_qty": str(order_notional_qty),
    }
    qty_candidates = [
        buy_quote_limit_qty,
        sell_base_limit_qty,
        buy_depth_qty,
        sell_depth_qty,
        order_notional_qty,
    ]
    if inputs.runtime_state.remaining_bot_notional is not None:
        remaining_bot_qty = inputs.runtime_state.remaining_bot_notional / best_buy_ask
        components["remaining_bot_notional_qty"] = str(remaining_bot_qty)
        qty_candidates.append(remaining_bot_qty)

    target_qty = min(qty_candidates)
    return CandidateSizeResult(target_qty=target_qty, components=components)


def simulate_executable_edge(
    inputs: ArbitrageInputs,
    candidate_size: CandidateSizeResult,
) -> ExecutableEdgeResult | None:
    qty = candidate_size.target_qty
    if qty <= 0:
        return None

    buy_vwap = _vwap(inputs.base_orderbook.asks, qty)
    sell_vwap = _vwap(inputs.hedge_orderbook.bids, qty)
    if buy_vwap is None or sell_vwap is None:
        return None
    if buy_vwap <= 0:
        return None

    gross_buy_cost = buy_vwap * qty
    if gross_buy_cost <= 0:
        return None
    gross_sell_proceeds = sell_vwap * qty
    fee_buy = gross_buy_cost * inputs.risk_config.taker_fee_bps_buy / Decimal("10000")
    fee_sell = gross_sell_proceeds * inputs.risk_config.taker_fee_bps_sell / Decimal("10000")
    spread_bps = ((sell_vwap - buy_vwap) / buy_vwap) * Decimal("10000")
    slippage_buffer = gross_buy_cost * inputs.risk_config.slippage_buffer_bps / Decimal("10000")
    executable_profit_quote = (
        gross_sell_proceeds
        - gross_buy_cost
        - fee_buy
        - fee_sell
        - slippage_buffer
        - inputs.risk_config.unwind_buffer_quote
    )
    executable_profit_bps = (executable_profit_quote / gross_buy_cost) * Decimal("10000")
    passed = (
        executable_profit_quote >= inputs.risk_config.min_profit_quote
        and executable_profit_bps >= inputs.risk_config.min_profit_bps
        and spread_bps <= inputs.risk_config.max_spread_bps
    )
    return ExecutableEdgeResult(
        executable_buy_cost_quote=gross_buy_cost,
        executable_sell_proceeds_quote=gross_sell_proceeds,
        executable_profit_quote=executable_profit_quote,
        executable_profit_bps=executable_profit_bps,
        buy_vwap=buy_vwap,
        sell_vwap=sell_vwap,
        total_fee_quote=fee_buy + fee_sell,
        passed=passed,
    )
