from __future__ import annotations

import json

from .postgres_bot_views import (
    bot_exists,
    get_bot_detail,
    get_strategy_run,
    latest_config,
)
from .postgres_driver import PostgresDriverAdapter
from .postgres_view_utils import alert_event, config_version, iso_text, uuid_or_none


def emit_alert(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str | None,
    level: str,
    code: str,
    message: str,
) -> dict[str, object]:
    bot_uuid = uuid_or_none(bot_id) if bot_id is not None else None
    row = adapter.fetch_one(
        """
        insert into alert_events (bot_id, level, code, message, context)
        values (%s::uuid, %s::alert_level, %s, %s, null)
        returning
            id::text as alert_id,
            bot_id::text as bot_id,
            level::text as level,
            code,
            message,
            created_at,
            acknowledged_at
        """,
        (bot_uuid, level, code, message),
    )
    if row is None:
        raise RuntimeError("failed to insert alert event")
    return alert_event(row)


def create_config_version(
    adapter: PostgresDriverAdapter,
    *,
    config_scope: str,
    config_json: dict[str, object],
    checksum: str,
    created_by: str | None,
) -> dict[str, object]:
    config_json_text = json.dumps(config_json, separators=(",", ":"), ensure_ascii=True)
    row = adapter.fetch_one(
        """
        with next_version as (
            select coalesce(max(version_no), 0) + 1 as version_no
            from config_versions
            where config_scope = %s
        )
        insert into config_versions (
            config_scope,
            version_no,
            config_json,
            checksum,
            created_by
        )
        select
            %s,
            next_version.version_no,
            %s::jsonb,
            %s,
            %s
        from next_version
        returning
            id::text as config_version_id,
            config_scope,
            version_no,
            config_json,
            checksum,
            created_by,
            created_at
        """,
        (config_scope, config_scope, config_json_text, checksum, created_by),
    )
    if row is None:
        raise RuntimeError("failed to insert config version")
    return config_version(row)


def create_strategy_run(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str,
    strategy_name: str,
    mode: str,
) -> tuple[str, dict[str, object] | None]:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None:
        return "not_found", None
    if not bot_exists(adapter, bot_uuid):
        return "not_found", None
    existing_run_id = adapter.fetch_value(
        """
        select id::text
        from strategy_runs
        where bot_id = %s::uuid
          and status::text in ('pending', 'running')
        order by created_at desc
        limit 1
        """,
        (bot_uuid,),
    )
    if existing_run_id is not None:
        return "conflict", get_strategy_run(adapter, str(existing_run_id))
    row = adapter.fetch_one(
        """
        insert into strategy_runs (
            bot_id,
            strategy_name,
            mode,
            status
        )
        values (
            %s::uuid,
            %s,
            %s::run_mode,
            'pending'::strategy_status
        )
        returning id::text as run_id
        """,
        (bot_uuid, strategy_name, mode),
    )
    if row is None:
        raise RuntimeError("failed to create strategy run")
    return "created", get_strategy_run(adapter, str(row["run_id"]))


def start_strategy_run(
    adapter: PostgresDriverAdapter, run_id: str
) -> tuple[str, dict[str, object] | None]:
    run_uuid = uuid_or_none(run_id)
    if run_uuid is None:
        return "not_found", None
    run = adapter.fetch_one(
        """
        select
            id::text as run_id,
            bot_id::text as bot_id,
            status::text as status
        from strategy_runs
        where id = %s::uuid
        """,
        (run_uuid,),
    )
    if run is None:
        return "not_found", None
    if run["status"] != "pending":
        return "conflict", get_strategy_run(adapter, run_id)
    running_for_bot = adapter.fetch_value(
        """
        select id::text
        from strategy_runs
        where bot_id = %s::uuid
          and id <> %s::uuid
          and status::text = 'running'
        limit 1
        """,
        (run["bot_id"], run_uuid),
    )
    if running_for_bot is not None:
        return "conflict", get_strategy_run(adapter, run_id)
    adapter.fetch_one(
        """
        update strategy_runs
        set
            status = 'running'::strategy_status,
            started_at = coalesce(started_at, now()),
            ended_at = null
        where id = %s::uuid
        returning id::text as run_id
        """,
        (run_uuid,),
    )
    return "started", get_strategy_run(adapter, run_id)


def stop_strategy_run(
    adapter: PostgresDriverAdapter, run_id: str
) -> tuple[str, dict[str, object] | None]:
    run_uuid = uuid_or_none(run_id)
    if run_uuid is None:
        return "not_found", None
    run = adapter.fetch_one(
        """
        select status::text as status
        from strategy_runs
        where id = %s::uuid
        """,
        (run_uuid,),
    )
    if run is None:
        return "not_found", None
    if run["status"] != "running":
        return "conflict", get_strategy_run(adapter, run_id)
    adapter.fetch_one(
        """
        update strategy_runs
        set
            status = 'stopped'::strategy_status,
            ended_at = now()
        where id = %s::uuid
        returning id::text as run_id
        """,
        (run_uuid,),
    )
    return "stopped", get_strategy_run(adapter, run_id)


def assign_config(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str,
    config_scope: str,
    version_no: int,
) -> dict[str, object] | None:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None or not bot_exists(adapter, bot_uuid):
        return None
    version_row = adapter.fetch_one(
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
          and version_no = %s
        limit 1
        """,
        (config_scope, version_no),
    )
    if version_row is None:
        return None
    row = adapter.fetch_one(
        """
        insert into bot_config_assignments (
            bot_id,
            config_version_id,
            applied,
            applied_at
        )
        values (
            %s::uuid,
            %s::uuid,
            true,
            now()
        )
        returning
            %s as config_scope,
            %s as version_no,
            config_version_id::text as config_version_id,
            coalesce(applied_at, created_at) as assigned_at
        """,
        (
            bot_uuid,
            version_row["config_version_id"],
            version_row["config_scope"],
            version_row["version_no"],
        ),
    )
    if row is None:
        raise RuntimeError("failed to assign config version")
    emit_alert(
        adapter,
        bot_id=bot_id,
        level="info",
        code="CONFIG_ASSIGNED",
        message=f"config {config_scope} v{version_no} assigned",
    )
    return {
        "config_scope": row["config_scope"],
        "version_no": int(version_no),
        "config_version_id": row["config_version_id"],
        "assigned_at": iso_text(row.get("assigned_at")),
    }


def acknowledge_alert(
    adapter: PostgresDriverAdapter, alert_id: str
) -> dict[str, object] | None:
    alert_uuid = uuid_or_none(alert_id)
    if alert_uuid is None:
        return None
    row = adapter.fetch_one(
        """
        update alert_events
        set acknowledged_at = now()
        where id = %s::uuid
        returning
            id::text as alert_id,
            acknowledged_at
        """,
        (alert_uuid,),
    )
    if row is None:
        return None
    return {
        "alert_id": row["alert_id"],
        "acknowledged_at": iso_text(row.get("acknowledged_at")),
    }


def register_bot(
    adapter: PostgresDriverAdapter,
    *,
    bot_key: str,
    strategy_name: str,
    mode: str,
    hostname: str | None,
) -> dict[str, object]:
    row = adapter.fetch_one(
        """
        insert into bots (
            bot_key,
            strategy_name,
            mode,
            status,
            hostname,
            last_seen_at,
            started_at,
            updated_at
        )
        values (
            %s,
            %s,
            %s::run_mode,
            'running'::strategy_status,
            %s,
            now(),
            now(),
            now()
        )
        on conflict (bot_key) do update
        set
            strategy_name = excluded.strategy_name,
            mode = excluded.mode,
            hostname = excluded.hostname,
            status = 'running'::strategy_status,
            last_seen_at = now(),
            started_at = coalesce(bots.started_at, now()),
            stopped_at = null,
            updated_at = now()
        returning id::text as bot_id
        """,
        (bot_key, strategy_name, mode, hostname),
    )
    if row is None:
        raise RuntimeError("failed to register bot")
    bot_id = str(row["bot_id"])
    adapter.fetch_one(
        """
        with latest_default as (
            select id
            from config_versions
            where config_scope = 'default'
            order by version_no desc, created_at desc
            limit 1
        )
        insert into bot_config_assignments (
            bot_id,
            config_version_id,
            applied,
            applied_at
        )
        select
            %s::uuid,
            latest_default.id,
            true,
            now()
        from latest_default
        where not exists (
            select 1
            from bot_config_assignments
            where bot_id = %s::uuid
        )
        returning id::text as assignment_id
        """,
        (bot_id, bot_id),
    )
    detail = get_bot_detail(adapter, bot_id)
    if detail is None:
        raise RuntimeError("registered bot could not be read back")
    return {
        "bot_id": bot_id,
        "assigned_config_version": detail.get("assigned_config_version"),
        "status": detail["status"],
    }


def record_heartbeat(
    adapter: PostgresDriverAdapter,
    *,
    bot_id: str,
    is_process_alive: bool,
    is_market_data_alive: bool,
    is_ordering_alive: bool,
    lag_ms: int | None,
    context: dict[str, object] | None,
) -> dict[str, object] | None:
    bot_uuid = uuid_or_none(bot_id)
    if bot_uuid is None or not bot_exists(adapter, bot_uuid):
        return None
    context_json_text = json.dumps(context or {}, separators=(",", ":"), ensure_ascii=True)
    row = adapter.fetch_one(
        """
        with heartbeat_insert as (
            insert into bot_heartbeats (
                bot_id,
                is_process_alive,
                is_market_data_alive,
                is_ordering_alive,
                lag_ms,
                payload
            )
            values (
                %s::uuid,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            returning bot_id, created_at
        )
        update bots
        set
            last_seen_at = (select created_at from heartbeat_insert),
            status = case
                when %s then 'running'::strategy_status
                else 'failed'::strategy_status
            end,
            started_at = case
                when %s then coalesce(started_at, (select created_at from heartbeat_insert))
                else started_at
            end,
            stopped_at = case
                when %s then null
                else coalesce(stopped_at, (select created_at from heartbeat_insert))
            end,
            updated_at = (select created_at from heartbeat_insert)
        where id = %s::uuid
        returning
            id::text as bot_id,
            status::text as status,
            (select created_at from heartbeat_insert) as recorded_at
        """,
        (
            bot_uuid,
            is_process_alive,
            is_market_data_alive,
            is_ordering_alive,
            lag_ms,
            context_json_text,
            is_process_alive,
            is_process_alive,
            is_process_alive,
            bot_uuid,
        ),
    )
    if row is None:
        return None
    return {
        "bot_id": row["bot_id"],
        "status": "created" if row["status"] == "pending" else row["status"],
        "recorded_at": iso_text(row.get("recorded_at")),
    }
