from __future__ import annotations

import json
from decimal import Decimal

from .postgres_order_views import get_fill, get_order_detail, get_order_intent
from .postgres_driver import PostgresDriverAdapter
from .postgres_view_utils import uuid_or_none


def create_order_intent(
    adapter: PostgresDriverAdapter,
    *,
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
    run_uuid = uuid_or_none(strategy_run_id)
    if run_uuid is None:
        return "not_found", None
    run_exists = adapter.fetch_value(
        "select count(*) from strategy_runs where id = %s::uuid",
        (run_uuid,),
    )
    if not int(run_exists or 0):
        return "not_found", None
    decision_context_json = json.dumps(
        decision_context or {}, separators=(",", ":"), ensure_ascii=True
    )
    row = adapter.fetch_one(
        """
        insert into order_intents (
            strategy_run_id,
            market,
            buy_exchange,
            sell_exchange,
            side_pair,
            target_qty,
            expected_profit,
            expected_profit_ratio,
            status,
            decision_context
        )
        values (
            %s::uuid,
            %s,
            %s,
            %s,
            %s,
            %s::numeric,
            %s::numeric,
            %s::numeric,
            %s::order_intent_status,
            %s::jsonb
        )
        returning id::text as intent_id
        """,
        (
            run_uuid,
            market,
            buy_exchange,
            sell_exchange,
            side_pair,
            target_qty,
            expected_profit,
            expected_profit_ratio,
            status,
            decision_context_json,
        ),
    )
    if row is None:
        raise RuntimeError("failed to create order intent")
    return "created", get_order_intent(adapter, str(row["intent_id"]))


def create_order(
    adapter: PostgresDriverAdapter,
    *,
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
    intent_uuid = uuid_or_none(order_intent_id)
    if intent_uuid is None:
        return "not_found", None
    intent = adapter.fetch_one(
        """
        select
            oi.id::text as intent_id,
            sr.bot_id::text as bot_id,
            oi.market,
            oi.buy_exchange,
            oi.sell_exchange
        from order_intents oi
        join strategy_runs sr on sr.id = oi.strategy_run_id
        where oi.id = %s::uuid
        """,
        (intent_uuid,),
    )
    if intent is None:
        return "not_found", None
    if market != str(intent["market"]):
        return "invalid", None
    if exchange_name not in {str(intent["buy_exchange"]), str(intent["sell_exchange"])}:
        return "invalid", None
    if exchange_order_id is not None:
        existing_id = adapter.fetch_value(
            """
            select id::text
            from orders
            where exchange_name = %s
              and exchange_order_id = %s
            limit 1
            """,
            (exchange_name, exchange_order_id),
        )
        if existing_id is not None:
            return "conflict", get_order_detail(adapter, str(existing_id))
    raw_payload_json = json.dumps(raw_payload or {}, separators=(",", ":"), ensure_ascii=True)
    row = adapter.fetch_one(
        """
        insert into orders (
            order_intent_id,
            bot_id,
            exchange_name,
            exchange_order_id,
            market,
            side,
            price,
            quantity,
            status,
            submitted_at,
            updated_at,
            raw_payload
        )
        values (
            %s::uuid,
            %s::uuid,
            %s,
            %s,
            %s,
            %s,
            %s::numeric,
            %s::numeric,
            %s::order_status,
            now(),
            now(),
            %s::jsonb
        )
        returning id::text as order_id
        """,
        (
            intent_uuid,
            intent["bot_id"],
            exchange_name,
            exchange_order_id,
            market,
            side,
            requested_price,
            requested_qty,
            status,
            raw_payload_json,
        ),
    )
    if row is None:
        raise RuntimeError("failed to create order")
    adapter.fetch_one(
        """
        update order_intents
        set status = 'submitted'::order_intent_status
        where id = %s::uuid
          and status::text = 'created'
        returning id::text as intent_id
        """,
        (intent_uuid,),
    )
    return "created", get_order_detail(adapter, str(row["order_id"]))


def create_fill(
    adapter: PostgresDriverAdapter,
    *,
    order_id: str,
    exchange_trade_id: str | None,
    fill_price: str,
    fill_qty: str,
    fee_asset: str | None,
    fee_amount: str | None,
    filled_at: str,
) -> tuple[str, dict[str, object] | None]:
    order_uuid = uuid_or_none(order_id)
    if order_uuid is None:
        return "not_found", None
    order_row = adapter.fetch_one(
        """
        select
            o.id::text as order_id,
            o.status::text as status,
            o.quantity as requested_qty,
            coalesce(sum(tf.fill_qty), 0) as current_filled_qty
        from orders o
        left join trade_fills tf on tf.order_id = o.id
        where o.id = %s::uuid
        group by o.id, o.status, o.quantity
        """,
        (order_uuid,),
    )
    if order_row is None:
        return "not_found", None
    if str(order_row["status"]) in {"cancelled", "rejected", "expired", "filled"}:
        return "invalid", None
    if exchange_trade_id is not None:
        existing_id = adapter.fetch_value(
            """
            select id::text
            from trade_fills
            where order_id = %s::uuid
              and exchange_trade_id = %s
            limit 1
            """,
            (order_uuid, exchange_trade_id),
        )
        if existing_id is not None:
            return "conflict", get_fill(adapter, str(existing_id))

    requested_qty = Decimal(str(order_row["requested_qty"]))
    current_filled_qty = Decimal(str(order_row["current_filled_qty"]))
    next_filled_qty = current_filled_qty + Decimal(fill_qty)
    if next_filled_qty > requested_qty:
        return "invalid", None
    next_status = "filled" if next_filled_qty == requested_qty else "partially_filled"
    row = adapter.fetch_one(
        """
        with inserted_fill as (
            insert into trade_fills (
                order_id,
                exchange_trade_id,
                fill_price,
                fill_qty,
                fee_asset,
                fee_amount,
                filled_at
            )
            values (
                %s::uuid,
                %s,
                %s::numeric,
                %s::numeric,
                %s,
                %s::numeric,
                %s::timestamptz
            )
            returning id::text as fill_id
        ), updated_order as (
            update orders
            set
                status = %s::order_status,
                updated_at = now()
            where id = %s::uuid
            returning id::text as order_id
        )
        select inserted_fill.fill_id
        from inserted_fill
        join updated_order on true
        """,
        (
            order_uuid,
            exchange_trade_id,
            fill_price,
            fill_qty,
            fee_asset,
            fee_amount,
            filled_at,
            next_status,
            order_uuid,
        ),
    )
    if row is None:
        raise RuntimeError("failed to create fill")
    return "created", get_fill(adapter, str(row["fill_id"]))
