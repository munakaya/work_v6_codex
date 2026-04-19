from __future__ import annotations

from decimal import Decimal

from .arbitrage_models import ArbitrageInputs, CandidateSizeResult, ExecutableEdgeResult


def _sum_depth_qty(levels: tuple[object, ...]) -> Decimal:
    total = Decimal("0")
    for level in levels:
        total += level.quantity
    return total


def _sum_depth_notional(levels: tuple[object, ...]) -> Decimal:
    total = Decimal("0")
    for level in levels:
        total += level.price * level.quantity
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


def _max_qty_with_quote_limit(levels: tuple[object, ...], quote_limit: Decimal) -> Decimal:
    if quote_limit <= 0:
        return Decimal("0")
    remaining_quote = quote_limit
    total_qty = Decimal("0")
    for level in levels:
        if level.price <= 0 or level.quantity <= 0:
            continue
        level_notional = level.price * level.quantity
        if remaining_quote >= level_notional:
            total_qty += level.quantity
            remaining_quote -= level_notional
            continue
        total_qty += remaining_quote / level.price
        remaining_quote = Decimal("0")
        break
    return total_qty


def _gross_buy_cost_budget_for_quote_requirement(inputs: ArbitrageInputs) -> Decimal:
    fixed_quote_buffer = (
        inputs.risk_config.unwind_buffer_quote
        + inputs.risk_config.rebalance_buffer_quote
    )
    quote_budget = inputs.base_balance.available_quote - fixed_quote_buffer
    if quote_budget <= 0:
        return Decimal("0")
    multiplier = (
        Decimal("1")
        + inputs.risk_config.taker_fee_bps_buy / Decimal("10000")
        + inputs.risk_config.slippage_buffer_bps / Decimal("10000")
    )
    if multiplier <= 0:
        return Decimal("0")
    return quote_budget / multiplier


def compute_candidate_size(inputs: ArbitrageInputs) -> CandidateSizeResult:
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
    buy_depth_qty = _sum_depth_qty(inputs.base_orderbook.asks)
    sell_depth_qty = _sum_depth_qty(inputs.hedge_orderbook.bids)
    buy_depth_notional_quote = _sum_depth_notional(inputs.base_orderbook.asks)
    sell_depth_notional_quote = _sum_depth_notional(inputs.hedge_orderbook.bids)
    buy_quote_budget_for_gross_cost = _gross_buy_cost_budget_for_quote_requirement(inputs)
    buy_quote_available_qty = _max_qty_with_quote_limit(
        inputs.base_orderbook.asks,
        buy_quote_budget_for_gross_cost,
    )
    sell_base_available_qty = inputs.hedge_balance.available_base
    max_notional_per_order_qty = _max_qty_with_quote_limit(
        inputs.base_orderbook.asks,
        inputs.risk_config.max_notional_per_order,
    )
    max_total_notional_per_bot_qty = _max_qty_with_quote_limit(
        inputs.base_orderbook.asks,
        inputs.risk_config.max_total_notional_per_bot,
    )
    remaining_bot_notional_qty = (
        _max_qty_with_quote_limit(
            inputs.base_orderbook.asks,
            inputs.runtime_state.remaining_bot_notional,
        )
        if inputs.runtime_state.remaining_bot_notional is not None
        else buy_depth_qty
    )

    components = {
        "buy_depth_levels": str(len(inputs.base_orderbook.asks)),
        "sell_depth_levels": str(len(inputs.hedge_orderbook.bids)),
        "buy_depth_qty": str(buy_depth_qty),
        "sell_depth_qty": str(sell_depth_qty),
        "buy_depth_notional_quote": str(buy_depth_notional_quote),
        "sell_depth_notional_quote": str(sell_depth_notional_quote),
        "buy_quote_available": str(inputs.base_balance.available_quote),
        "sell_base_available": str(inputs.hedge_balance.available_base),
        "buy_quote_budget_for_gross_cost": str(buy_quote_budget_for_gross_cost),
        "buy_quote_available_qty": str(buy_quote_available_qty),
        "sell_base_available_qty": str(sell_base_available_qty),
        "max_notional_per_order_qty": str(max_notional_per_order_qty),
        "max_total_notional_per_bot_qty": str(max_total_notional_per_bot_qty),
        "remaining_bot_notional_qty": str(remaining_bot_notional_qty),
    }
    qty_candidates = [
        buy_depth_qty,
        sell_depth_qty,
        buy_quote_available_qty,
        sell_base_available_qty,
        max_notional_per_order_qty,
        max_total_notional_per_bot_qty,
        remaining_bot_notional_qty,
    ]
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
    gross_profit_quote = gross_sell_proceeds - gross_buy_cost
    fee_buy = gross_buy_cost * inputs.risk_config.taker_fee_bps_buy / Decimal("10000")
    fee_sell = gross_sell_proceeds * inputs.risk_config.taker_fee_bps_sell / Decimal("10000")
    spread_bps = ((sell_vwap - buy_vwap) / buy_vwap) * Decimal("10000")
    buy_slippage_buffer = (
        gross_buy_cost * inputs.risk_config.slippage_buffer_bps / Decimal("10000")
    )
    sell_slippage_buffer = (
        gross_sell_proceeds * inputs.risk_config.slippage_buffer_bps / Decimal("10000")
    )
    total_cost_adjustment_quote = (
        fee_buy
        + fee_sell
        + buy_slippage_buffer
        + sell_slippage_buffer
        + inputs.risk_config.unwind_buffer_quote
        + inputs.risk_config.rebalance_buffer_quote
    )
    executable_profit_quote = gross_profit_quote - total_cost_adjustment_quote
    executable_profit_bps = (executable_profit_quote / gross_buy_cost) * Decimal("10000")
    passed = (
        executable_profit_quote >= inputs.risk_config.min_profit_quote
        and executable_profit_bps >= inputs.risk_config.min_profit_bps
        and spread_bps <= inputs.risk_config.max_spread_bps
    )
    return ExecutableEdgeResult(
        executable_buy_cost_quote=gross_buy_cost,
        executable_sell_proceeds_quote=gross_sell_proceeds,
        gross_profit_quote=gross_profit_quote,
        executable_profit_quote=executable_profit_quote,
        executable_profit_bps=executable_profit_bps,
        buy_vwap=buy_vwap,
        sell_vwap=sell_vwap,
        fee_buy_quote=fee_buy,
        fee_sell_quote=fee_sell,
        buy_slippage_buffer_quote=buy_slippage_buffer,
        sell_slippage_buffer_quote=sell_slippage_buffer,
        unwind_buffer_quote=inputs.risk_config.unwind_buffer_quote,
        rebalance_buffer_quote=inputs.risk_config.rebalance_buffer_quote,
        total_fee_quote=fee_buy + fee_sell,
        total_cost_adjustment_quote=total_cost_adjustment_quote,
        passed=passed,
    )
