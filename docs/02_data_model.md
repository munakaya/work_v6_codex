# Data Model and Storage Design

이 문서는 PostgreSQL, Redis, migration 정책을 포함한 저장 모델 기준서다. 스키마와 이벤트 저장 규약 변경은 이 문서를 먼저 갱신한다.


## 15. 초기 DB 스키마 초안

### 15.1 저장소 원칙

- PostgreSQL은 권위 있는 영속 저장소다.
- Redis는 hot state, distributed lock, event stream 용도다.
- 전체 orderbook raw payload는 PostgreSQL에 무조건 쌓지 않는다.
- 초기 버전에서는 top-of-book 또는 요약 snapshot만 DB에 저장한다.

### 15.2 핵심 테이블 목록

- `bots`
- `config_versions`
- `bot_config_assignments`
- `strategy_runs`
- `bot_heartbeats`
- `market_snapshots`
- `balance_snapshots`
- `order_intents`
- `orders`
- `trade_fills`
- `positions`
- `alert_events`

### 15.3 권장 enum

```sql
create type run_mode as enum ('dry_run', 'shadow', 'live');
create type strategy_status as enum ('pending', 'running', 'stopped', 'failed', 'completed');
create type order_intent_status as enum ('created', 'submitted', 'cancelled', 'expired', 'rejected', 'simulated');
create type order_status as enum ('new', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired');
create type alert_level as enum ('info', 'warn', 'error', 'critical');
```

### 15.4 테이블 초안

```sql
create table bots (
    id uuid primary key,
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
    id uuid primary key,
    config_scope varchar(64) not null,
    version_no integer not null,
    config_json jsonb not null,
    checksum varchar(128) not null,
    created_by varchar(128),
    created_at timestamptz not null default now(),
    unique (config_scope, version_no)
);

create table bot_config_assignments (
    id uuid primary key,
    bot_id uuid not null references bots(id),
    config_version_id uuid not null references config_versions(id),
    applied boolean not null default false,
    applied_at timestamptz,
    created_at timestamptz not null default now()
);

create table strategy_runs (
    id uuid primary key,
    bot_id uuid not null references bots(id),
    strategy_name varchar(64) not null,
    mode run_mode not null,
    status strategy_status not null default 'pending',
    started_at timestamptz,
    ended_at timestamptz,
    reason text,
    created_at timestamptz not null default now()
);

create table bot_heartbeats (
    id bigserial primary key,
    bot_id uuid not null references bots(id),
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
    bot_id uuid references bots(id),
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
    id uuid primary key,
    strategy_run_id uuid not null references strategy_runs(id),
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

create table orders (
    id uuid primary key,
    order_intent_id uuid references order_intents(id),
    bot_id uuid references bots(id),
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

create index idx_orders_exchange_order_id
    on orders (exchange_name, exchange_order_id);

create table trade_fills (
    id uuid primary key,
    order_id uuid not null references orders(id),
    exchange_trade_id varchar(128),
    fill_price numeric(36, 18) not null,
    fill_qty numeric(36, 18) not null,
    fee_asset varchar(32),
    fee_amount numeric(36, 18),
    filled_at timestamptz not null,
    created_at timestamptz not null default now()
);

create table positions (
    id uuid primary key,
    bot_id uuid not null references bots(id),
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

create table alert_events (
    id uuid primary key,
    bot_id uuid references bots(id),
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

### 15.5 Redis 사용 초안

Redis에는 아래만 둔다.

- 최신 bot state cache
- latest orderbook top cache
- distributed lock
- idempotency / dedup key
- strategy event stream

예시 키 규약:

- `bot:{bot_key}:state`
- `market:orderbook_top:{exchange}:{market}`
- `lock:order_intent:{intent_id}`
- `stream:strategy_events`

### 15.6 스키마 설계 메모

- `market_snapshots`는 초기에는 top-of-book만 저장한다.
- full orderbook raw frame은 장기 보관 대상이 아니면 Redis TTL 또는 object storage로 분리한다.
- `order_intents`와 `orders`를 분리해야 dry-run / shadow / live를 공통 모델로 처리할 수 있다.
- `bot_heartbeats`는 운영 분석과 장애 추적 때문에 시계열로 적재한다.
- `config_versions`를 둬야 전략 실행과 설정 반영 이력을 재현할 수 있다.

## 19. Redis Key / Stream 규약 초안

Redis는 권위 있는 저장소가 아니라 hot state와 이벤트 백본 용도다.
초기 버전에서는 key naming, TTL, stream consumer group 규칙을 먼저 고정해야 한다.

### 19.1 Key naming 규칙

- 단수보다 역할 중심 prefix 사용
- 환경 prefix를 붙일 수 있어야 함
- key 조합 순서는 `domain:identifier:subresource`

예시:

- `bot:{bot_key}:state`
- `bot:{bot_key}:lock`
- `market:orderbook_top:{exchange}:{market}`
- `strategy_run:{run_id}:state`
- `config:{scope}:latest`
- `dedup:order_intent:{intent_id}`

### 19.2 권장 key 목록

#### Bot state

- `bot:{bot_key}:state`
  - 현재 bot 최신 상태
  - JSON payload
  - TTL 예: 120초

#### Latest market top

- `market:orderbook_top:{exchange}:{market}`
  - 최신 top-of-book
  - JSON payload
  - TTL 예: 15초

#### Strategy state

- `strategy_run:{run_id}:state`
  - strategy run 최신 상태
  - TTL 없음 또는 장시간 TTL

#### Locks

- `lock:order_intent:{intent_id}`
- `lock:bot:{bot_key}:command`

#### Dedup

- `dedup:order_intent:{intent_id}`
- `dedup:exchange_order:{exchange}:{exchange_order_id}`

### 19.3 Stream 규약

초기 stream은 너무 많지 않게 시작한다.

권장 stream:

- `stream:bot_events`
- `stream:market_events`
- `stream:strategy_events`
- `stream:order_events`
- `stream:alert_events`

권장 consumer group:

- `cg:control_plane`
- `cg:strategy_workers`
- `cg:alert_dispatcher`

### 19.4 Event envelope 초안

모든 stream event는 공통 envelope를 가진다.

```json
{
  "event_id": "evt_01",
  "event_type": "order_intent.created",
  "event_version": 1,
  "occurred_at": "2026-04-03T14:12:00Z",
  "producer": "strategy-worker",
  "trace_id": "trc_123",
  "payload": {
    "order_intent_id": "uuid",
    "bot_id": "uuid"
  }
}
```

### 19.5 TTL 초안

- `bot:{bot_key}:state`: 120초
- `market:{exchange}:{market}:top`: 5초
- `dedup:*`: 10분~1시간
- `lock:*`: 수 초~수십 초

### 19.6 Redis 사용 금지 항목

초기 버전에서는 아래를 Redis에 장기 저장하지 않는다.

- 전체 주문 이력
- 전체 체결 이력
- 장기 snapshot history
- full orderbook archive

이런 데이터는 PostgreSQL 또는 별도 object storage에 둔다.

## 20. 초기 Migration 정책

초기 버전부터 migration 운영 규칙을 세워야 이후 스키마 변경이 덜 위험하다.

### 20.1 도구

- Alembic 사용
- SQLAlchemy model과 migration은 분리 관리
- auto-generate 결과는 그대로 쓰지 않고 수동 검토

### 20.2 규칙

- migration 파일은 불변으로 취급
- 운영 반영된 migration은 rewrite 금지
- destructive change는 2-step migration으로 처리
- enum 변경은 별도 검토 절차 포함

### 20.3 권장 절차

1. schema 변경 PR 작성
2. SQLAlchemy model 수정
3. Alembic revision 생성
4. migration SQL 검토
5. local/staging 적용
6. rollback 시나리오 확인
7. production 반영

### 20.4 destructive change 원칙

예:

- 컬럼 삭제
- not null 추가
- enum 값 제거
- 테이블 분해/병합

이런 변경은 다음 순서를 따른다.

1. 새 컬럼/새 테이블 추가
2. dual write 또는 backfill
3. 읽기 경로 전환
4. 검증 완료 후 구 컬럼 제거

### 20.5 초기 migration 묶음

초기 버전에서는 다음 revision 단위로 나누는 것이 좋다.

- `0001_initial_core_tables`
  - bots
  - config_versions
  - bot_config_assignments
  - strategy_runs
- `0002_market_and_balance_snapshots`
  - market_snapshots
  - balance_snapshots
- `0003_order_flow`
  - order_intents
  - orders
  - trade_fills
- `0004_operations`
  - bot_heartbeats
  - alert_events
  - positions

### 20.6 rollback 원칙

- schema rollback보다 feature flag 차단을 우선 고려
- DB rollback은 데이터 손실 위험이 있는 경우 매우 제한적으로 수행
- 운영 중 문제 발생 시 애플리케이션 read/write path 차단이 1차 대응
