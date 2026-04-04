# Alembic and SQL Reference

이 문서는 Alembic initial migration SQL 초안을 별도 레퍼런스로 분리한 파일이다. 실제 migration 파일 작성 전 비교 기준으로 사용한다.


## 28. Alembic Initial Migration SQL 초안

이 섹션은 Alembic의 첫 migration에서 실제로 생성하게 될 SQL 초안이다.
목표는 "초기 운영에 필요한 최소 테이블을 안정적으로 올리는 것"이며, 이후 변경은 별도 revision으로 분리한다.

### 28.1 가정

- PostgreSQL 15+
- UUID 생성은 애플리케이션에서 하거나 `gen_random_uuid()` 사용 가능
- `pgcrypto` extension 사용 가능
- timezone은 UTC 기준

### 28.2 초기 revision 구성

초기 Alembic revision 이름 제안:

- `0001_initial_core_tables`
- `0002_market_and_balance_snapshots`
- `0003_order_flow`
- `0004_operations`

초기 구현 속도를 위해 단일 revision으로 시작할 수도 있지만, 운영상 검토와 롤백을 위해 4개로 나누는 편이 좋다.

### 28.3 SQL 초안

```sql
create extension if not exists pgcrypto;

create type run_mode as enum ('dry_run', 'shadow', 'live');
create type strategy_status as enum ('pending', 'running', 'stopped', 'failed', 'completed');
create type order_intent_status as enum ('created', 'submitted', 'cancelled', 'expired', 'rejected', 'simulated');
create type order_status as enum ('new', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired');
create type alert_level as enum ('info', 'warn', 'error', 'critical');

create table bots (
    id uuid primary key default gen_random_uuid(),
    bot_key varchar(64) not null unique,
    exchange_group varchar(64),
    strategy_name varchar(64) not null,
    mode run_mode not null,
    status strategy_status not null default 'pending',
    hostname varchar(255),
    started_at timestamptz,
    stopped_at timestamptz,
    last_seen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table config_versions (
    id uuid primary key default gen_random_uuid(),
    config_scope varchar(64) not null,
    version_no integer not null,
    config_json jsonb not null,
    checksum varchar(128) not null,
    created_by varchar(128),
    created_at timestamptz not null default now(),
    unique (config_scope, version_no)
);

create index idx_config_versions_scope_created_at
    on config_versions (config_scope, created_at desc);

create table bot_config_assignments (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid not null references bots(id) on delete cascade,
    config_version_id uuid not null references config_versions(id),
    applied boolean not null default false,
    applied_at timestamptz,
    created_at timestamptz not null default now()
);

create index idx_bot_config_assignments_bot_created_at
    on bot_config_assignments (bot_id, created_at desc);

create table strategy_runs (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid not null references bots(id) on delete cascade,
    strategy_name varchar(64) not null,
    mode run_mode not null,
    status strategy_status not null default 'pending',
    started_at timestamptz,
    ended_at timestamptz,
    reason text,
    created_at timestamptz not null default now()
);

create index idx_strategy_runs_bot_created_at
    on strategy_runs (bot_id, created_at desc);

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

-- decision_context jsonb minimum contract (documented convention)
-- {
--   "decision_id": "uuid",
--   "observed_at": "timestamptz",
--   "inputs": {
--     "quote_pair_id": "string",
--     "orderbook_age_ms": {"exchange": 120},
--     "clock_skew_ms": 60
--   },
--   "gate_checks": {...},
--   "computed": {
--     "executable_profit_quote": "123.45",
--     "executable_profit_bps": "8.12",
--     "unwind_buffer_quote": "10.00"
--   },
--   "reservation": {
--     "reservation_passed": true
--   },
--   "decision": {
--     "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND"
--   }
-- }

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
```

### 28.4 Alembic revision 역할 분리 메모

#### `0001_initial_core_tables`

- enum 생성
- `bots`
- `config_versions`
- `bot_config_assignments`
- `strategy_runs`

#### `0002_market_and_balance_snapshots`

- `market_snapshots`
- `balance_snapshots`

#### `0003_order_flow`

- `order_intents`
- `orders`
- `trade_fills`

#### `0004_operations`

- `bot_heartbeats`
- `positions`
- `alert_events`

### 28.5 주의사항

- `exchange_order_id`는 거래소별 중복 가능성이 있으므로 `exchange_name`과 합쳐 unique 처리
- `market_snapshots`는 장기 누적 시 데이터가 빠르게 커지므로 retention 정책 필요
- `balance_snapshots`, `market_snapshots`, `bot_heartbeats`는 파티셔닝 후보
- enum 변경 가능성이 있으면 초기부터 migration 전략을 엄격히 가져가야 함
