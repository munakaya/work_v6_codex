from __future__ import annotations

from .postgres_driver import PostgresDriverAdapter
from .postgres_view_utils import fill, order, order_intent, timestamp_or_none, uuid_or_none


def list_order_intents(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None = None,
    strategy_run_id: str | None = None,
    status: str | None = None,
    market: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if bot_id:
        bot_uuid = uuid_or_none(bot_id)
        if bot_uuid is None:
            return []
        conditions.append("sr.bot_id = %s::uuid")
        params.append(bot_uuid)
    if strategy_run_id:
        run_uuid = uuid_or_none(strategy_run_id)
        if run_uuid is None:
            return []
        conditions.append("oi.strategy_run_id = %s::uuid")
        params.append(run_uuid)
    if status:
        conditions.append("oi.status::text = %s")
        params.append(status)
    if market:
        conditions.append("oi.market = %s")
        params.append(market)
    created_from = timestamp_or_none(created_from)
    created_to = timestamp_or_none(created_to)
    if created_from:
        conditions.append("oi.created_at >= %s::timestamptz")
        params.append(created_from)
    if created_to:
        conditions.append("oi.created_at <= %s::timestamptz")
        params.append(created_to)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            oi.id::text as intent_id,
            sr.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            oi.market,
            oi.buy_exchange,
            oi.sell_exchange,
            oi.side_pair,
            oi.target_qty,
            oi.expected_profit,
            oi.expected_profit_ratio,
            oi.status::text as status,
            oi.created_at,
            oi.decision_context
        from order_intents oi
        join strategy_runs sr on sr.id = oi.strategy_run_id
        {where_clause}
        order by oi.created_at desc
        """,
        tuple(params),
    )
    return [order_intent(row) for row in rows]


def get_order_intent(
    adapter: PostgresDriverAdapter, intent_id: str
) -> dict[str, object] | None:
    intent_uuid = uuid_or_none(intent_id)
    if intent_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            oi.id::text as intent_id,
            sr.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            oi.market,
            oi.buy_exchange,
            oi.sell_exchange,
            oi.side_pair,
            oi.target_qty,
            oi.expected_profit,
            oi.expected_profit_ratio,
            oi.status::text as status,
            oi.created_at,
            oi.decision_context
        from order_intents oi
        join strategy_runs sr on sr.id = oi.strategy_run_id
        where oi.id = %s::uuid
        """,
        (intent_uuid,),
    )
    return None if row is None else order_intent(row)


def list_orders(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None = None,
    exchange_name: str | None = None,
    status: str | None = None,
    market: str | None = None,
    strategy_run_id: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if bot_id:
        bot_uuid = uuid_or_none(bot_id)
        if bot_uuid is None:
            return []
        conditions.append("o.bot_id = %s::uuid")
        params.append(bot_uuid)
    if exchange_name:
        conditions.append("o.exchange_name = %s")
        params.append(exchange_name)
    if status:
        conditions.append("o.status::text = %s")
        params.append(status)
    if market:
        conditions.append("o.market = %s")
        params.append(market)
    if strategy_run_id:
        run_uuid = uuid_or_none(strategy_run_id)
        if run_uuid is None:
            return []
        conditions.append("oi.strategy_run_id = %s::uuid")
        params.append(run_uuid)
    created_from = timestamp_or_none(created_from)
    created_to = timestamp_or_none(created_to)
    if created_from:
        conditions.append("coalesce(o.submitted_at, o.updated_at) >= %s::timestamptz")
        params.append(created_from)
    if created_to:
        conditions.append("coalesce(o.submitted_at, o.updated_at) <= %s::timestamptz")
        params.append(created_to)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            o.id::text as order_id,
            o.order_intent_id::text as order_intent_id,
            o.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            o.exchange_name,
            o.exchange_order_id,
            o.market,
            o.side,
            o.price as requested_price,
            o.quantity as requested_qty,
            fill_agg.filled_qty,
            fill_agg.avg_fill_price,
            fill_agg.fee_amount,
            o.status::text as status,
            o.raw_payload ->> 'internal_error_code' as internal_error_code,
            coalesce(o.submitted_at, o.updated_at) as created_at,
            o.submitted_at,
            o.updated_at
        from orders o
        left join order_intents oi on oi.id = o.order_intent_id
        left join (
            select
                tf.order_id,
                sum(tf.fill_qty) as filled_qty,
                case
                    when sum(tf.fill_qty) > 0
                    then round(sum(tf.fill_price * tf.fill_qty) / sum(tf.fill_qty), 16)
                    else null
                end as avg_fill_price,
                sum(tf.fee_amount) as fee_amount
            from trade_fills tf
            group by tf.order_id
        ) fill_agg on fill_agg.order_id = o.id
        {where_clause}
        order by o.updated_at desc
        """,
        tuple(params),
    )
    return [order(row) for row in rows]


def get_order_detail(
    adapter: PostgresDriverAdapter, order_id: str
) -> dict[str, object] | None:
    order_uuid = uuid_or_none(order_id)
    if order_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            o.id::text as order_id,
            o.order_intent_id::text as order_intent_id,
            o.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            o.exchange_name,
            o.exchange_order_id,
            o.market,
            o.side,
            o.price as requested_price,
            o.quantity as requested_qty,
            fill_agg.filled_qty,
            fill_agg.avg_fill_price,
            fill_agg.fee_amount,
            o.status::text as status,
            o.raw_payload ->> 'internal_error_code' as internal_error_code,
            coalesce(o.submitted_at, o.updated_at) as created_at,
            o.submitted_at,
            o.updated_at
        from orders o
        left join order_intents oi on oi.id = o.order_intent_id
        left join (
            select
                tf.order_id,
                sum(tf.fill_qty) as filled_qty,
                case
                    when sum(tf.fill_qty) > 0
                    then round(sum(tf.fill_price * tf.fill_qty) / sum(tf.fill_qty), 16)
                    else null
                end as avg_fill_price,
                sum(tf.fee_amount) as fee_amount
            from trade_fills tf
            group by tf.order_id
        ) fill_agg on fill_agg.order_id = o.id
        where o.id = %s::uuid
        """,
        (order_uuid,),
    )
    if row is None:
        return None
    payload = order(row)
    payload["order_intent"] = (
        get_order_intent(adapter, str(payload["order_intent_id"]))
        if payload.get("order_intent_id")
        else None
    )
    payload["fills"] = list_fills(adapter, order_id=order_uuid)
    payload["reconciliation_events"] = []
    payload["decision_record"] = None
    return payload


def list_fills(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None = None,
    exchange_name: str | None = None,
    market: str | None = None,
    strategy_run_id: str | None = None,
    order_id: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if bot_id:
        bot_uuid = uuid_or_none(bot_id)
        if bot_uuid is None:
            return []
        conditions.append("o.bot_id = %s::uuid")
        params.append(bot_uuid)
    if exchange_name:
        conditions.append("o.exchange_name = %s")
        params.append(exchange_name)
    if market:
        conditions.append("o.market = %s")
        params.append(market)
    if strategy_run_id:
        run_uuid = uuid_or_none(strategy_run_id)
        if run_uuid is None:
            return []
        conditions.append("oi.strategy_run_id = %s::uuid")
        params.append(run_uuid)
    if order_id:
        order_uuid = uuid_or_none(order_id)
        if order_uuid is None:
            return []
        conditions.append("tf.order_id = %s::uuid")
        params.append(order_uuid)
    created_from = timestamp_or_none(created_from)
    created_to = timestamp_or_none(created_to)
    if created_from:
        conditions.append("tf.filled_at >= %s::timestamptz")
        params.append(created_from)
    if created_to:
        conditions.append("tf.filled_at <= %s::timestamptz")
        params.append(created_to)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            tf.id::text as fill_id,
            tf.order_id::text as order_id,
            o.order_intent_id::text as order_intent_id,
            o.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            o.exchange_name,
            tf.exchange_trade_id,
            o.market,
            o.side,
            tf.fill_price,
            tf.fill_qty,
            tf.fee_asset,
            tf.fee_amount,
            o.status::text as order_status,
            tf.filled_at,
            tf.created_at
        from trade_fills tf
        join orders o on o.id = tf.order_id
        left join order_intents oi on oi.id = o.order_intent_id
        {where_clause}
        order by tf.filled_at desc
        """,
        tuple(params),
    )
    return [fill(row) for row in rows]


def get_fill(adapter: PostgresDriverAdapter, fill_id: str) -> dict[str, object] | None:
    fill_uuid = uuid_or_none(fill_id)
    if fill_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            tf.id::text as fill_id,
            tf.order_id::text as order_id,
            o.order_intent_id::text as order_intent_id,
            o.bot_id::text as bot_id,
            oi.strategy_run_id::text as strategy_run_id,
            o.exchange_name,
            tf.exchange_trade_id,
            o.market,
            o.side,
            tf.fill_price,
            tf.fill_qty,
            tf.fee_asset,
            tf.fee_amount,
            o.status::text as order_status,
            tf.filled_at,
            tf.created_at
        from trade_fills tf
        join orders o on o.id = tf.order_id
        left join order_intents oi on oi.id = o.order_intent_id
        where tf.id = %s::uuid
        """,
        (fill_uuid,),
    )
    return None if row is None else fill(row)
