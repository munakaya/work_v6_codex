create table order_intents (
    id uuid primary key default gen_random_uuid(),
    strategy_run_id uuid not null references strategy_runs(id) on delete cascade,
    market varchar(64) not null,
    buy_exchange varchar(64) not null,
    sell_exchange varchar(64) not null,
    side_pair varchar(32) not null,
    target_qty numeric(36, 18) not null,
    expected_profit numeric(36, 18),
    expected_profit_ratio numeric(18, 8),
    status order_intent_status not null default 'created',
    decision_context jsonb,
    created_at timestamptz not null default now()
);

create index idx_order_intents_strategy_run_created_at
    on order_intents (strategy_run_id, created_at desc);

create table orders (
    id uuid primary key default gen_random_uuid(),
    order_intent_id uuid references order_intents(id) on delete set null,
    bot_id uuid references bots(id) on delete set null,
    exchange_name varchar(64) not null,
    exchange_order_id varchar(128),
    market varchar(64) not null,
    side varchar(8) not null,
    price numeric(36, 18),
    quantity numeric(36, 18) not null,
    status order_status not null,
    submitted_at timestamptz,
    updated_at timestamptz not null default now(),
    raw_payload jsonb
);

create unique index uq_orders_exchange_order_id
    on orders (exchange_name, exchange_order_id)
    where exchange_order_id is not null;

create index idx_orders_bot_updated_at
    on orders (bot_id, updated_at desc);

create table trade_fills (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references orders(id) on delete cascade,
    exchange_trade_id varchar(128),
    fill_price numeric(36, 18) not null,
    fill_qty numeric(36, 18) not null,
    fee_asset varchar(32),
    fee_amount numeric(36, 18),
    filled_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index idx_trade_fills_order_filled_at
    on trade_fills (order_id, filled_at desc);
