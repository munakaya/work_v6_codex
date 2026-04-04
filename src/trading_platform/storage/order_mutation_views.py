from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4


def _sample_time() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_order_intent(
    *,
    strategy_runs: dict[str, dict[str, object]],
    order_intents: dict[str, dict[str, object]],
    strategy_run_id: str,
    market: str,
    buy_exchange: str,
    sell_exchange: str,
    side_pair: str,
    target_qty: str,
    expected_profit: str | None,
    expected_profit_ratio: str | None,
    status: str,
    decision_context: dict[str, object] | None,
) -> tuple[str, dict[str, object] | None]:
    run = strategy_runs.get(strategy_run_id)
    if run is None:
        return "not_found", None
    intent = {
        "intent_id": str(uuid4()),
        "bot_id": run["bot_id"],
        "strategy_run_id": strategy_run_id,
        "market": market,
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "side_pair": side_pair,
        "target_qty": target_qty,
        "expected_profit": expected_profit,
        "expected_profit_ratio": expected_profit_ratio,
        "status": status,
        "created_at": _sample_time(),
        "decision_context": decision_context or {},
    }
    order_intents[intent["intent_id"]] = intent
    run["decision_count"] = int(run.get("decision_count", 0)) + 1
    return "created", intent


def create_order(
    *,
    order_intents: dict[str, dict[str, object]],
    orders: dict[str, dict[str, object]],
    order_intent_id: str,
    exchange_name: str,
    exchange_order_id: str | None,
    market: str,
    side: str,
    requested_price: str | None,
    requested_qty: str,
    status: str,
    raw_payload: dict[str, object] | None,
) -> tuple[str, dict[str, object] | None]:
    intent = order_intents.get(order_intent_id)
    if intent is None:
        return "not_found", None
    if market != intent["market"]:
        return "invalid", None
    if exchange_name not in {intent["buy_exchange"], intent["sell_exchange"]}:
        return "invalid", None
    if exchange_order_id is not None:
        existing = next(
            (
                order
                for order in orders.values()
                if order.get("exchange_name") == exchange_name
                and order.get("exchange_order_id") == exchange_order_id
            ),
            None,
        )
        if existing is not None:
            return "conflict", existing
    created_at = _sample_time()
    order = {
        "order_id": str(uuid4()),
        "order_intent_id": order_intent_id,
        "bot_id": intent["bot_id"],
        "strategy_run_id": intent["strategy_run_id"],
        "exchange_name": exchange_name,
        "exchange_order_id": exchange_order_id,
        "market": market,
        "side": side,
        "requested_price": requested_price,
        "requested_qty": requested_qty,
        "filled_qty": "0",
        "avg_fill_price": None,
        "fee_amount": None,
        "status": status,
        "internal_error_code": None,
        "created_at": created_at,
        "submitted_at": created_at,
        "updated_at": created_at,
        "raw_payload": raw_payload or {},
    }
    orders[order["order_id"]] = order
    if intent["status"] == "created":
        intent["status"] = "submitted"
    return "created", order


def create_fill(
    *,
    orders: dict[str, dict[str, object]],
    order_intents: dict[str, dict[str, object]],
    fills: list[dict[str, object]],
    order_id: str,
    exchange_trade_id: str | None,
    fill_price: str,
    fill_qty: str,
    fee_asset: str | None,
    fee_amount: str | None,
    filled_at: str,
) -> tuple[str, dict[str, object] | None]:
    order = orders.get(order_id)
    if order is None:
        return "not_found", None
    if str(order.get("status")) in {"cancelled", "rejected", "expired", "filled"}:
        return "invalid", None
    if exchange_trade_id is not None:
        existing = next(
            (
                fill
                for fill in fills
                if fill.get("order_id") == order_id
                and fill.get("exchange_trade_id") == exchange_trade_id
            ),
            None,
        )
        if existing is not None:
            return "conflict", existing

    requested_qty = Decimal(str(order["requested_qty"]))
    current_filled_qty = sum(
        Decimal(str(fill["fill_qty"]))
        for fill in fills
        if fill.get("order_id") == order_id
    )
    next_filled_qty = current_filled_qty + Decimal(fill_qty)
    if next_filled_qty > requested_qty:
        return "invalid", None

    created_at = _sample_time()
    next_status = "filled" if next_filled_qty == requested_qty else "partially_filled"
    order["status"] = next_status
    order["updated_at"] = created_at

    intent = order_intents.get(str(order.get("order_intent_id")))
    fill = {
        "fill_id": str(uuid4()),
        "order_id": order_id,
        "order_intent_id": order.get("order_intent_id"),
        "bot_id": order.get("bot_id"),
        "strategy_run_id": order.get("strategy_run_id"),
        "exchange_name": order["exchange_name"],
        "exchange_trade_id": exchange_trade_id,
        "market": order["market"],
        "side": order["side"],
        "fill_price": fill_price,
        "fill_qty": fill_qty,
        "fee_asset": fee_asset,
        "fee_amount": fee_amount,
        "order_status": next_status,
        "filled_at": filled_at,
        "created_at": created_at,
    }
    fills.insert(0, fill)
    if intent is not None:
        if intent.get("status") == "created":
            intent["status"] = "submitted"
        related_orders = [
            item
            for item in orders.values()
            if item.get("order_intent_id") == intent.get("intent_id")
        ]
        if related_orders and all(
            str(item.get("status") or "") == "filled" for item in related_orders
        ):
            intent["status"] = "simulated"
    return "created", fill
