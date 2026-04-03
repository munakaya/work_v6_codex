create table market_snapshots (
    id bigserial primary key,
    exchange_name varchar(64) not null,
    market varchar(64) not null,
    best_bid numeric(36, 18) not null,
    best_ask numeric(36, 18) not null,
    bid_volume numeric(36, 18),
    ask_volume numeric(36, 18),
    source_type varchar(16) not null,
    exchange_timestamp timestamptz,
    received_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index idx_market_snapshots_exchange_market_received_at
    on market_snapshots (exchange_name, market, received_at desc);

create table balance_snapshots (
    id bigserial primary key,
    bot_id uuid references bots(id) on delete set null,
    exchange_name varchar(64) not null,
    asset varchar(32) not null,
    total numeric(36, 18) not null,
    available numeric(36, 18) not null,
    locked numeric(36, 18) not null,
    snapshot_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index idx_balance_snapshots_exchange_asset_snapshot_at
    on balance_snapshots (exchange_name, asset, snapshot_at desc);
