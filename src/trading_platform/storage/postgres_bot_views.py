from __future__ import annotations

from .postgres_driver import PostgresDriverAdapter
from .postgres_view_utils import (
    alert_event,
    bot_summary,
    config_version,
    heartbeat_entry,
    strategy_run,
    timestamp_or_none,
    uuid_or_none,
)


def list_bots(
    adapter: PostgresDriverAdapter,
    *,
    status: str | None = None,
    strategy_name: str | None = None,
    mode: str | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if status:
        conditions.append("b.status::text = %s")
        params.append("pending" if status == "created" else status)
    if strategy_name:
        conditions.append("b.strategy_name = %s")
        params.append(strategy_name)
    if mode:
        conditions.append("b.mode::text = %s")
        params.append(mode)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            b.id::text as bot_id,
            b.bot_key,
            b.strategy_name,
            b.mode::text as mode,
            case when b.status::text = 'pending' then 'created' else b.status::text end as status,
            b.hostname,
            b.last_seen_at,
            assigned.config_scope as assigned_config_scope,
            assigned.version_no as assigned_version_no,
            assigned.config_version_id as assigned_config_version_id,
            assigned.assigned_at,
            assigned.apply_status as assigned_apply_status,
            assigned.acknowledged_at as assigned_acknowledged_at,
            assigned.ack_message as assigned_ack_message,
            assigned.changed_sections as assigned_changed_sections,
            assigned.hot_reloadable_sections as assigned_hot_reloadable_sections,
            assigned.restart_required_sections as assigned_restart_required_sections
        from bots b
        left join lateral (
            select
                cv.config_scope,
                cv.version_no,
                cv.id::text as config_version_id,
                bca.created_at as assigned_at,
                bca.ack_status as apply_status,
                bca.acked_at as acknowledged_at,
                bca.ack_message,
                bca.changed_sections,
                bca.hot_reloadable_sections,
                bca.restart_required_sections
            from bot_config_assignments bca
            join config_versions cv on cv.id = bca.config_version_id
            where bca.bot_id = b.id
            order by bca.created_at desc
            limit 1
        ) assigned on true
        {where_clause}
        order by coalesce(b.last_seen_at, b.updated_at, b.created_at) desc
        """,
        tuple(params),
    )
    return [bot_summary(row) for row in rows]


def get_bot_detail(
    adapter: PostgresDriverAdapter, bot_id: str
) -> dict[str, object] | None:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            b.id::text as bot_id,
            b.bot_key,
            b.strategy_name,
            b.mode::text as mode,
            case when b.status::text = 'pending' then 'created' else b.status::text end as status,
            b.hostname,
            b.last_seen_at,
            assigned.config_scope as assigned_config_scope,
            assigned.version_no as assigned_version_no,
            assigned.config_version_id as assigned_config_version_id,
            assigned.assigned_at,
            assigned.apply_status as assigned_apply_status,
            assigned.acknowledged_at as assigned_acknowledged_at,
            assigned.ack_message as assigned_ack_message,
            assigned.changed_sections as assigned_changed_sections,
            assigned.hot_reloadable_sections as assigned_hot_reloadable_sections,
            assigned.restart_required_sections as assigned_restart_required_sections
        from bots b
        left join lateral (
            select
                cv.config_scope,
                cv.version_no,
                cv.id::text as config_version_id,
                bca.created_at as assigned_at,
                bca.ack_status as apply_status,
                bca.acked_at as acknowledged_at,
                bca.ack_message,
                bca.changed_sections,
                bca.hot_reloadable_sections,
                bca.restart_required_sections
            from bot_config_assignments bca
            join config_versions cv on cv.id = bca.config_version_id
            where bca.bot_id = b.id
            order by bca.created_at desc
            limit 1
        ) assigned on true
        where b.id = %s::uuid
        """,
        (bot_uuid,),
    )
    if row is None:
        return None
    detail = bot_summary(row)
    detail["latest_heartbeat"] = latest_heartbeat(adapter, bot_uuid)
    detail["latest_strategy_run"] = latest_strategy_run(adapter, bot_uuid)
    detail["recent_alerts"] = recent_alerts(adapter, bot_uuid, limit=5)
    return detail


def list_strategy_runs(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None = None,
    status: str | None = None,
    mode: str | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if bot_id:
        bot_uuid = uuid_or_none(bot_id)
        if bot_uuid is None:
            return []
        conditions.append("sr.bot_id = %s::uuid")
        params.append(bot_uuid)
    if status:
        conditions.append("sr.status::text = %s")
        params.append("pending" if status == "created" else status)
    if mode:
        conditions.append("sr.mode::text = %s")
        params.append(mode)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            sr.id::text as run_id,
            sr.bot_id::text as bot_id,
            sr.strategy_name,
            sr.mode::text as mode,
            sr.status::text as status,
            sr.created_at,
            sr.started_at,
            sr.ended_at as stopped_at,
            0 as decision_count
        from strategy_runs sr
        {where_clause}
        order by coalesce(sr.started_at, sr.created_at, sr.ended_at) desc
        """,
        tuple(params),
    )
    return [strategy_run(row) for row in rows]


def get_strategy_run(
    adapter: PostgresDriverAdapter, run_id: str
) -> dict[str, object] | None:
    run_uuid = uuid_or_none(run_id)
    if run_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            sr.id::text as run_id,
            sr.bot_id::text as bot_id,
            sr.strategy_name,
            sr.mode::text as mode,
            sr.status::text as status,
            sr.created_at,
            sr.started_at,
            sr.ended_at as stopped_at,
            0 as decision_count
        from strategy_runs sr
        where sr.id = %s::uuid
        """,
        (run_uuid,),
    )
    return None if row is None else strategy_run(row)


def list_heartbeats(
    adapter: PostgresDriverAdapter,
    bot_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, object]] | None:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None:
        return None
    rows = adapter.fetch_all(
        """
        select
            created_at,
            is_process_alive,
            is_market_data_alive,
            is_ordering_alive,
            lag_ms,
            payload
        from bot_heartbeats
        where bot_id = %s::uuid
        order by created_at desc
        limit %s
        """,
        (bot_uuid, limit),
    )
    if not rows and not bot_exists(adapter, bot_uuid):
        return None
    return [heartbeat_entry(row) for row in rows]


def list_alerts(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None = None,
    level: str | None = None,
    acknowledged: bool | None = None,
) -> list[dict[str, object]]:
    conditions = []
    params: list[object] = []
    if bot_id:
        bot_uuid = uuid_or_none(bot_id)
        if bot_uuid is None:
            return []
        conditions.append("bot_id = %s::uuid")
        params.append(bot_uuid)
    if level:
        conditions.append("level::text = %s")
        params.append(level)
    if acknowledged is True:
        conditions.append("acknowledged_at is not null")
    if acknowledged is False:
        conditions.append("acknowledged_at is null")
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""
    rows = adapter.fetch_all(
        f"""
        select
            id::text as alert_id,
            bot_id::text as bot_id,
            level::text as level,
            code,
            message,
            created_at,
            acknowledged_at
        from alert_events
        {where_clause}
        order by created_at desc
        """,
        tuple(params),
    )
    return [alert_event(row) for row in rows]


def latest_config(
    adapter: PostgresDriverAdapter, config_scope: str
) -> dict[str, object] | None:
    row = adapter.fetch_one(
        """
        select
            id::text as config_version_id,
            config_scope,
            version_no,
            config_json,
            checksum,
            created_by,
            created_at
        from config_versions
        where config_scope = %s
        order by version_no desc, created_at desc
        limit 1
        """,
        (config_scope,),
    )
    return None if row is None else config_version(row)


def list_config_versions(
    adapter: PostgresDriverAdapter, config_scope: str
) -> list[dict[str, object]]:
    rows = adapter.fetch_all(
        """
        select
            id::text as config_version_id,
            config_scope,
            version_no,
            config_json,
            checksum,
            created_by,
            created_at
        from config_versions
        where config_scope = %s
        order by version_no desc, created_at desc
        """,
        (config_scope,),
    )
    return [config_version(row) for row in rows]


def get_alert_detail(
    adapter: PostgresDriverAdapter, alert_id: str
) -> dict[str, object] | None:
    alert_uuid = uuid_or_none(alert_id)
    if alert_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        select
            id::text as alert_id,
            bot_id::text as bot_id,
            level::text as level,
            code,
            message,
            created_at,
            acknowledged_at
        from alert_events
        where id = %s::uuid
        limit 1
        """,
        (alert_uuid,),
    )
    return None if row is None else alert_event(row)


def active_bot_count(adapter: PostgresDriverAdapter) -> int:
    value = adapter.fetch_value("select count(*) from bots where status::text = 'running'")
    return int(value or 0)


def active_strategy_run_count(adapter: PostgresDriverAdapter) -> int:
    value = adapter.fetch_value(
        "select count(*) from strategy_runs where status::text = 'running'"
    )
    return int(value or 0)


def latest_heartbeat(
    adapter: PostgresDriverAdapter, bot_id: str
) -> dict[str, object] | None:
    heartbeats = list_heartbeats(adapter, bot_id, limit=1)
    if not heartbeats:
        return None
    return heartbeats[0]


def latest_strategy_run(
    adapter: PostgresDriverAdapter, bot_id: str
) -> dict[str, object] | None:
    runs = list_strategy_runs(adapter, bot_id=bot_id)
    if not runs:
        return None
    return runs[0]


def recent_alerts(
    adapter: PostgresDriverAdapter, bot_id: str, *, limit: int
) -> list[dict[str, object]]:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None:
        return []
    rows = adapter.fetch_all(
        """
        select
            id::text as alert_id,
            bot_id::text as bot_id,
            level::text as level,
            code,
            message,
            created_at,
            acknowledged_at
        from alert_events
        where bot_id = %s::uuid
        order by created_at desc
        limit %s
        """,
        (bot_uuid, limit),
    )
    return [alert_event(row) for row in rows]


def bot_exists(adapter: PostgresDriverAdapter, bot_id: str) -> bool:
    value = adapter.fetch_value(
        "select count(*) from bots where id = %s::uuid",
        (bot_id,),
    )
    return bool(int(value or 0))
