create table bot_heartbeats (
    id bigserial primary key,
    bot_id uuid not null references bots(id) on delete cascade,
    is_process_alive boolean not null,
    is_market_data_alive boolean not null,
    is_ordering_alive boolean not null,
    lag_ms integer,
    payload jsonb,
    created_at timestamptz not null default now()
);

create index idx_bot_heartbeats_bot_created_at
    on bot_heartbeats (bot_id, created_at desc);

create table positions (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid not null references bots(id) on delete cascade,
    exchange_name varchar(64) not null,
    market varchar(64) not null,
    base_asset varchar(32) not null,
    quote_asset varchar(32) not null,
    quantity numeric(36, 18) not null,
    avg_entry_price numeric(36, 18),
    mark_price numeric(36, 18),
    unrealized_pnl numeric(36, 18),
    snapshot_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index idx_positions_bot_snapshot_at
    on positions (bot_id, snapshot_at desc);

create table alert_events (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid references bots(id) on delete set null,
    level alert_level not null,
    code varchar(64) not null,
    message text not null,
    context jsonb,
    created_at timestamptz not null default now(),
    acknowledged_at timestamptz
);

create index idx_alert_events_level_created_at
    on alert_events (level, created_at desc);
