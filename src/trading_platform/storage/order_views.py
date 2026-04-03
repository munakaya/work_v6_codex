from __future__ import annotations

from decimal import Decimal


def _fill_aggregate(
    fills_source: list[dict[str, object]], order_id: str
) -> dict[str, str | None]:
    order_fills = [fill for fill in fills_source if fill.get("order_id") == order_id]
    if not order_fills:
        return {
            "filled_qty": "0",
            "avg_fill_price": None,
            "fee_amount": None,
        }

    total_qty = sum(Decimal(str(fill["fill_qty"])) for fill in order_fills)
    total_notional = sum(
        Decimal(str(fill["fill_price"])) * Decimal(str(fill["fill_qty"]))
        for fill in order_fills
    )
    total_fee = sum(
        Decimal(str(fill["fee_amount"]))
        for fill in order_fills
        if fill.get("fee_amount") is not None
    )
    avg_fill_price = None
    if total_qty > 0:
        avg_fill_price = format((total_notional / total_qty).normalize(), "f")
        if "." in avg_fill_price:
            avg_fill_price = avg_fill_price.rstrip("0").rstrip(".")
    filled_qty = format(total_qty.normalize(), "f")
    if "." in filled_qty:
        filled_qty = filled_qty.rstrip("0").rstrip(".")
    fee_amount = format(total_fee.normalize(), "f")
    if "." in fee_amount:
        fee_amount = fee_amount.rstrip("0").rstrip(".")
    return {
        "filled_qty": filled_qty or "0",
        "avg_fill_price": avg_fill_price,
        "fee_amount": fee_amount or "0",
    }


def list_orders(
    orders_by_id: dict[str, dict[str, object]],
    fills_source: list[dict[str, object]],
    *,
    bot_id: str | None = None,
    exchange_name: str | None = None,
    status: str | None = None,
    market: str | None = None,
    strategy_run_id: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    orders = list(orders_by_id.values())
    for key, value in {
        "bot_id": bot_id,
        "exchange_name": exchange_name,
        "status": status,
        "market": market,
        "strategy_run_id": strategy_run_id,
    }.items():
        if value:
            orders = [order for order in orders if order.get(key) == value]
    if created_from:
        orders = [order for order in orders if str(order.get("created_at", "")) >= created_from]
    if created_to:
        orders = [order for order in orders if str(order.get("created_at", "")) <= created_to]
    enriched_orders = [
        {
            **order,
            **_fill_aggregate(fills_source, str(order["order_id"])),
        }
        for order in orders
    ]
    return sorted(
        enriched_orders,
        key=lambda order: str(order.get("updated_at") or ""),
        reverse=True,
    )


def list_fills(
    fills_source: list[dict[str, object]],
    *,
    bot_id: str | None = None,
    exchange_name: str | None = None,
    market: str | None = None,
    strategy_run_id: str | None = None,
    order_id: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    fills = fills_source
    for key, value in {
        "bot_id": bot_id,
        "exchange_name": exchange_name,
        "market": market,
        "strategy_run_id": strategy_run_id,
        "order_id": order_id,
    }.items():
        if value:
            fills = [fill for fill in fills if fill.get(key) == value]
    if created_from:
        fills = [fill for fill in fills if str(fill.get("filled_at", "")) >= created_from]
    if created_to:
        fills = [fill for fill in fills if str(fill.get("filled_at", "")) <= created_to]
    return sorted(fills, key=lambda fill: str(fill.get("filled_at", "")), reverse=True)


def get_order_detail(
    orders_by_id: dict[str, dict[str, object]],
    order_intents_by_id: dict[str, dict[str, object]],
    fills_source: list[dict[str, object]],
    order_id: str,
) -> dict[str, object] | None:
    order = orders_by_id.get(order_id)
    if order is None:
        return None
    aggregate = _fill_aggregate(fills_source, order_id)
    return {
        **order,
        **aggregate,
        "order_intent": order_intents_by_id.get(str(order.get("order_intent_id"))),
        "fills": list_fills(fills_source, order_id=order_id),
        "reconciliation_events": [],
        "decision_record": None,
    }
