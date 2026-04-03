# Trading Platform PRD

## 1. 문서 목적

이 문서는 기존 `work_v4` 코드베이스를 직접 수정하기 위한 문서가 아니다.  
이 문서는 기존 운영 경험에서 검증된 요구사항을 바탕으로, 새 자동매매 플랫폼을 처음부터 설계하고 구현하기 위한 PRD(Product Requirements Document)다.

핵심 목표는 다음과 같다.

- 봇 스크립트 묶음이 아니라 운영 가능한 트레이딩 플랫폼을 만든다.
- 전략, 거래소 연결, 상태 저장, 운영 관제를 명확히 분리한다.
- dry-run, shadow, live 실행 모드를 처음부터 제품 개념으로 포함한다.
- 파일 기반 운영이 아니라 DB, 이벤트, 관측성 중심 구조로 설계한다.

## 2. 배경

기존 시스템에서 확인된 운영 현실은 다음과 같다.

- 주문장 freshness가 실제 수익성과 안정성에 직접 영향을 준다.
- 단순 프로세스 생존 여부만으로는 정상 동작을 판단할 수 없다.
- 주문 후 잔고 및 체결 상태 재검증이 반드시 필요하다.
- 운영자가 즉시 볼 수 있는 상태 조회와 알림 체계가 필요하다.
- 설정 변경, 전략 중지, 재시작 같은 운영 개입은 시스템 기본 기능이어야 한다.

따라서 새 프로젝트는 "거래소 API를 호출하는 스크립트"가 아니라, "전략 실행 + 상태 저장 + 운영 제어 + 관측성"을 갖춘 시스템으로 설계해야 한다.

## 3. 제품 비전

새 프로젝트의 비전은 다음과 같다.

여러 거래소에 대해 공통된 방식으로 시장 데이터를 수집하고, 전략 워커가 이를 바탕으로 주문 의도를 생성하며, Control Plane이 상태/설정/운영 관제를 담당하는 이벤트 기반 트레이딩 플랫폼을 만든다.

이 플랫폼은 다음 특성을 가져야 한다.

- 거래소 추가가 쉽다.
- 전략 추가가 쉽다.
- 운영자가 시스템 상태를 즉시 파악할 수 있다.
- 실주문 전 dry-run과 shadow 검증이 가능하다.
- 장애와 오작동을 빨리 감지할 수 있다.

## 4. 목표

### 4.1 제품 목표

- 차익거래 전략 1개를 안정적으로 운영 가능한 수준으로 구현한다.
- 2~3개 거래소에 대해 공통 어댑터 구조를 제공한다.
- Control Plane을 통해 봇 상태, 설정 버전, 주문 이력, 알림 이벤트를 조회할 수 있어야 한다.
- 운영 중 실주문과 비실주문 모드를 안전하게 전환할 수 있어야 한다.

### 4.2 기술 목표

- Python 3.12 기반 비동기 아키텍처
- FastAPI 기반 Control Plane
- PostgreSQL 기반 영속 저장
- Redis 기반 hot state / event backbone
- 구조화 로그 + metrics + alert hook 기본 제공

### 4.3 운영 목표

- health check, heartbeat, alert가 제품 기본 기능일 것
- 운영자가 재시작/중지/설정 반영 상태를 확인할 수 있을 것
- 주문 실패, 응답 지연, stale data 증가 같은 운영 이슈를 관측 가능할 것

## 5. 비목표

초기 버전에서 아래는 목표가 아니다.

- 10개 이상의 거래소 동시 지원
- 다양한 전략 동시 제공
- 복잡한 웹 프론트엔드
- 완성형 백테스트 플랫폼
- 멀티 테넌트 SaaS 구조
- Kubernetes 전제 배포

초기 버전은 "기능 수"보다 "실행 품질과 운영 가능성"에 집중한다.

## 6. 핵심 사용자

### 6.1 운영자

시스템을 실제로 실행하고 상태를 확인하며, 설정을 바꾸고, 장애 시 개입하는 사용자다.

운영자가 원하는 것:

- 현재 어떤 봇이 살아있는지
- 어떤 전략이 어떤 설정 버전으로 동작 중인지
- 주문이 정상적으로 발생했는지
- 이상 상황이 발생했는지
- 즉시 중지할 수 있는지

### 6.2 전략 개발자

전략 로직과 리스크 규칙을 작성하는 사용자다.

전략 개발자가 원하는 것:

- 거래소 세부 구현을 몰라도 전략 작성 가능
- dry-run / shadow로 안전하게 검증 가능
- 입력 데이터와 실행 결과를 재현 가능
- 공통 도메인 모델을 재사용 가능

### 6.3 플랫폼 개발자

거래소 어댑터, 저장소, Control Plane, 알림, 배포를 구현하는 사용자다.

플랫폼 개발자가 원하는 것:

- 명확한 계층 경계
- 테스트 가능한 구조
- 모듈 간 계약이 분명한 인터페이스
- 운영 문제를 진단 가능한 로그/메트릭

## 7. 제품 원칙

### 7.1 운영 경험에서 반드시 계승할 규칙

- 주문장 freshness를 엄격하게 검사한다.
- 잔고 최신성과 주문장 최신성을 분리해서 본다.
- keep-alive는 프로세스 생존과 기능 생존을 구분해서 본다.
- 주문 후 반드시 체결/잔고를 재검증한다.
- 설정은 버전 관리 가능해야 한다.
- 운영자 관제와 알림은 선택 기능이 아니라 기본 기능이다.
- dry-run, shadow, live 실행 모드를 시스템 개념으로 명시한다.

### 7.2 설계 원칙

- 전략과 인프라를 분리한다.
- 읽기 모델과 쓰기 모델을 분리한다.
- 외부 시스템 연결은 어댑터 계층으로 격리한다.
- 파일 저장이 아니라 상태 모델과 이벤트 모델을 우선 정의한다.
- 모든 핵심 동작은 로그와 메트릭으로 관측 가능해야 한다.

## 8. 권장 기술 스택

### 8.1 애플리케이션

- Python 3.12
- FastAPI
- Pydantic v2
- asyncio

### 8.2 데이터 및 이벤트

- PostgreSQL
- Redis
- Redis Streams 또는 NATS
- SQLAlchemy 2
- Alembic

### 8.3 운영

- Docker Compose
- Prometheus
- Grafana
- JSON structured logging
- Telegram 또는 Slack notifier

## 9. 목표 아키텍처

```text
┌─────────────────────────────────────────────────────────────┐
│                    Control Plane (FastAPI)                 │
│ bot registry · config service · admin API · read models    │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
                │ command/event           │ query
                │                         │
        ┌───────▼─────────────────────────▼────────┐
        │          Event / State Backbone           │
        │ Redis Streams or NATS · Redis Cache       │
        └───────┬─────────────────────────┬────────┘
                │                         │
        ┌───────▼────────┐       ┌────────▼────────┐
        │ Strategy Worker │ ...  │ Strategy Worker │
        │ Python asyncio  │      │ Python asyncio  │
        │ arbitrage       │      │ market_making   │
        └───────┬────────┘       └────────┬────────┘
                │                          │
                └──────────────┬───────────┘
                               │
                     ┌─────────▼─────────┐
                     │ Exchange Adapters │
                     │ REST · WS · auth  │
                     └─────────┬─────────┘
                               │
                     ┌─────────▼─────────┐
                     │    Exchanges      │
                     └───────────────────┘

부가 계층
- PostgreSQL: orders / fills / snapshots / configs / bot states
- Redis: hot state / event stream / locks
- Notifier: Telegram / Slack
- Metrics: Prometheus / Grafana
```

## 10. 권장 디렉터리 구조

```text
platform/
├── apps/
│   ├── control_plane/
│   ├── worker_strategy/
│   └── backoffice/
├── core/
│   ├── bus/
│   ├── config/
│   ├── logging/
│   ├── metrics/
│   ├── throttling/
│   ├── time/
│   └── utils/
├── domain/
│   ├── bots/
│   ├── balances/
│   ├── orderbooks/
│   ├── orders/
│   ├── trades/
│   └── positions/
├── connectors/
│   ├── exchanges/
│   ├── notification/
│   └── storage/
├── strategies/
│   ├── arbitrage/
│   ├── market_making/
│   ├── funding/
│   └── shared/
├── repositories/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── deploy/
├── configs/
│   ├── templates/
│   ├── local/
│   ├── staging/
│   └── production/
└── docs/
```

## 11. 기능 요구사항

### 11.1 Control Plane

필수 기능:

- bot registry
- config version 관리
- bot 상태 조회 API
- 전략 실행 상태 조회 API
- 주문/체결 조회 API
- alert event 조회 API
- 운영 명령 API
  - start strategy
  - stop strategy
  - restart worker
  - apply config version

### 11.2 Strategy Worker

필수 기능:

- 시장 데이터 수신
- 전략 조건 평가
- OrderIntent 생성
- dry-run / shadow / live 실행 모드 지원
- 주문 후 체결/잔고 재검증
- heartbeat 전송
- structured log 발행

### 11.3 Exchange Adapter

거래소별 최소 계약:

- public orderbook REST
- public orderbook WS
- private balance
- private place order
- private order status
- rate limit 처리
- 오류 분류 및 재시도 정책

### 11.4 운영 인터페이스

필수 기능:

- alert hook
- heartbeat monitor
- stale data monitor
- order failure alert
- config apply result tracking

### 11.5 실행 모드

시스템은 아래 세 모드를 지원해야 한다.

- `dry-run`: 주문 의도만 계산, 외부 주문 호출 없음
- `shadow`: 주문 의도와 결과 추정 기록, 실주문 없음
- `live`: 실제 주문 실행

## 12. 비기능 요구사항

### 12.1 안정성

- 봇 heartbeat 누락 감지
- stale orderbook 감지
- 주문 실패 시 재시도 정책
- worker 단위 재시작 가능

### 12.2 관측성

- JSON structured logs
- bot, strategy, exchange 단위 metrics
- health endpoint
- alert hooks

### 12.3 보안

- 비밀정보는 저장소에 포함하지 않음
- 설정 템플릿과 실제 설정 분리
- API key / secret / token 암호화 또는 외부 secret source 사용

### 12.4 테스트 가능성

- 단위 테스트: 도메인, 전략 계산, 저장소 계약
- 통합 테스트: 거래소 mock, DB, Redis, API
- e2e 테스트: dry-run / shadow 흐름

## 13. MVP 범위

초기 버전은 아래 범위로 제한한다.

- FastAPI Control Plane 1개
- PostgreSQL 1개
- Redis 1개
- 거래소 어댑터 2~3개
- 차익거래 전략 1개
- dry-run + shadow + live 모드
- Telegram 알림
- 최소 운영 조회 API

## 14. 새 프로젝트 구현 순서

### Step 1. 도메인과 스키마 확정

- 핵심 엔티티 정의
- API 스키마 정의
- 이벤트 스키마 정의
- DB 테이블 초안 정의

### Step 2. Control Plane 구현

- health check
- bot registry
- config service
- status read API
- alert webhook endpoint

### Step 3. 저장소와 이벤트 백본 구현

- PostgreSQL schema
- Redis key / stream 규약
- repositories
- config version persistence

### Step 4. 거래소 어댑터 구현

MVP에서는 거래소 2~3개만 구현한다.

### Step 5. 전략 엔진 MVP 구현

- 차익거래 전략 1개
- freshness 검사
- min profit 검사
- OrderIntent 생성

### Step 6. Shadow Mode 검증

- 실주문 없이 판단 품질 검증
- alert / report / state 관찰

### Step 7. 제한된 Live Mode 전환

- 한 전략
- 한 코인 또는 소수 코인
- 낮은 볼륨
- 강한 안전장치

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
- `market:{exchange}:{market}:top`
- `lock:order_intent:{intent_id}`
- `stream:strategy_events`

### 15.6 스키마 설계 메모

- `market_snapshots`는 초기에는 top-of-book만 저장한다.
- full orderbook raw frame은 장기 보관 대상이 아니면 Redis TTL 또는 object storage로 분리한다.
- `order_intents`와 `orders`를 분리해야 dry-run / shadow / live를 공통 모델로 처리할 수 있다.
- `bot_heartbeats`는 운영 분석과 장애 추적 때문에 시계열로 적재한다.
- `config_versions`를 둬야 전략 실행과 설정 반영 이력을 재현할 수 있다.

## 16. 성공 기준

초기 버전 성공 기준은 다음과 같다.

- 운영자가 Control Plane에서 봇 상태와 주문 이력을 볼 수 있다.
- dry-run과 shadow 모드에서 전략 의사결정이 기록된다.
- live 모드에서 제한된 전략이 안전하게 실행된다.
- 주문 실패, stale data, heartbeat 이상이 알림으로 전달된다.
- 전략, 거래소, 저장소, 알림 계층이 명확히 분리돼 테스트 가능하다.

## 17. 결론

새 프로젝트의 본질은 봇 스크립트 집합이 아니다.

최종적으로 만들고 싶은 것은 다음이다.

- 전략이 명확히 분리된 트레이딩 엔진
- 거래소 추가가 쉬운 어댑터 구조
- 읽기 모델과 운영 모델이 분리된 Control Plane
- DB 기반의 조회 가능 이력
- dry-run, shadow, live 전환이 가능한 실행 모델
- 관측 가능하고 테스트 가능한 운영 플랫폼

즉, 새 프로젝트는 "자동매매 코드"가 아니라 "트레이딩 운영 시스템"이어야 한다.

## 18. API 명세 초안

초기 버전의 API는 "Control Plane 우선" 원칙을 따른다.  
즉, 주문 실행 API보다 상태 조회, 설정 배포, 운영 명령 API를 먼저 안정화한다.

### 18.1 공통 규칙

- 모든 API는 `/api/v1` prefix 사용
- 응답은 `success`, `data`, `error` 형태를 기본으로 함
- `request_id`를 응답 헤더 또는 body에 포함
- 시간 필드는 `ISO 8601 UTC` 문자열 사용
- 운영 명령 API는 비동기 처리 기준으로 `accepted` 상태를 반환 가능

응답 예시:

```json
{
  "success": true,
  "data": {
    "bot_id": "9d0f9b5d-8f1d-4fe0-bd90-5b7bcb3b4e21"
  },
  "error": null
}
```

에러 예시:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "BOT_NOT_FOUND",
    "message": "bot_id not found"
  }
}
```

### 18.2 Health API

#### `GET /api/v1/health`

목적:

- Control Plane 프로세스 생존 여부 확인

응답 예시:

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "service": "control-plane",
    "version": "0.1.0"
  },
  "error": null
}
```

#### `GET /api/v1/ready`

목적:

- PostgreSQL, Redis 연결 포함 준비 상태 확인

### 18.3 Bot API

#### `POST /api/v1/bots/register`

목적:

- worker 또는 bot instance가 자신을 등록

요청 예시:

```json
{
  "bot_key": "arb-upbit-bithumb-001",
  "strategy_name": "arbitrage",
  "mode": "shadow",
  "hostname": "trade-host-01"
}
```

응답 핵심 필드:

- `bot_id`
- `assigned_config_version`
- `status`

#### `GET /api/v1/bots`

목적:

- bot 목록 조회

필터 예시:

- `status`
- `strategy_name`
- `mode`

#### `GET /api/v1/bots/{bot_id}`

목적:

- bot 상세 상태 조회

응답 핵심 필드:

- bot 기본 정보
- latest heartbeat
- assigned config
- latest strategy run

### 18.4 Heartbeat API

#### `POST /api/v1/bots/{bot_id}/heartbeat`

목적:

- bot 상태와 기능 생존 신호 보고

요청 예시:

```json
{
  "is_process_alive": true,
  "is_market_data_alive": true,
  "is_ordering_alive": true,
  "lag_ms": 240,
  "context": {
    "orderbook_stale_count": 0,
    "balance_refresh_age_ms": 1800
  }
}
```

### 18.5 Config API

#### `POST /api/v1/configs`

목적:

- 새 config version 생성

핵심 필드:

- `config_scope`
- `config_json`
- `checksum`

#### `GET /api/v1/configs/{config_scope}/latest`

목적:

- scope 기준 최신 config 조회

#### `POST /api/v1/bots/{bot_id}/assign-config`

목적:

- bot에 특정 config version 할당

### 18.6 Strategy Run API

#### `POST /api/v1/strategy-runs`

목적:

- strategy run 생성

#### `POST /api/v1/strategy-runs/{run_id}/start`

목적:

- 특정 strategy run 시작 명령

#### `POST /api/v1/strategy-runs/{run_id}/stop`

목적:

- 특정 strategy run 정지 명령

#### `GET /api/v1/strategy-runs/{run_id}`

목적:

- strategy run 상태 조회

### 18.7 Orders / Fills API

#### `GET /api/v1/order-intents`

목적:

- dry-run, shadow, live 전반의 의사결정 기록 조회

필터 예시:

- `bot_id`
- `strategy_run_id`
- `status`
- `market`

#### `GET /api/v1/orders`

목적:

- 실제 주문 이력 조회

#### `GET /api/v1/orders/{order_id}`

목적:

- 단일 주문 및 체결 상세 조회

#### `GET /api/v1/fills`

목적:

- 체결 이력 조회

### 18.8 Alerts API

#### `GET /api/v1/alerts`

목적:

- alert event 목록 조회

#### `POST /api/v1/alerts/{alert_id}/ack`

목적:

- 운영자가 alert 확인 처리

### 18.9 Metrics API

#### `GET /metrics`

목적:

- Prometheus scraping endpoint 제공

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
- `market:{exchange}:{market}:top`
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

- `market:{exchange}:{market}:top`
  - 최신 top-of-book
  - JSON payload
  - TTL 예: 5초

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

## 21. OpenAPI 초안

아래는 초기 버전 Control Plane의 OpenAPI 초안이다.  
정식 OpenAPI YAML을 바로 작성하기 전에, 구현 팀이 빠르게 인터페이스를 합의할 수 있도록 최소 계약 중심으로 정리한다.

### 21.1 공통 컴포넌트 스키마

#### `BotSummary`

```json
{
  "id": "uuid",
  "bot_key": "arb-upbit-bithumb-001",
  "strategy_name": "arbitrage",
  "mode": "shadow",
  "status": "running",
  "hostname": "trade-host-01",
  "last_seen_at": "2026-04-03T14:12:00Z"
}
```

#### `HeartbeatPayload`

```json
{
  "is_process_alive": true,
  "is_market_data_alive": true,
  "is_ordering_alive": true,
  "lag_ms": 240,
  "context": {
    "orderbook_stale_count": 0,
    "balance_refresh_age_ms": 1800
  }
}
```

#### `ConfigVersionSummary`

```json
{
  "id": "uuid",
  "config_scope": "arbitrage.default",
  "version_no": 3,
  "checksum": "sha256:...",
  "created_at": "2026-04-03T14:10:00Z"
}
```

#### `OrderIntentSummary`

```json
{
  "id": "uuid",
  "strategy_run_id": "uuid",
  "market": "XRP-KRW",
  "buy_exchange": "upbit",
  "sell_exchange": "bithumb",
  "target_qty": "120.5",
  "expected_profit": "14320.11",
  "status": "created",
  "created_at": "2026-04-03T14:13:00Z"
}
```

#### `AlertEventSummary`

```json
{
  "id": "uuid",
  "bot_id": "uuid",
  "level": "warn",
  "code": "ORDERBOOK_STALE",
  "message": "orderbook stale count exceeded threshold",
  "created_at": "2026-04-03T14:13:22Z",
  "acknowledged_at": null
}
```

### 21.2 핵심 엔드포인트 목록

#### Health

- `GET /api/v1/health`
- `GET /api/v1/ready`

#### Bots

- `POST /api/v1/bots/register`
- `GET /api/v1/bots`
- `GET /api/v1/bots/{bot_id}`
- `POST /api/v1/bots/{bot_id}/heartbeat`
- `POST /api/v1/bots/{bot_id}/assign-config`

#### Configs

- `POST /api/v1/configs`
- `GET /api/v1/configs/{config_scope}/latest`
- `GET /api/v1/configs/{config_scope}/versions`

#### Strategy Runs

- `POST /api/v1/strategy-runs`
- `GET /api/v1/strategy-runs`
- `GET /api/v1/strategy-runs/{run_id}`
- `POST /api/v1/strategy-runs/{run_id}/start`
- `POST /api/v1/strategy-runs/{run_id}/stop`

#### Orders and Fills

- `GET /api/v1/order-intents`
- `GET /api/v1/order-intents/{intent_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{order_id}`
- `GET /api/v1/fills`

#### Alerts

- `GET /api/v1/alerts`
- `GET /api/v1/alerts/{alert_id}`
- `POST /api/v1/alerts/{alert_id}/ack`

### 21.3 엔드포인트별 핵심 계약

#### `POST /api/v1/bots/register`

요청:

```json
{
  "bot_key": "arb-upbit-bithumb-001",
  "strategy_name": "arbitrage",
  "mode": "shadow",
  "hostname": "trade-host-01"
}
```

응답:

```json
{
  "success": true,
  "data": {
    "bot": {
      "id": "uuid",
      "bot_key": "arb-upbit-bithumb-001",
      "strategy_name": "arbitrage",
      "mode": "shadow",
      "status": "pending"
    },
    "assigned_config": {
      "id": "uuid",
      "config_scope": "arbitrage.default",
      "version_no": 1
    }
  },
  "error": null
}
```

#### `POST /api/v1/bots/{bot_id}/heartbeat`

요청:

```json
{
  "is_process_alive": true,
  "is_market_data_alive": true,
  "is_ordering_alive": true,
  "lag_ms": 240,
  "context": {
    "orderbook_stale_count": 0
  }
}
```

응답:

```json
{
  "success": true,
  "data": {
    "accepted": true,
    "server_time": "2026-04-03T14:12:03Z"
  },
  "error": null
}
```

#### `POST /api/v1/configs`

요청:

```json
{
  "config_scope": "arbitrage.default",
  "config_json": {
    "min_profit": 1000,
    "max_order_notional": 500000
  }
}
```

#### `POST /api/v1/strategy-runs`

요청:

```json
{
  "bot_id": "uuid",
  "strategy_name": "arbitrage",
  "mode": "shadow"
}
```

#### `GET /api/v1/order-intents`

쿼리 파라미터 예시:

- `bot_id`
- `strategy_run_id`
- `market`
- `status`
- `created_from`
- `created_to`

### 21.4 상태 코드 원칙

- `200`: 정상 조회/처리
- `202`: 비동기 명령 접수
- `400`: 잘못된 요청
- `404`: 리소스 없음
- `409`: 상태 충돌
- `422`: 도메인 검증 실패
- `500`: 서버 내부 오류

### 21.5 인증 초안

초기 버전에서는 내부 운영망 기준으로 간단히 시작할 수 있지만, 최소한 아래 두 단계는 열어둔다.

- 1단계: 내부망 + static admin token
- 2단계: service-to-service token 또는 mTLS

## 22. Strategy Decision Record Format

전략 품질을 검증하고 shadow/live 비교를 가능하게 하려면, 주문 결과뿐 아니라 "왜 주문하려 했는지"를 기록해야 한다.  
이를 위해 `Strategy Decision Record`를 별도 포맷으로 정의한다.

### 22.1 목적

- 전략 판단 근거 기록
- dry-run / shadow / live 결과 비교
- 사후 분석과 튜닝 근거 확보
- 재현 가능한 디버깅 데이터 확보

### 22.2 필수 필드

```json
{
  "decision_id": "uuid",
  "strategy_run_id": "uuid",
  "bot_id": "uuid",
  "mode": "shadow",
  "strategy_name": "arbitrage",
  "market": "XRP-KRW",
  "buy_exchange": "upbit",
  "sell_exchange": "bithumb",
  "observed_at": "2026-04-03T14:13:00Z",
  "inputs": {
    "best_bid_sell_exchange": "1023.2",
    "best_ask_buy_exchange": "1018.4",
    "balance_buy_exchange_quote": "1200000",
    "balance_sell_exchange_base": "1500",
    "orderbook_age_ms": {
      "upbit": 120,
      "bithumb": 180
    }
  },
  "constraints": {
    "min_profit": "1000",
    "max_order_notional": "500000",
    "max_order_age_ms": 1000
  },
  "computed": {
    "target_qty": "120.5",
    "expected_profit": "14320.11",
    "expected_profit_ratio": "0.0121",
    "freshness_passed": true,
    "balance_passed": true,
    "risk_passed": true
  },
  "decision": {
    "action": "create_order_intent",
    "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
    "reason_message": "profit and freshness conditions satisfied"
  }
}
```

### 22.3 reason_code 초안

- `ARBITRAGE_OPPORTUNITY_FOUND`
- `ORDERBOOK_STALE`
- `BALANCE_INSUFFICIENT`
- `PROFIT_TOO_LOW`
- `RISK_LIMIT_BLOCKED`
- `CONFIG_DISABLED`
- `DUPLICATE_INTENT_BLOCKED`

### 22.4 저장 위치

- 운영 분석용: PostgreSQL `order_intents.decision_context`
- 실시간 디버깅용: structured log
- 필요 시 object storage에 raw decision archive 저장 가능

## 23. Observability Spec

새 프로젝트는 처음부터 관측 가능해야 한다.  
즉, 로그와 메트릭은 나중에 붙이는 것이 아니라 제품 핵심 요구사항이다.

### 23.1 로그 규칙

모든 핵심 로그는 JSON structured logging으로 출력한다.

필수 공통 필드:

- `timestamp`
- `level`
- `service`
- `module`
- `event_name`
- `bot_id`
- `strategy_run_id`
- `trace_id`
- `message`

예시:

```json
{
  "timestamp": "2026-04-03T14:13:00Z",
  "level": "INFO",
  "service": "strategy-worker",
  "module": "arbitrage_engine",
  "event_name": "order_intent_created",
  "bot_id": "uuid",
  "strategy_run_id": "uuid",
  "trace_id": "trc_123",
  "message": "arbitrage opportunity accepted"
}
```

### 23.2 메트릭 초안

#### Control Plane

- `control_plane_http_requests_total`
- `control_plane_http_request_duration_seconds`
- `control_plane_active_bots`
- `control_plane_active_strategy_runs`

#### Strategy Worker

- `strategy_decisions_total`
- `strategy_decisions_rejected_total`
- `strategy_order_intents_total`
- `strategy_shadow_orders_total`
- `strategy_live_orders_total`
- `strategy_decision_duration_seconds`

#### Market Data

- `market_orderbook_updates_total`
- `market_orderbook_stale_total`
- `market_orderbook_age_ms`
- `market_ws_reconnects_total`

#### Orders

- `orders_submitted_total`
- `orders_failed_total`
- `orders_filled_total`
- `orders_cancelled_total`
- `order_submission_latency_ms`

#### Alerts

- `alerts_emitted_total`
- `alerts_acknowledged_total`

### 23.3 Alert 정책 초안

초기 버전에서 반드시 알림 대상이 되어야 하는 이벤트:

- heartbeat 누락
- market data stale 증가
- repeated order failure
- config apply 실패
- worker crash
- DB 또는 Redis 연결 불가

권장 alert level:

- `info`: 일반 운영 이벤트
- `warn`: 운영자가 봐야 하는 이상 징후
- `error`: 즉시 대응이 필요한 장애
- `critical`: 실주문 중단 또는 강제 정지 고려

### 23.4 Dashboard 초안

초기 Grafana 또는 운영 조회 화면에서 보여야 할 최소 패널:

- active bots
- active strategy runs
- heartbeat lag
- orderbook age by exchange
- decision accepted vs rejected
- live orders / shadow orders count
- alert event count by level

## 24. 다음 우선 문서

이 문서 다음으로 바로 작성할 가치가 큰 문서는 아래 순서다.

1. OpenAPI YAML 초안
2. Alembic initial migration 문서
3. Redis event catalog
4. Strategy ADR
5. Deployment runbook

## 25. Deployment Runbook 초안

이 섹션은 새 프로젝트를 실제로 배포하고 운영할 때 필요한 최소 런북 초안이다.  
초기 버전은 Docker Compose 기반 운영을 기준으로 한다.

### 25.1 배포 단위

초기 배포 단위는 다음 5개다.

- `control-plane`
- `strategy-worker`
- `postgres`
- `redis`
- `notifier-dispatcher` 또는 alert worker

선택 배포:

- `grafana`
- `prometheus`
- `nginx` 또는 reverse proxy

### 25.2 환경 구분

필수 환경은 아래 3개다.

- `local`
- `staging`
- `production`

환경별로 분리해야 하는 것:

- PostgreSQL DB
- Redis DB 또는 namespace
- config set
- secret source
- alert destination
- bot registration scope

### 25.3 필수 환경 변수 초안

#### 공통

- `APP_ENV`
- `LOG_LEVEL`
- `TZ`

#### Control Plane

- `CONTROL_PLANE_HOST`
- `CONTROL_PLANE_PORT`
- `DATABASE_URL`
- `REDIS_URL`
- `ADMIN_TOKEN`

#### Strategy Worker

- `WORKER_ID`
- `DATABASE_URL`
- `REDIS_URL`
- `CONFIG_SCOPE`
- `RUN_MODE`

#### Notification

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SLACK_WEBHOOK_URL`

### 25.4 Secret 관리 원칙

- `.env`는 저장소에 커밋하지 않는다.
- 운영 secret은 vault 또는 배포 환경 secret store를 우선 사용한다.
- local 개발 시에만 `.env.local` 또는 별도 local secret file 허용
- bot API key/secret은 strategy worker가 직접 읽되 Control Plane DB에는 평문 저장 금지

### 25.5 초기 배포 순서

#### Local

1. PostgreSQL 기동
2. Redis 기동
3. Alembic migration 적용
4. Control Plane 기동
5. Strategy Worker 기동
6. Health check 확인
7. dry-run smoke test 수행

#### Staging

1. DB backup 또는 빈 스테이징 DB 준비
2. migration 적용
3. Control Plane 배포
4. Worker 배포
5. metrics / health / alert 확인
6. shadow mode smoke test 수행

#### Production

1. maintenance window 확인
2. DB backup 확인
3. migration 적용
4. Control Plane rolling deploy
5. Worker deploy
6. health / ready / metrics 확인
7. bot registration 확인
8. dry-run 또는 shadow sanity 확인
9. 제한적 live enable

### 25.6 최초 기동 체크리스트

- `/api/v1/health` 응답 정상
- `/api/v1/ready` 응답 정상
- PostgreSQL 연결 정상
- Redis 연결 정상
- Prometheus scrape 정상
- bot register 정상
- heartbeat 적재 정상
- alert hook 정상
- config latest 조회 정상

### 25.7 운영 모드 전환 규칙

#### Dry-run -> Shadow

전환 전 조건:

- order intent 생성 정상
- decision record 적재 정상
- heartbeat 안정
- stale alert 비정상적으로 많지 않음

#### Shadow -> Live

전환 전 조건:

- shadow 결과가 기대값과 유사
- alert noise 정리 완료
- rate limit 정책 검증 완료
- stop command 즉시 반영 확인
- 운영자 승인 완료

### 25.8 장애 대응 우선순위

#### 1순위: 실주문 중지

다음 조건이면 즉시 live mode를 차단한다.

- repeated order failure 증가
- balance mismatch 반복 발생
- stale orderbook 급증
- exchange auth 오류 지속
- DB 또는 Redis 불안정

#### 2순위: worker 격리

- 특정 worker만 문제면 해당 worker만 stop
- 다른 worker는 정상 유지

#### 3순위: Control Plane read-only 전환

- 쓰기 경로 문제 발생 시 운영 조회 API만 유지하고 명령 API 차단 가능해야 한다.

### 25.9 운영 명령 런북

#### 전략 중지

1. `/api/v1/strategy-runs/{run_id}/stop` 호출
2. stop accepted 확인
3. worker 상태가 `stopped`로 전이되는지 확인
4. live order 제출이 더 이상 없는지 확인

#### bot 격리

1. bot status 확인
2. config assignment 해제 또는 disable config 적용
3. heartbeat 중단 확인
4. alert noise 정리

#### config 롤백

1. 이전 `config_version` 조회
2. 대상 bot에 재할당
3. 적용 이벤트 확인
4. post-apply sanity check 수행

### 25.10 릴리즈 체크리스트

- migration 검토 완료
- OpenAPI 변경 검토 완료
- alert rule 변경 검토 완료
- metrics 대시보드 영향 확인
- rollback plan 존재
- live mode 영향 범위 명시

## 26. Strategy ADR 초안

이 섹션은 초기 전략 설계 결정을 기록하는 ADR(Architecture Decision Record) 초안이다.

### ADR-001: 첫 전략은 차익거래 전략으로 시작한다

#### 상태

Accepted

#### 배경

초기 플랫폼은 구조 검증이 우선이다.  
전략 자체의 복잡성보다 다음을 검증하는 데 유리한 전략이 필요하다.

- 거래소 2개 이상 어댑터 구조
- market snapshot 품질
- freshness 판단
- order intent 생성
- dry-run / shadow / live 모드
- 체결 후 재검증

#### 결정

초기 버전 첫 전략은 `2거래소 단순 차익거래 전략`으로 한다.

#### 이유

- 입력과 판단 구조가 비교적 단순하다.
- freshness와 실행 안전장치를 검증하기 좋다.
- 운영 지표를 정의하기 쉽다.

### ADR-002: 전략은 OrderIntent를 만들고 직접 주문 세부를 소유하지 않는다

#### 상태

Accepted

#### 결정

전략은 "실행 가능한 의도"인 `OrderIntent`까지만 생성한다.  
실제 주문 제출과 상태 추적은 execution 계층이 맡는다.

#### 이유

- dry-run / shadow / live를 동일 전략 코드로 처리 가능
- 전략 로직과 거래소 주문 세부 로직 분리
- replay와 debugging이 쉬움

### ADR-003: freshness 실패는 거래 기회 손실보다 우선한다

#### 상태

Accepted

#### 결정

시장 데이터 freshness가 기준을 넘으면, 예상 수익이 커도 거래하지 않는다.

#### 이유

- stale data 기반 거래는 실제 손실 확률이 높다.
- 운영 시스템은 기회 손실보다 잘못된 주문 방지가 우선이다.

### ADR-004: 주문 후 잔고 재검증은 필수다

#### 상태

Accepted

#### 결정

실주문 이후에는 반드시 체결 조회 또는 잔고 재조회로 결과를 검증한다.

#### 이유

- 거래소별 체결 이벤트 신뢰성이 다를 수 있음
- 부분 체결, 취소, 지연 반영 이슈를 방치하면 포지션 추정이 틀어짐

### ADR-005: 실행 모드는 제품 모델의 일부다

#### 상태

Accepted

#### 결정

`dry-run`, `shadow`, `live`는 단순 설정값이 아니라 시스템 핵심 실행 모델로 정의한다.

#### 이유

- 모드별 데이터 기록 기준이 달라짐
- 운영 승인 절차와 알림 정책이 달라짐
- QA와 운영 검증 흐름을 표준화할 수 있음

### ADR-006: 초기 전략 안전장치

초기 차익거래 전략은 최소한 아래 안전장치를 가진다.

- max order age
- min expected profit
- max order notional
- exchange별 health check 통과 여부
- balance sufficient 여부
- duplicate intent 방지
- emergency stop switch

### ADR-007: 초기 전략 의사결정 출력

전략은 다음 세 가지를 반드시 남겨야 한다.

- decision record
- order intent
- alert 또는 reject reason

즉, "왜 거래했는지"와 "왜 거래하지 않았는지"가 둘 다 남아야 한다.

## 27. OpenAPI YAML 초안

아래는 초기 버전 Control Plane용 OpenAPI YAML 초안이다.  
전체 엔드포인트를 모두 포함한 완성본은 아니고, MVP 구현에 필요한 핵심 경로와 스키마를 우선 정의한다.

```yaml
openapi: 3.1.0
info:
  title: Trading Platform Control Plane API
  version: 0.1.0
  description: >
    Automated trading platform control plane for bot registry,
    config management, strategy runs, order intents, orders, fills, and alerts.

servers:
  - url: https://api.example.com
    description: Production
  - url: https://staging-api.example.com
    description: Staging
  - url: http://localhost:8000
    description: Local

tags:
  - name: Health
  - name: Bots
  - name: Configs
  - name: StrategyRuns
  - name: OrderIntents
  - name: Orders
  - name: Alerts

paths:
  /api/v1/health:
    get:
      tags: [Health]
      summary: Health check
      operationId: getHealth
      responses:
        '200':
          description: Service is alive
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthResponse'

  /api/v1/ready:
    get:
      tags: [Health]
      summary: Readiness check
      operationId: getReadiness
      responses:
        '200':
          description: Service is ready
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReadyResponse'
        '503':
          description: Dependency unavailable

  /api/v1/bots/register:
    post:
      tags: [Bots]
      summary: Register a bot instance
      operationId: registerBot
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/BotRegisterRequest'
      responses:
        '200':
          description: Bot registered
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotRegisterResponse'
        '409':
          description: Bot key already registered

  /api/v1/bots:
    get:
      tags: [Bots]
      summary: List bots
      operationId: listBots
      parameters:
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/StrategyStatus'
        - in: query
          name: strategy_name
          schema:
            type: string
        - in: query
          name: mode
          schema:
            $ref: '#/components/schemas/RunMode'
      responses:
        '200':
          description: Bot list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotListResponse'

  /api/v1/bots/{bot_id}:
    get:
      tags: [Bots]
      summary: Get bot details
      operationId: getBot
      parameters:
        - $ref: '#/components/parameters/BotId'
      responses:
        '200':
          description: Bot detail
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotDetailResponse'
        '404':
          description: Bot not found

  /api/v1/bots/{bot_id}/heartbeat:
    post:
      tags: [Bots]
      summary: Submit bot heartbeat
      operationId: submitHeartbeat
      parameters:
        - $ref: '#/components/parameters/BotId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/HeartbeatRequest'
      responses:
        '200':
          description: Heartbeat accepted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HeartbeatResponse'
        '404':
          description: Bot not found

  /api/v1/configs:
    post:
      tags: [Configs]
      summary: Create config version
      operationId: createConfigVersion
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateConfigRequest'
      responses:
        '200':
          description: Config created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConfigVersionResponse'

  /api/v1/configs/{config_scope}/latest:
    get:
      tags: [Configs]
      summary: Get latest config by scope
      operationId: getLatestConfig
      parameters:
        - in: path
          name: config_scope
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Latest config
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConfigVersionResponse'
        '404':
          description: Config scope not found

  /api/v1/bots/{bot_id}/assign-config:
    post:
      tags: [Configs]
      summary: Assign config version to bot
      operationId: assignConfigToBot
      parameters:
        - $ref: '#/components/parameters/BotId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AssignConfigRequest'
      responses:
        '202':
          description: Assignment accepted
        '404':
          description: Bot or config not found

  /api/v1/strategy-runs:
    post:
      tags: [StrategyRuns]
      summary: Create strategy run
      operationId: createStrategyRun
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateStrategyRunRequest'
      responses:
        '200':
          description: Strategy run created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StrategyRunResponse'
    get:
      tags: [StrategyRuns]
      summary: List strategy runs
      operationId: listStrategyRuns
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/StrategyStatus'
      responses:
        '200':
          description: Strategy run list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StrategyRunListResponse'

  /api/v1/strategy-runs/{run_id}/start:
    post:
      tags: [StrategyRuns]
      summary: Start strategy run
      operationId: startStrategyRun
      parameters:
        - $ref: '#/components/parameters/RunId'
      responses:
        '202':
          description: Start accepted
        '404':
          description: Run not found

  /api/v1/strategy-runs/{run_id}/stop:
    post:
      tags: [StrategyRuns]
      summary: Stop strategy run
      operationId: stopStrategyRun
      parameters:
        - $ref: '#/components/parameters/RunId'
      responses:
        '202':
          description: Stop accepted
        '404':
          description: Run not found

  /api/v1/order-intents:
    get:
      tags: [OrderIntents]
      summary: List order intents
      operationId: listOrderIntents
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: strategy_run_id
          schema:
            type: string
            format: uuid
        - in: query
          name: market
          schema:
            type: string
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/OrderIntentStatus'
      responses:
        '200':
          description: Order intent list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderIntentListResponse'

  /api/v1/orders:
    get:
      tags: [Orders]
      summary: List orders
      operationId: listOrders
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: exchange_name
          schema:
            type: string
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/OrderStatus'
      responses:
        '200':
          description: Order list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderListResponse'

  /api/v1/alerts:
    get:
      tags: [Alerts]
      summary: List alerts
      operationId: listAlerts
      parameters:
        - in: query
          name: level
          schema:
            $ref: '#/components/schemas/AlertLevel'
        - in: query
          name: acknowledged
          schema:
            type: boolean
      responses:
        '200':
          description: Alert list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AlertListResponse'

  /api/v1/alerts/{alert_id}/ack:
    post:
      tags: [Alerts]
      summary: Acknowledge alert
      operationId: acknowledgeAlert
      parameters:
        - $ref: '#/components/parameters/AlertId'
      responses:
        '200':
          description: Alert acknowledged
        '404':
          description: Alert not found

components:
  parameters:
    BotId:
      in: path
      name: bot_id
      required: true
      schema:
        type: string
        format: uuid
    RunId:
      in: path
      name: run_id
      required: true
      schema:
        type: string
        format: uuid
    AlertId:
      in: path
      name: alert_id
      required: true
      schema:
        type: string
        format: uuid

  schemas:
    RunMode:
      type: string
      enum: [dry_run, shadow, live]

    StrategyStatus:
      type: string
      enum: [pending, running, stopped, failed, completed]

    OrderIntentStatus:
      type: string
      enum: [created, submitted, cancelled, expired, rejected, simulated]

    OrderStatus:
      type: string
      enum: [new, partially_filled, filled, cancelled, rejected, expired]

    AlertLevel:
      type: string
      enum: [info, warn, error, critical]

    ApiError:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
        message:
          type: string

    BotSummary:
      type: object
      required: [id, bot_key, strategy_name, mode, status]
      properties:
        id:
          type: string
          format: uuid
        bot_key:
          type: string
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        status:
          $ref: '#/components/schemas/StrategyStatus'
        hostname:
          type: string
        last_seen_at:
          type: string
          format: date-time

    ConfigVersionSummary:
      type: object
      required: [id, config_scope, version_no, checksum, created_at]
      properties:
        id:
          type: string
          format: uuid
        config_scope:
          type: string
        version_no:
          type: integer
        checksum:
          type: string
        created_at:
          type: string
          format: date-time

    BotRegisterRequest:
      type: object
      required: [bot_key, strategy_name, mode]
      properties:
        bot_key:
          type: string
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        hostname:
          type: string

    BotRegisterResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            bot:
              $ref: '#/components/schemas/BotSummary'
            assigned_config:
              $ref: '#/components/schemas/ConfigVersionSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    HeartbeatRequest:
      type: object
      required: [is_process_alive, is_market_data_alive, is_ordering_alive]
      properties:
        is_process_alive:
          type: boolean
        is_market_data_alive:
          type: boolean
        is_ordering_alive:
          type: boolean
        lag_ms:
          type: integer
        context:
          type: object
          additionalProperties: true

    HeartbeatResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            accepted:
              type: boolean
            server_time:
              type: string
              format: date-time
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    CreateConfigRequest:
      type: object
      required: [config_scope, config_json]
      properties:
        config_scope:
          type: string
        config_json:
          type: object
          additionalProperties: true

    AssignConfigRequest:
      type: object
      required: [config_version_id]
      properties:
        config_version_id:
          type: string
          format: uuid

    ConfigVersionResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/ConfigVersionSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    CreateStrategyRunRequest:
      type: object
      required: [bot_id, strategy_name, mode]
      properties:
        bot_id:
          type: string
          format: uuid
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'

    StrategyRunSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        bot_id:
          type: string
          format: uuid
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        status:
          $ref: '#/components/schemas/StrategyStatus'
        started_at:
          type: string
          format: date-time
        ended_at:
          type: string
          format: date-time

    StrategyRunResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    StrategyRunListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    OrderIntentSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        strategy_run_id:
          type: string
          format: uuid
        market:
          type: string
        buy_exchange:
          type: string
        sell_exchange:
          type: string
        target_qty:
          type: string
        expected_profit:
          type: string
        status:
          $ref: '#/components/schemas/OrderIntentStatus'
        created_at:
          type: string
          format: date-time

    OrderIntentListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/OrderIntentSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    OrderSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        exchange_name:
          type: string
        market:
          type: string
        side:
          type: string
        quantity:
          type: string
        price:
          type: string
        status:
          $ref: '#/components/schemas/OrderStatus'

    OrderListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/OrderSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    AlertEventSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        bot_id:
          type: string
          format: uuid
        level:
          $ref: '#/components/schemas/AlertLevel'
        code:
          type: string
        message:
          type: string
        created_at:
          type: string
          format: date-time
        acknowledged_at:
          type: string
          format: date-time
          nullable: true

    AlertListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/AlertEventSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    HealthResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            status:
              type: string
            service:
              type: string
            version:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    ReadyResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            status:
              type: string
            database:
              type: string
            redis:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    BotListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/BotSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    BotDetailResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            bot:
              $ref: '#/components/schemas/BotSummary'
            latest_config:
              $ref: '#/components/schemas/ConfigVersionSummary'
            latest_strategy_run:
              $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'
```

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

## 29. 거래소 설계 진행 상태

질문하신 거래소 관련 항목은 "방향과 범위"는 설계되어 있고, "거래소별 세부 계약"은 아직 초안 수준이다.

### 29.1 현재 설계된 수준

이미 문서에 반영된 것:

- 거래소 어댑터 공통 인터페이스 필요
- REST/WS/public/private 분리 필요
- rate limit과 재시도 정책은 전략이 아니라 어댑터 책임
- 최초 MVP는 2~3개 거래소만 지원

즉, 아키텍처 레벨 설계는 끝난 상태다.

### 29.2 아직 더 구체화가 필요한 것

거래소별로 추가 설계가 필요한 항목:

- Upbit
  - orderbook REST endpoint 계약
  - orderbook WS subscribe payload
  - private auth signature 방식
  - balance 응답 정규화 규칙
  - order status mapping

- Bithumb
  - public orderbook 정규화 규칙
  - private balance/order 응답 매핑
  - 에러 코드 표준화
  - 체결 정보 정규화

- Coinone
  - REST/WS 최신 API 기준 응답 스키마 정리
  - private auth 및 nonce 처리 규칙
  - partial fill / remain qty 정규화
  - rate limit 정책

### 29.3 거래소 설계 상태 판단

- 공통 어댑터 구조: 설계됨
- 거래소별 세부 계약: 미완료
- 에러 코드 표준화: 미완료
- test fixture / mock payload: 미완료

즉, "구조 설계는 완료, 거래소별 상세 명세는 다음 문서 단계"라고 보면 된다.

## 30. 웹 UI 설계 진행 상태

웹 UI도 방향은 설계되어 있지만, 상세 화면 설계는 아직 초안 전 단계다.

### 30.1 현재 설계된 수준

문서상 이미 확정된 수준:

- Control Plane은 운영 조회와 명령을 담당
- 읽기 모델과 쓰기 모델 분리
- Grafana 기반 대시보드와 별도 운영 조회 API를 함께 고려

즉, UI는 "필수 운영 조회 화면" 위주로 가야 한다는 방향은 정해져 있다.

### 30.2 초기 UI 범위 제안

초기 웹 UI는 다음 5개 화면이면 충분하다.

1. Bot Overview
   - bot 목록
   - 상태
   - last seen
   - mode
   - assigned config version

2. Strategy Run Detail
   - run 상태
   - start/stop
   - 최근 decision count
   - reject reason 분포

3. Order / Fill Explorer
   - order_intents
   - orders
   - fills
   - exchange별 필터

4. Alert Center
   - alert 목록
   - level별 필터
   - acknowledge

5. Config Viewer
   - config scope
   - version history
   - latest assigned bots

### 30.3 아직 설계가 필요한 UI 항목

- 화면 IA
- 화면별 API dependency
- 인증 방식
- 관리자 권한 모델
- 다크/라이트 테마 여부
- Grafana와 자체 UI의 경계

### 30.4 UI 설계 상태 판단

- UI 역할 정의: 설계됨
- 초기 화면 목록: 설계됨
- 상세 와이어프레임: 미완료
- 프론트엔드 스택 결정: 미완료

즉, 웹 UI는 "무엇을 보여줘야 하는가"는 정리됐고, "어떻게 그릴 것인가"는 아직 남아 있다.

## 31. 전체 설계 진행 상황

지금까지 문서 기준으로 보면 전체 설계 진행 상황은 아래 정도다.

### 31.1 완료된 영역

- 제품 비전
- 제품 목표 / 비목표
- 핵심 사용자 정의
- 제품 원칙
- 권장 기술 스택
- 목표 아키텍처
- 권장 디렉터리 구조
- 기능 요구사항
- 비기능 요구사항
- MVP 범위
- 구현 순서
- 초기 PostgreSQL 스키마 초안
- API 명세 초안
- OpenAPI YAML 초안
- Redis key / stream 규약
- migration 정책
- decision record format
- observability spec
- deployment runbook
- strategy ADR

### 31.2 아직 초안 수준인 영역

- 거래소별 상세 어댑터 계약
- UI 상세 설계
- OpenAPI 완성본
- Redis event catalog 상세판
- migration 실제 revision 파일 수준 설계
- alert rule 임계치 값
- 전략별 리스크 규칙 상세값

### 31.3 아직 거의 시작하지 않은 영역

- 프론트엔드 실제 스택 선택
- auth / RBAC
- object storage 사용 여부
- backtesting / replay spec
- 운영자 워크플로우 문서
- SLO / SLA 정의

### 31.4 현재 진척도 판단

내 기준으로는 지금 문서 설계는 다음 정도까지 왔다.

- 시스템/제품 아키텍처: 85%
- 데이터 모델: 75%
- API 설계: 70%
- 운영 설계: 80%
- 거래소 세부 설계: 40%
- UI 세부 설계: 35%

전체적으로 보면 "프로젝트 착수 가능한 수준의 상위 설계는 완료" 상태다.  
다음 단계는 더 많은 PRD 확장이 아니라, 거래소 상세 설계와 UI 상세 설계를 별도 문서로 파고드는 것이 맞다.

## 32. 거래소 어댑터 상세 설계

이 섹션은 코인원, 빗썸, 업비트 어댑터를 구현하기 전에 공통 계약과 거래소별 정규화 관점을 정리한 상세 설계다.  
구체 API endpoint 문자열이나 인증 파라미터 이름은 구현 직전 공식 문서 기준으로 검증해야 하며, 여기서는 "플랫폼 내부 계약"을 정의한다.

### 32.1 어댑터 공통 책임

모든 거래소 어댑터는 아래 기능을 공통 제공해야 한다.

- public orderbook snapshot 조회
- public orderbook stream 구독
- private balance 조회
- private order 제출
- private order 상태 조회
- private open order 목록 조회
- 거래소 고유 에러를 내부 에러 코드로 정규화
- 거래소 rate limit과 backoff 정책 처리

전략 계층은 어댑터의 내부 인증 방식이나 응답 원문 구조를 몰라야 한다.

### 32.2 공통 인터페이스 초안

```python
class ExchangeAdapter(Protocol):
    name: str

    async def get_orderbook_top(self, market: str) -> OrderBookTop: ...
    async def subscribe_orderbook(self, market: str) -> AsyncIterator[OrderBookTop]: ...

    async def get_balances(self) -> list[BalanceItem]: ...

    async def place_order(self, req: PlaceOrderRequest) -> ExchangeOrderRef: ...
    async def get_order_status(self, exchange_order_id: str, market: str) -> OrderStatusSnapshot: ...
    async def list_open_orders(self, market: str | None = None) -> list[OrderStatusSnapshot]: ...
```

### 32.3 공통 도메인 모델

#### `OrderBookTop`

```json
{
  "exchange": "upbit",
  "market": "XRP-KRW",
  "best_bid": "1023.2",
  "best_ask": "1023.3",
  "bid_volume": "1500.12",
  "ask_volume": "948.33",
  "exchange_timestamp": "2026-04-03T14:12:00Z",
  "received_at": "2026-04-03T14:12:00.120Z",
  "source_type": "ws"
}
```

#### `BalanceItem`

```json
{
  "exchange": "bithumb",
  "asset": "KRW",
  "total": "1200000",
  "available": "1180000",
  "locked": "20000",
  "snapshot_at": "2026-04-03T14:12:04Z"
}
```

#### `PlaceOrderRequest`

```json
{
  "market": "XRP-KRW",
  "side": "buy",
  "order_type": "limit",
  "price": "1020.5",
  "quantity": "120.5",
  "client_order_id": "uuid"
}
```

#### `OrderStatusSnapshot`

```json
{
  "exchange": "coinone",
  "exchange_order_id": "abc123",
  "market": "XRP-KRW",
  "side": "buy",
  "status": "partially_filled",
  "price": "1020.5",
  "quantity": "120.5",
  "filled_quantity": "40.0",
  "remaining_quantity": "80.5",
  "avg_fill_price": "1020.7",
  "updated_at": "2026-04-03T14:12:10Z"
}
```

### 32.4 내부 에러 코드 규약

거래소별 에러는 아래 내부 코드로 정규화한다.

- `AUTH_FAILED`
- `RATE_LIMITED`
- `INSUFFICIENT_BALANCE`
- `ORDER_REJECTED`
- `ORDER_NOT_FOUND`
- `NETWORK_ERROR`
- `SERVER_ERROR`
- `INVALID_SYMBOL`
- `INVALID_REQUEST`
- `TEMPORARY_UNAVAILABLE`

각 어댑터는 원본 에러 코드와 메시지를 보존하되, 전략/실행 계층에는 내부 코드만 전달한다.

### 32.5 Rate Limit 정책

어댑터는 최소한 아래 3계층 제한을 관리해야 한다.

- public REST limit
- private REST limit
- websocket reconnect / subscribe burst limit

전략은 요청 속도를 직접 제어하지 않고, 어댑터는 초과 시:

1. local throttle
2. retry with backoff
3. still failing 시 `RATE_LIMITED` 또는 `TEMPORARY_UNAVAILABLE`

로 정규화한다.

### 32.6 Upbit 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 제공
- private balance / order / order status 제공
- websocket 기반 빠른 orderbook 업데이트 주 공급원 역할

#### 구현 시 확인할 항목

- market symbol 매핑
- WS reconnect 정책
- auth header / JWT 방식
- partial fill 상태 표현
- balance asset naming

#### 정규화 시 주의점

- market 형식을 내부 표준으로 통일
- 잔고 응답의 total/available/locked 계산 규칙 명확화
- order status의 terminal state 판정 기준 고정

### 32.7 Bithumb 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 공급
- private balance / order / order status 제공

#### 구현 시 확인할 항목

- public / private 응답 구조 차이
- 체결 정보의 부분 체결 누적 방식
- remaining quantity 계산 기준
- 에러 코드 집합

#### 정규화 시 주의점

- 체결 contract 배열이 있을 경우 내부 fill 모델로 풀어야 함
- order status를 `new / partially_filled / filled / cancelled / rejected`로 안정적으로 매핑

### 32.8 Coinone 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 공급
- private balance / order / order status 제공

#### 구현 시 확인할 항목

- nonce 또는 request signing 규칙
- remain quantity / filled quantity 필드 의미
- orderbook timestamp 신뢰성
- rate limit 및 maintenance 응답

#### 정규화 시 주의점

- remain 기준으로 filled 계산이 필요한 경우가 있음
- maintenance나 temporary unavailable 상태를 전략 차단 신호로 연결해야 함

### 32.9 거래소별 테스트 요구사항

거래소마다 최소 아래 테스트 픽스처가 필요하다.

- 정상 orderbook REST 응답 샘플
- 정상 orderbook WS 샘플
- 정상 balance 응답 샘플
- 정상 order submit 응답 샘플
- partial fill 응답 샘플
- terminal fill 응답 샘플
- auth 실패 응답 샘플
- rate limit 응답 샘플

### 32.10 거래소 상세 설계 산출물

각 거래소별로 아래 문서 또는 구현 산출물이 있어야 한다.

- endpoint inventory
- auth flow
- request signing spec
- normalized payload mapping table
- error mapping table
- retry / backoff policy
- mock fixture set

## 33. 웹 UI 상세 설계

웹 UI는 거래용 UI가 아니라 운영 UI다.  
즉, 복잡한 차트 트레이딩 화면보다 "상태 확인, 이상 감지, 명령 실행"이 중심이어야 한다.

### 33.1 UI 목표

- 운영자가 현재 상태를 한눈에 본다.
- 문제 bot을 빠르게 찾는다.
- strategy run과 order flow를 추적한다.
- config 변경과 alert 확인을 처리한다.

### 33.2 프론트엔드 권장 스택

초기 버전 권장안:

- Next.js 또는 React + TypeScript
- TanStack Query
- Tailwind CSS
- shadcn/ui 또는 headless UI 계열 컴포넌트
- chart는 필요 최소만 사용

이유:

- 운영 UI는 복잡한 비주얼보다 빠른 개발과 명확한 상태 표현이 우선
- Control Plane API와 타입 연동이 쉬움

### 33.3 정보 구조(IA)

초기 IA 제안:

- `/bots`
- `/bots/{botId}`
- `/strategy-runs`
- `/strategy-runs/{runId}`
- `/orders`
- `/fills`
- `/alerts`
- `/configs`
- `/configs/{scope}`

### 33.4 화면 상세

#### 1. Bot Overview

목적:

- 전체 bot 상태를 빠르게 파악

주요 컬럼:

- bot key
- strategy
- mode
- status
- hostname
- last seen
- latest config version
- heartbeat lag

행동:

- 상세 이동
- stop / restart
- config assign

#### 2. Bot Detail

목적:

- 개별 bot의 최근 상태와 heartbeat, latest strategy run 확인

주요 섹션:

- bot summary
- latest heartbeat
- latest alerts
- recent order intents
- recent orders
- assigned config

#### 3. Strategy Run List / Detail

목적:

- 특정 run이 어떤 모드로 동작 중인지 확인

주요 정보:

- run status
- mode
- started_at / ended_at
- decision count
- reject reason distribution
- linked order intents

#### 4. Order / Fill Explorer

목적:

- 주문 흐름 추적

필터:

- bot
- strategy run
- exchange
- market
- status
- created range

테이블:

- order intent
- order
- fills

#### 5. Alert Center

목적:

- 경고와 장애를 우선순위대로 처리

필수 기능:

- level 필터
- acknowledged 필터
- bot 연관 링크
- acknowledge action

#### 6. Config Viewer

목적:

- config scope / version history 확인

필수 기능:

- latest config 조회
- version diff
- assigned bots 목록

### 33.5 상태 색상 규칙

- `running`: green
- `pending`: blue
- `stopped`: gray
- `failed`: red
- `warn`: amber
- `critical`: red 강조

운영 UI는 색상 규칙이 일관돼야 한다.

### 33.6 초기 UI에서 넣지 않을 것

- 고급 주문 수동 입력 화면
- 복잡한 캔들 차트
- 백테스트 리포트 대시보드
- 사용자별 커스텀 레이아웃

### 33.7 UI와 Grafana의 경계

자체 UI가 맡는 것:

- bot registry
- config version
- strategy run 상태
- order intent / order / fill 탐색
- alert ack
- 운영 명령

Grafana가 맡는 것:

- 시계열 heartbeat
- orderbook age 추이
- request latency
- alert volume trend

### 33.8 UI 상세 설계에서 다음으로 필요한 것

- 페이지별 wireframe
- 컴포넌트 목록
- route map
- API dependency map
- auth / RBAC 정책

## 34. 거래소별 Endpoint Inventory 초안

이 섹션은 코인원, 빗썸, 업비트의 구현 대상 endpoint 범주를 정리한 초안이다.  
정확한 URI, 메서드, 요청/응답 필드명은 구현 직전 공식 문서로 재검증해야 하며, 여기서는 플랫폼 구현 범위를 고정하는 목적이 더 크다.

### 34.1 Upbit

공식 문서 기준으로 Upbit는 Quotation REST, Exchange REST, WebSocket 문서 구조가 비교적 명확하다.  
구현 대상은 다음이다.

#### Public REST

- 주문 가능 마켓/페어 조회
- 호가(orderbook) 조회
- 현재가/체결가 보조 조회

#### Public WebSocket

- orderbook stream
- trade/ticker는 초기 MVP에서는 선택

#### Private REST

- balance 조회
- 주문 생성
- 주문 단건 조회
- 미체결 주문 조회
- 주문 취소

#### Private WebSocket

- 내 주문 / 체결 이벤트
- 내 자산 변동 이벤트

#### 참고 문서 범주

- Upbit 인증 가이드
- Quotation API Reference
- WebSocket orderbook reference
- 주문/잔고 Exchange API Reference

### 34.2 Bithumb

빗썸은 최근 문서 버전과 changelog 갱신이 활발하고, Public/Private, REST/WebSocket 버전 차이가 섞여 있으므로 구현 전 최종 버전을 잠가야 한다.

#### Public REST

- 호가(orderbook) 조회
- 시세 보조 조회

#### Public WebSocket

- orderbook stream
- 필요 시 ticker / trade stream

#### Private REST

- balance 조회
- 주문 생성
- 주문 단건 조회
- 미체결 주문 조회
- 주문 취소

#### Private WebSocket

- 내 주문/체결 이벤트
- 내 자산 변동 이벤트

#### 추가 주의

- 주문 관련 별도 rate limit이 존재하므로 주문 API는 일반 private API와 다른 limiter를 둬야 함
- 신규 주문 유형(TWAP 등) 확장 가능성이 있어 `order_type` 내부 enum은 유연하게 설계

### 34.3 Coinone

코인원은 v2.1 계열 private API와 public/private websocket 문서를 기준으로 구현하는 것이 적절하다.  
구버전/폐기 예정 API가 섞여 있으므로 v2.1 기준을 고정해야 한다.

#### Public REST

- orderbook snapshot 조회
- 마켓 정보 조회

#### Public WebSocket

- orderbook stream

#### Private REST

- balance 조회
- 주문 생성
- 주문 정보 조회
- 미체결/체결 주문 조회
- 주문 취소

#### Private WebSocket

- MYORDER
- MYASSET

#### 추가 주의

- deprecated 문서와 권장 문서가 혼재하므로 endpoint inventory 확정 시 폐기 API를 명시적으로 배제
- private websocket 인증 실패와 connection limit을 운영 alert 기준에 포함

### 34.4 공통 구현 우선순위

세 거래소 모두 초기 MVP에서 반드시 구현해야 하는 공통 기능:

1. public orderbook REST
2. public orderbook WS
3. private balance
4. private place order
5. private order status

이 다섯 가지가 완성돼야 전략 엔진 MVP가 성립한다.

## 35. 거래소별 Auth Flow 초안

이 섹션은 플랫폼 내부 관점의 인증 흐름 초안이다.  
정확한 header 이름, payload field, signature algorithm 파라미터는 구현 직전 공식 문서로 재검증한다.

### 35.1 공통 원칙

- 거래소 secret은 DB에 평문 저장 금지
- worker는 secret source 또는 secure local secret만 사용
- access key / secret key / nonce / timestamp 생성 책임은 adapter 내부에 둔다
- 전략 계층은 인증 세부를 몰라야 한다

### 35.2 Upbit Auth Flow

문서상 Upbit는 API Key 기반 인증 가이드를 제공하며, Exchange REST와 private WebSocket 모두 인증이 필요하다.

권장 구현 흐름:

1. worker가 secure store에서 access key / secret key 로드
2. request payload 기준 서명용 claim 구성
3. JWT 생성
4. REST는 Authorization header 부착
5. private websocket 연결 시 인증 payload 또는 token 부착

운영 주의:

- API key 권한 그룹 분리
- 허용 IP 설정 필요
- private websocket은 reconnect 시 인증 재수행

### 35.3 Bithumb Auth Flow

빗썸은 private API와 private websocket이 분리되어 있고, 버전 변화가 있으므로 auth flow 구현 전 최종 문서 버전을 잠가야 한다.

권장 구현 흐름:

1. api key / secret 로드
2. 요청별 nonce/timestamp 생성
3. 문서 기준 signature 생성
4. private REST header 부착
5. private websocket 연결 시 인증 메시지 전송

운영 주의:

- private websocket 안정화 이슈가 changelog에 존재하므로 reconnect/backoff 전략 필요
- 주문 API는 별도 limiter 적용

### 35.4 Coinone Auth Flow

코인원은 private REST와 private websocket 모두 인증이 필요하며, request signing / nonce 관리가 핵심이다.

권장 구현 흐름:

1. access token 또는 api key / secret 로드
2. nonce/timestamp 생성
3. 문서 기준 payload encode + sign
4. REST 요청 header/body 부착
5. private websocket 연결 시 인증 요청 송신

운영 주의:

- connection limit과 auth failure close code를 alert 조건에 반영
- nonce 재사용 방지

## 36. 거래소별 Error Mapping 초안

전략과 실행 계층은 거래소 고유 에러 문자열에 직접 의존하면 안 된다.  
모든 거래소 에러는 아래 내부 코드 체계로 매핑한다.

### 36.1 내부 표준 코드

- `AUTH_FAILED`
- `RATE_LIMITED`
- `INSUFFICIENT_BALANCE`
- `ORDER_REJECTED`
- `ORDER_NOT_FOUND`
- `NETWORK_ERROR`
- `SERVER_ERROR`
- `INVALID_SYMBOL`
- `INVALID_REQUEST`
- `TEMPORARY_UNAVAILABLE`
- `WS_AUTH_FAILED`
- `WS_CONNECTION_LIMIT`
- `WS_STREAM_ERROR`

### 36.2 Upbit 매핑 초안

- 인증 실패/권한 부족 → `AUTH_FAILED`
- 요청 수 제한 → `RATE_LIMITED`
- 주문 가능 금액/수량 부족 → `INSUFFICIENT_BALANCE`
- 잘못된 마켓/파라미터 → `INVALID_SYMBOL` 또는 `INVALID_REQUEST`
- websocket private 인증 실패 → `WS_AUTH_FAILED`

### 36.3 Bithumb 매핑 초안

- private 인증 실패 → `AUTH_FAILED`
- private / order API 요청 수 제한 → `RATE_LIMITED`
- 주문 정책 불일치 / 허용되지 않은 주문 유형 → `ORDER_REJECTED`
- 잘못된 가격/수량 포맷 → `INVALID_REQUEST`
- private websocket 연결 이상 → `WS_STREAM_ERROR`

### 36.4 Coinone 매핑 초안

- auth 또는 signature 불일치 → `AUTH_FAILED`
- nonce/요청 형식 오류 → `INVALID_REQUEST`
- insufficient balance → `INSUFFICIENT_BALANCE`
- deprecated endpoint 사용 또는 지원 불가 → `INVALID_REQUEST` 또는 `TEMPORARY_UNAVAILABLE`
- private websocket auth close → `WS_AUTH_FAILED`
- connection limit 초과 close → `WS_CONNECTION_LIMIT`

### 36.5 에러 매핑 구현 규칙

- raw error payload는 주문/알림/로그 context에 보존
- 내부 계층에는 표준 코드만 전달
- `retryable` 여부를 에러 객체에 함께 포함

예시:

```json
{
  "exchange": "coinone",
  "internal_code": "RATE_LIMITED",
  "retryable": true,
  "raw_code": "TODO(verify)",
  "raw_message": "Too many requests"
}
```

## 37. 2026-04-04 기준 공식 문서 재검증 메모

이 섹션은 2026년 4월 4일 기준 공식 문서에서 다시 확인한 내용만 요약한 것이다.  
정확한 endpoint path, header name, field schema는 구현 직전 한 번 더 공식 문서 기준으로 잠그는 것을 원칙으로 한다.

### 37.1 Upbit 재검증 포인트

- private websocket endpoint는 `wss://api.upbit.com/websocket/v1/private`
- 내 주문 및 체결, 내 자산 구독은 private endpoint와 인증 헤더가 필요
- websocket 요청 제한 정책은 문서상 별도 그룹으로 관리되며, 인증 포함 여부에 따라 계정 단위 또는 IP 단위로 측정
- 공식 문서에는 websocket 메시지 제한이 초당 5회, 분당 100회로 안내되어 있음
- 허용 IP 설정은 운영 전 필수 점검 항목

문서 반영 원칙:

- Upbit adapter는 REST auth와 private WS auth를 동일한 token provider 계층에서 공급
- private WS 연결 재수립 시 토큰 재생성 필수
- rate limiter는 REST/WS를 분리하되, Exchange 계열은 계정 단위 quota를 전제로 설계

### 37.2 Bithumb 재검증 포인트

- 인증 헤더 문서는 버전별 차이가 있음
- `v1.2.0` 문서에서는 `Api-Nonce`를 millisecond timestamp로 설명
- `v2.1.5` 문서에서는 `nonce`를 UUID 문자열로 설명
- 따라서 빗썸 adapter는 "문서 버전 pinning" 없이 구현하면 인증 오류 위험이 큼
- private websocket은 changelog 기준으로 정책 변경과 안정화 공지가 반복되고 있으므로 reconnect/backoff를 필수 capability로 본다

문서 반영 원칙:

- Bithumb adapter는 auth profile을 코드 상수로 고정하고, 어떤 문서 버전에 맞춰 구현했는지 release note에 명시
- websocket 연결 정책은 별도 limiter와 reconnect circuit breaker를 둔다
- error mapping 시 HTTP 상태만 보지 말고 body error code까지 함께 저장한다

### 37.3 Coinone 재검증 포인트

- private websocket endpoint는 `wss://stream.coinone.co.kr/v1/private`
- private websocket은 인증 필요
- 계정당 최대 20개 연결 허용
- 연결 초과 시 `4290` close code, 인증 실패 시 `4280` close code
- 마지막 PING 이후 30분이 지나면 idle 연결로 간주되어 종료
- public/private request signing은 access token, secret key, payload/signature 흐름을 명확히 따름

문서 반영 원칙:

- Coinone adapter는 ping scheduler를 내장
- close code 기반 장애 분류를 반드시 구현
- connection pool 설계 시 계정당 private WS 연결 수를 하드 제한

### 37.4 구현 시 소스 잠금 규칙

- 거래소별 adapter 구현 시작 전 공식 문서 URL과 확인 일자를 ADR 또는 release note에 기록
- changelog subscription 또는 주간 확인 루틴을 운영 절차에 포함
- 문서가 상충할 경우 "현재 배포 버전에서 실제 통과한 contract"를 별도 compatibility note로 남긴다

## 38. 상태 전이 설계

전략 실행과 주문 실행은 상태 전이가 명확해야 한다.  
이 섹션은 DB enum과 API 응답, UI 표시 상태를 일치시키기 위한 기준이다.

### 38.1 Strategy Run 상태 전이

권장 상태:

- `created`
- `starting`
- `running`
- `degraded`
- `paused`
- `stopping`
- `stopped`
- `failed`

전이 규칙:

- `created -> starting -> running`
- freshness 실패, connector 일부 장애, balance stale 발생 시 `running -> degraded`
- 운영자 수동 중지 시 `running/degraded/paused -> stopping -> stopped`
- 치명적 초기화 실패 시 `starting -> failed`
- 일시적 거래 차단은 `running -> paused`, 복구 후 `paused -> running`

### 38.2 Order Intent 상태 전이

권장 상태:

- `created`
- `validated`
- `submitted`
- `partially_filled`
- `filled`
- `cancel_requested`
- `cancelled`
- `rejected`
- `expired`
- `failed`

전이 규칙:

- 전략이 decision record를 만들면 `created`
- 리스크 검증, 잔고 검증, freshness 검증 통과 시 `validated`
- 거래소 제출 성공 시 `submitted`
- 부분 체결 발생 시 `partially_filled`
- 전량 체결 시 `filled`
- 거래소 거부 또는 정책 위반 시 `rejected`
- 일정 시간 초과 또는 시장 조건 상실 시 `expired`
- 네트워크/알 수 없는 오류는 `failed`

### 38.3 Order 상태 전이

거래소 원본 주문 상태는 제각각이므로 내부 표준 상태를 둔다.

- `new`
- `open`
- `partially_filled`
- `filled`
- `cancelled`
- `rejected`
- `failed`

매핑 원칙:

- 거래소별 세부 상태 문자열은 원문 보존
- UI와 전략 판단은 내부 상태 기준으로만 작동
- fill event는 order 상태와 별도로 누적 저장

### 38.4 Position 상태 전이

초기 MVP는 현물 양방향 차익 전략을 기준으로 포지션 개념을 단순화한다.

- `flat`
- `opening`
- `open`
- `closing`
- `closed`
- `unwind_required`

전이 규칙:

- 양 거래소 주문 제출 직후 `opening`
- 양쪽 체결이 모두 확인되면 `open`
- 청산 로직 진입 시 `closing`
- 잔여 수량 0이면 `closed`
- 한쪽만 체결되거나 hedge mismatch 발생 시 `unwind_required`

## 39. 인증, 비밀관리, RBAC 초안

### 39.1 비밀관리 원칙

- 거래소 API secret은 DB 평문 저장 금지
- control plane은 secret metadata만 저장
- 실제 secret 값은 외부 secret manager 또는 로컬 encrypted file source 사용
- worker는 기동 시 필요한 secret만 메모리에 로드
- secret rotation은 bot 재기동 없이 가능하도록 versioned reference 사용

### 39.2 권장 권한 모델

초기 UI와 API는 최소 세 역할로 시작한다.

- `viewer`
- `operator`
- `admin`

권한 범위:

- `viewer`: 조회 전용, bot/주문/알림/로그 조회 가능
- `operator`: pause/resume, dry-run 전환, config 배포 승인 요청 가능
- `admin`: secret 등록, bot 생성, live 모드 전환 승인, 권한 관리 가능

### 39.3 민감 동작의 이중 보호

다음 동작은 단순 API 호출만으로 끝내지 않는다.

- live mode 전환
- 거래소 키 교체
- emergency stop 해제
- config version production assignment

권장 보호:

- reason 필드 필수
- audit log 기록
- 2단계 승인 또는 admin 권한 한정

### 39.4 Audit Log 초안

초기 MVP에서도 아래 이벤트는 별도 저장한다.

- 누가 언제 어떤 bot을 pause/resume 했는지
- 누가 어떤 config version을 배포했는지
- 누가 live mode를 활성화했는지
- 누가 secret reference를 교체했는지

추가 테이블 제안:

- `audit_events(id, actor_id, actor_role, action, target_type, target_id, payload_json, created_at)`

## 40. 거래소 통합 테스트 매트릭스 초안

한국 거래소는 범용 sandbox가 제한적이거나 기능이 축소될 수 있으므로, 테스트 전략을 계층별로 나눈다.

### 40.1 테스트 계층

- contract test: 공식 문서와 샘플 payload 기준의 request/response schema 검증
- replay test: 저장된 orderbook / trade / order event를 재생
- simulation test: fake connector로 strategy 판단 검증
- live smoke test: 최소 권한 실계정으로 잔고 조회, 주문 가능 정보 조회, 주문 생성/취소 소액 검증

### 40.2 거래소별 필수 검증 항목

공통:

- public REST orderbook 정상 수신
- public WS orderbook reconnect
- private balance 조회
- 주문 생성
- 주문 조회
- 주문 취소
- private WS my order / my asset 수신
- rate limit 초과 시 backoff 동작
- auth 실패 시 non-retry 분류

### 40.3 시나리오 테스트 세트

- stale orderbook 입력 시 거래 차단
- balance snapshot이 오래되면 order intent 생성 차단
- 한 거래소만 부분 체결되면 `unwind_required`
- websocket 단절 시 REST fallback 또는 degraded 전환
- 동일 주문의 REST 조회 결과와 private WS 이벤트가 충돌하면 reconciliation job 수행

### 40.4 배포 전 승인 기준

거래소 adapter는 아래를 만족해야 production candidate가 된다.

- 최소 7일 shadow mode 무중단
- live smoke test 연속 성공
- auth refresh/reconnect 관련 치명 이슈 0건
- error mapping 누락 0건
- rate limit 위반 경고가 허용 기준 이하

## 41. UI 정보 구조와 핵심 사용자 흐름

33장의 웹 UI 상세 설계를 실제 제품 흐름 관점으로 다시 정리한다.

### 41.1 최상위 정보 구조

- Dashboard
- Bots
- Strategy Runs
- Orders / Fills
- Positions
- Alerts
- Configs
- Audit

### 41.2 Dashboard 핵심 카드

- 전체 bot 상태 요약
- exchange connector 상태
- 최근 1시간 alert 수
- 현재 degraded / paused bot 수
- 오늘 주문 건수, fill 건수, 실패 건수
- 최근 decision latency / order ack latency

### 41.3 Bot Detail 사용자 흐름

1. 운영자는 bot 목록에서 대상 bot 선택
2. 현재 run mode, strategy 상태, heartbeat freshness 확인
3. 최근 decision record와 latest alert 확인
4. 필요 시 pause/resume 또는 dry-run 전환 실행
5. 실행 내역은 audit trail에서 즉시 확인

### 41.4 Order Explorer 사용자 흐름

1. 거래소, bot, strategy run, 심볼, 시간 범위로 필터
2. order intent와 실제 order/fill를 한 화면에서 연결해 확인
3. 실패 주문은 internal error code와 raw payload를 함께 확인
4. replay/debug가 필요하면 decision record와 market snapshot으로 이동

### 41.5 Config 배포 사용자 흐름

1. 새 config version 생성
2. diff 확인
3. staging bot 또는 dry-run bot에 assignment
4. shadow 결과 확인
5. 승인 후 production assignment

### 41.6 초기 UI 비목표

- 차트 중심의 복잡한 수동 트레이딩 터미널
- 모바일 앱 우선 전략
- 사용자별 커스터마이징 대시보드
- 고급 BI 수준의 자유 질의 리포팅

## 42. 설계 완료 기준과 남은 공백

이 문서는 이미 새 프로젝트 착수를 위한 상위 설계 문서로 사용할 수 있다.  
다만 실제 구현 직전에는 아래 공백을 닫아야 한다.

### 42.1 구현 착수 가능 항목

- control plane API 골격
- PostgreSQL schema 1차 migration
- Redis stream/key 규약 기반 event bus 골격
- strategy worker runtime 골격
- observability/logging/notifier 기본 모듈
- Bot Overview, Bot Detail, Order Explorer 초기 UI

### 42.2 구현 직전 추가 확정이 필요한 항목

- Upbit / Bithumb / Coinone 공식 API 문서 버전 pinning
- 거래소별 symbol normalization 규칙
- 수수료 계산 source of truth
- 최소 주문 수량/금액 validation 규칙
- live mode 승인 절차와 실제 운영 책임자
- secret manager 방식

### 42.3 문서 기준 완료 정의

다음 조건을 만족하면 "설계 1차 완료"로 본다.

- PRD, 아키텍처, DB, API, 운영, UI, adapter 설계가 한 문서 안에서 충돌 없이 연결됨
- 전략 판단부터 주문, fill, 포지션, alert, audit까지 이벤트 흐름이 정의됨
- 거래소 구현 시 필요한 auth, endpoint, error mapping의 초안이 존재함
- production 이전에 필요한 test matrix와 approval gate가 정의됨

### 42.4 다음 상세 문서 후보

- 거래소별 symbol / fee / precision 규약서
- Order reconciliation job 상세 설계
- Position unwind engine 상세 설계
- Frontend API query contract 문서
- 운영자 장애 대응 플레이북 심화판

## 43. 거래소별 Symbol / Fee / Precision 규약 초안

전략 계층은 거래소 고유 표기법과 가격/수량 규칙을 직접 다루지 않는다.  
모든 거래소 adapter는 아래 내부 표준 모델로 정규화한다.

### 43.1 내부 표준 심볼 모델

권장 표준:

- `instrument_type`: `spot`
- `base_asset`: 예: `BTC`
- `quote_asset`: 예: `KRW`
- `canonical_symbol`: 예: `BTC/KRW`
- `exchange_symbol`: 거래소별 원본 표기

매핑 예시:

- Upbit: `KRW-BTC` -> `BTC/KRW`
- Bithumb: `KRW-BTC` -> `BTC/KRW`
- Coinone: `quote_currency=KRW`, `target_currency=BTC` -> `BTC/KRW`

정규화 원칙:

- 내부 저장과 전략 입력은 항상 `canonical_symbol` 사용
- 외부 요청 직전 adapter가 `exchange_symbol` 또는 path/body field로 변환
- symbol dictionary는 수동 하드코딩보다 거래소 metadata API 또는 관리 테이블로 유지

### 43.2 거래소별 심볼 표현 규약

#### Upbit

- 공식 문서 기준 market 코드는 `KRW-BTC` 형식
- quote asset이 앞, base asset이 뒤
- websocket도 동일 market code 사용

#### Bithumb

- 최신 private/public 문서 예시 기준 market ID는 `KRW-BTC` 형식
- V2.1.x 기준 market field를 사용하므로 Upbit와 비슷한 표기 계층을 둘 수 있음
- 다만 버전별 응답 필드 차이는 남아 있을 수 있으므로 metadata fetcher에서 version pinning 필요

#### Coinone

- market string 한 개가 아니라 `quote_currency`, `target_currency`의 쌍으로 표현되는 경우가 많음
- 내부적으로는 `BTC/KRW`로 정규화하고, adapter outbound 단계에서 두 필드로 분리
- private/public REST와 WS 모두 이 쌍 기반 모델을 기본으로 둔다

### 43.3 Precision 규약

정밀도는 세 층으로 나눈다.

- `price_tick_size`
- `qty_step_size`
- `min_notional`

추가 필드:

- `price_precision`
- `qty_precision`
- `min_qty`
- `max_qty`

규칙:

- 주문 생성 전 `price`는 `price_tick_size`에 맞춰 normalize
- `qty`는 `qty_step_size`에 맞춰 floor normalize
- normalize 이후 `price * qty >= min_notional` 검증
- normalize 결과가 원본 intent와 크게 다르면 주문 차단 후 decision record에 사유 기록

### 43.4 Upbit Precision 메모

- KRW 마켓 호가 단위와 최소 주문 가능 금액 정책은 공식 문서에서 별도 표로 관리됨
- 가격 구간에 따라 tick size가 달라지는 구간형 정책이므로 정적 소수점 자리수만으로 처리하면 안 된다
- KRW/BTC/USDT 마켓별 정책이 다를 수 있으므로 market class별 policy resolver 필요

설계 원칙:

- Upbit adapter는 `tick_policy_resolver(exchange, market_type, price)` 함수를 별도 모듈로 둔다
- 정책 변경일이 공지되는 경우 effective date를 포함한 버전화 필요

### 43.5 Bithumb Precision 메모

- 빗썸도 마켓별 최소 주문 수량/금액, 허용 가격 단위가 있을 수 있으므로 주문 전 metadata source로 검증 필요
- 공식 문서 또는 서비스 정보 API가 충분하지 않으면 운영 테이블로 보정할 수 있어야 한다

설계 원칙:

- Bithumb precision은 초기에는 운영 관리 테이블을 허용
- 다만 최종 source of truth는 공식 문서 또는 안정적인 metadata endpoint로 전환

### 43.6 Coinone Precision 메모

- Coinone public orderbook/주문 API는 문자열 기반 숫자 필드를 많이 사용
- 소수점 처리 시 float 사용 금지
- `Decimal` 기반 normalize가 필수

설계 원칙:

- Coinone adapter는 모든 수치 필드를 문자열로 파싱 후 `Decimal` 변환
- `quote_currency`, `target_currency`별 min/max 및 precision 정책은 symbol metadata에 귀속

### 43.7 수수료 모델 규약

전략 손익 계산에는 최소 세 종류 수수료가 필요하다.

- `maker_fee_rate`
- `taker_fee_rate`
- `withdraw_fee`

추가 고려:

- 프로모션/회원등급/이벤트 수수료
- 주문별 실제 체결 수수료
- quote asset 기준 수수료인지 base asset 기준 수수료인지 여부

정규화 원칙:

- 전략의 예상 손익은 `configured_fee_rate`
- 사후 손익과 reconciliation은 `executed_fee`
- 거래소 응답에 fee_rate와 fee amount가 모두 있으면 amount를 우선 신뢰

### 43.8 수수료 Source of Truth

권장 우선순위:

1. 주문/체결 응답의 실제 수수료 값
2. 계정/거래소 API가 제공하는 사용자 적용 수수료율
3. 운영자가 관리하는 config 기본값

금지 규칙:

- 문서에 적힌 일반 수수료율만으로 실제 PnL을 확정하지 않는다
- 거래소 프로모션 수수료를 코드 상수로 박아두지 않는다

### 43.9 Symbol Metadata 저장 제안

추가 테이블 제안:

- `instrument_metadata`
  - `id`
  - `exchange`
  - `exchange_symbol`
  - `canonical_symbol`
  - `base_asset`
  - `quote_asset`
  - `price_tick_policy_json`
  - `qty_step_size`
  - `min_qty`
  - `min_notional`
  - `maker_fee_rate`
  - `taker_fee_rate`
  - `active`
  - `last_verified_at`

## 44. Order Reconciliation Job 상세 설계

실거래에서는 REST 응답, private websocket 이벤트, DB 기록이 항상 완전히 일치하지 않는다.  
따라서 주문 정합성을 주기적으로 복구하는 reconciliation job이 필요하다.

### 44.1 목적

- 주문 상태 유실 복구
- fill 누락 복구
- partial fill 후 잔량 불일치 복구
- REST와 WS 간 상태 충돌 정리

### 44.2 입력 소스

- `orders`
- `trade_fills`
- `order_intents`
- private websocket event cache
- 거래소 REST order detail / open orders / completed orders

### 44.3 실행 트리거

- 주기 실행: 예를 들어 5초, 15초, 60초 티어
- 이벤트 기반 실행: WS disconnect, order timeout, fill mismatch
- 수동 실행: 운영자 요청

### 44.4 우선순위 큐

우선 복구 대상:

- `submitted` 상태가 오래 지속되는 주문
- partial fill 이후 업데이트가 멈춘 주문
- order intent 총 체결 수량과 order fill 합계가 맞지 않는 경우
- hedge leg 불균형이 존재하는 strategy run

### 44.5 핵심 알고리즘

1. 복구 후보 주문 집합 선택
2. 거래소별 bulk 조회 가능 시 bulk 조회 우선
3. 각 주문에 대해 raw 상태, 체결 수량, 잔량, 수수료, 최근 업데이트 시각 비교
4. DB와 차이가 있으면 append-only event 생성
5. 상태 승격 또는 정정 반영
6. 포지션/strategy run aggregate 재계산

### 44.6 상태 충돌 해결 규칙

우선순위:

1. 체결 내역 존재
2. 최신 거래소 REST order detail
3. private websocket 최신 event
4. 기존 DB 상태

해석 규칙:

- `filled`는 terminal 상태로 우선
- `cancelled`와 `filled`가 충돌하면 체결 수량 기준으로 분해 판단
- terminal 이후 non-terminal 상태가 오면 raw event는 저장하되 내부 상태는 되돌리지 않는다

### 44.7 이벤트 저장 규칙

추가 테이블 제안:

- `order_reconciliation_events`
  - `id`
  - `order_id`
  - `exchange`
  - `reason`
  - `before_state_json`
  - `after_state_json`
  - `raw_payload_json`
  - `created_at`

### 44.8 알림 규칙

다음은 alert를 발생시킨다.

- terminal 상태 불일치
- fill amount 불일치
- fee amount 불일치
- 2회 이상 복구 시도 후에도 상태 불명
- hedge pair 간 체결 불균형

## 45. Position Unwind Engine 상세 설계

차익거래 전략에서 가장 위험한 상황은 한쪽 거래만 체결되고 반대편 hedge가 실패하는 경우다.  
이를 자동으로 줄이기 위한 unwind engine을 별도 책임으로 둔다.

### 45.1 목적

- 단일 거래소 노출을 빠르게 축소
- 의도하지 않은 방향성 포지션 축소
- 운영자 개입 전 1차 안전장치 제공

### 45.2 진입 조건

- 한 leg만 `filled` 또는 `partially_filled`
- 반대 leg가 `rejected`, `failed`, `expired`
- hedge leg latency가 허용치 초과
- net exposure가 전략 허용 범위를 초과

### 45.3 입력

- `positions`
- `orders`
- `trade_fills`
- latest orderbook snapshot
- configured unwind policy

### 45.4 unwind 정책 유형

- `immediate_market_exit`
- `aggressive_limit_exit`
- `timeboxed_requote_then_market`
- `manual_only`

초기 MVP 권장:

- 기본값은 `timeboxed_requote_then_market`
- 고위험 bot은 `immediate_market_exit`
- dry-run은 `manual_only`

### 45.5 기본 알고리즘

1. 순노출 자산과 수량 계산
2. 현재 시장 가격과 slippage budget 계산
3. unwind policy에 따라 주문 생성
4. 일정 시간 내 미체결이면 재호가 또는 시장가 탈출
5. 종료 후 residual exposure 재계산
6. 완전 해소 실패 시 `critical` alert

### 45.6 보호 규칙

- stale orderbook 상태에서 시장가 unwind 금지 여부를 정책화
- balance snapshot stale이면 신규 전략 진입 금지, unwind는 별도 예외 규칙 적용
- 동일 포지션에 대해 중복 unwind 주문 생성 금지
- operator 수동 개입 중에는 자동 unwind 중단 옵션 제공

### 45.7 기록 규칙

모든 unwind 시도는 decision record와 별도 trace를 남긴다.

추가 테이블 제안:

- `unwind_actions`
  - `id`
  - `strategy_run_id`
  - `position_id`
  - `policy`
  - `trigger_reason`
  - `exposure_before_json`
  - `action_order_intent_id`
  - `result_status`
  - `exposure_after_json`
  - `created_at`

### 45.8 운영 알림

다음은 즉시 알림 대상이다.

- unwind engine 진입
- market exit 수행
- residual exposure가 기준 초과
- 2회 이상 unwind 실패
- manual handoff 필요 상태 전환

## 46. Frontend API Query Contract 초안

웹 UI는 백엔드의 내부 테이블 구조를 그대로 알면 안 된다.  
프론트엔드는 화면 단위의 read model을 기준으로 질의하고, 백엔드는 필요한 join/aggregate를 미리 구성해 응답한다.

### 46.1 공통 규칙

- 모든 목록 API는 cursor pagination을 기본으로 한다
- 시간 필터는 `from`, `to` UTC ISO8601 사용
- 정렬 기본값은 `created_at desc`
- 프론트엔드는 snake_case raw field보다 화면용 view model을 우선 사용
- enum 문자열은 DB enum과 동일하게 유지하되 label 변환은 UI에서 처리

### 46.2 공통 응답 메타

목록 응답 표준:

```json
{
  "items": [],
  "next_cursor": "opaque-cursor",
  "has_more": true
}
```

단건 응답 표준:

```json
{
  "data": {}
}
```

에러 응답 표준:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "human readable message",
    "request_id": "req_123"
  }
}
```

### 46.3 Dashboard Query Contract

권장 endpoint:

- `GET /api/v1/dashboard/summary`

응답 필드:

- `total_bots`
- `running_bots`
- `degraded_bots`
- `paused_bots`
- `critical_alert_count_1h`
- `orders_today`
- `fills_today`
- `failed_orders_today`
- `decision_latency_p95_ms`
- `order_ack_latency_p95_ms`
- `exchange_status`

`exchange_status` 예시:

```json
[
  {
    "exchange": "upbit",
    "public_market_data": "healthy",
    "private_api": "healthy",
    "private_ws": "degraded",
    "last_checked_at": "2026-04-04T10:15:00Z"
  }
]
```

### 46.4 Bot List / Bot Detail Query Contract

목록 endpoint:

- `GET /api/v1/bots`

주요 필터:

- `status`
- `run_mode`
- `exchange`
- `strategy_type`

목록 item view model:

- `bot_id`
- `bot_name`
- `strategy_type`
- `run_mode`
- `status`
- `canonical_symbols`
- `latest_heartbeat_at`
- `freshness_state`
- `latest_alert_level`

상세 endpoint:

- `GET /api/v1/bots/{bot_id}`
- `GET /api/v1/bots/{bot_id}/timeline`

상세 view model:

- bot 기본 정보
- 현재 config version
- 현재 strategy run 요약
- 최근 heartbeats
- 최근 alerts
- 최근 decision records
- connector health

### 46.5 Strategy Run Query Contract

목록 endpoint:

- `GET /api/v1/strategy-runs`

필터:

- `bot_id`
- `status`
- `from`
- `to`

상세 endpoint:

- `GET /api/v1/strategy-runs/{run_id}`

상세 응답:

- `run_id`
- `bot_id`
- `status`
- `started_at`
- `ended_at`
- `degraded_reason`
- `current_position_summary`
- `latest_decision_records`
- `latest_order_intents`
- `latest_alerts`

### 46.6 Order / Fill Explorer Query Contract

목록 endpoint:

- `GET /api/v1/orders`
- `GET /api/v1/fills`
- `GET /api/v1/order-intents`

필터:

- `bot_id`
- `exchange`
- `canonical_symbol`
- `status`
- `strategy_run_id`
- `from`
- `to`

중요 응답 필드:

- `order_id`
- `order_intent_id`
- `exchange_order_id`
- `exchange`
- `canonical_symbol`
- `side`
- `status`
- `requested_price`
- `requested_qty`
- `filled_qty`
- `avg_fill_price`
- `fee_amount`
- `internal_error_code`
- `created_at`
- `updated_at`

단건 상세는 아래 연결 데이터를 포함한다.

- 원본 intent
- 관련 fills
- reconciliation 이벤트
- 관련 decision record

### 46.7 Alert Center Query Contract

목록 endpoint:

- `GET /api/v1/alerts`

필터:

- `level`
- `exchange`
- `bot_id`
- `acknowledged`
- `from`
- `to`

추가 mutation:

- `POST /api/v1/alerts/{alert_id}/ack`

view model:

- `alert_id`
- `level`
- `category`
- `title`
- `message`
- `bot_id`
- `exchange`
- `created_at`
- `acknowledged_at`
- `acknowledged_by`

### 46.8 Config / Audit Query Contract

권장 endpoint:

- `GET /api/v1/configs`
- `GET /api/v1/configs/{version_id}`
- `GET /api/v1/audit-events`

Config detail 응답:

- `version_id`
- `schema_version`
- `created_by`
- `created_at`
- `change_summary`
- `assigned_bots`
- `config_json`

Audit event 응답:

- `event_id`
- `actor_id`
- `actor_role`
- `action`
- `target_type`
- `target_id`
- `payload_json`
- `created_at`

### 46.9 프론트엔드 캐시 키 제안

React Query 또는 동등한 query client 기준:

- `["dashboard", "summary"]`
- `["bots", filters]`
- `["bot", botId]`
- `["bot", botId, "timeline"]`
- `["strategy-runs", filters]`
- `["strategy-run", runId]`
- `["orders", filters]`
- `["fills", filters]`
- `["alerts", filters]`
- `["configs"]`
- `["config", versionId]`
- `["audit-events", filters]`

### 46.10 프론트엔드 실시간 업데이트 정책

- Dashboard, Bot Detail, Alert Center는 polling + server sent events 또는 websocket을 병행 가능
- 초기 MVP는 polling 우선
- 권장 polling 주기:
  - dashboard: 5초
  - bot detail: 3초
  - alerts: 5초
  - orders/fills explorer: 10초
- mutation 성공 시 관련 query만 선택적으로 invalidate

## 47. 운영자 장애 대응 플레이북 심화판

운영자는 장애 유형별로 같은 판단을 반복하지 않도록 표준 절차를 가져야 한다.

### 47.1 장애 등급

- `sev-1`: live 손실 위험 또는 자동매매 전면 중단
- `sev-2`: 일부 bot 거래 불가 또는 정합성 훼손 가능성 높음
- `sev-3`: 기능 일부 저하, 우회 가능
- `sev-4`: 관찰성/표시 문제

### 47.2 공통 초동 대응

1. Dashboard에서 영향 범위 확인
2. sev-1 또는 sev-2면 신규 진입 차단 여부 먼저 판단
3. 최근 alert, bot heartbeat, exchange connector health 확인
4. 관련 strategy run, order intent, order 상태 확인
5. raw error payload와 최근 reconciliation 이벤트 확인

### 47.3 장애 유형별 우선 절차

#### A. 거래소 Public WS 단절

1. connector 상태가 `degraded`로 전환되었는지 확인
2. REST fallback 동작 여부 확인
3. freshness SLA 초과 시 신규 주문 차단 확인
4. 재연결 backoff 루프가 정상인지 확인
5. 장기 단절 시 해당 거래소 사용 bot을 `paused` 또는 `degraded` 유지

#### B. 거래소 Private API 인증 실패

1. 특정 bot만 영향인지 전체 계정 영향인지 구분
2. key rotation 또는 IP 제한 변경 이력 확인
3. 최근 secret reference 변경 여부 확인
4. auth 실패가 지속되면 live 주문 차단
5. 필요 시 admin이 새 secret version 배포

#### C. 주문 제출 후 상태 미확정

1. exchange order id 생성 여부 확인
2. private WS event 수신 여부 확인
3. REST order detail 조회 수행
4. reconciliation job 수동 실행
5. terminal 상태 확정 전까지 동일 의도의 재주문 금지

#### D. 한쪽 leg만 체결

1. current exposure와 손실 위험 계산
2. unwind engine 자동 진입 여부 확인
3. 자동 unwind 실패 시 operator가 manual handoff 수행
4. 이후 동일 bot 신규 진입 일시 차단
5. incident record와 postmortem 후보로 표시

#### E. DB 또는 Redis 장애

1. control plane write path 영향 범위 확인
2. event bus 적재 실패 여부 확인
3. 전략 worker가 fail-closed 되었는지 확인
4. 정합성 훼손 가능 시 전체 live 신규 주문 중지
5. 복구 후 reconciliation full scan 수행

### 47.4 즉시 중단 기준

아래 조건 중 하나면 해당 bot 또는 전체 시스템의 신규 진입을 즉시 중단한다.

- private auth 실패 지속
- balance snapshot stale 지속
- orderbook freshness 실패 지속
- hedge mismatch 누적
- DB write 실패 또는 reconciliation backlog 급증
- 동일 exchange에서 terminal 상태 불일치 반복

### 47.5 장애 기록 표준

모든 sev-1/sev-2 장애는 아래를 남긴다.

- `incident_id`
- 발생 시각
- 감지 경로
- 영향 범위
- 최초 증상
- 초동 대응
- 최종 원인
- 손실 또는 미체결 영향
- 재발 방지 항목

추가 테이블 제안:

- `incident_events`
  - `id`
  - `severity`
  - `status`
  - `title`
  - `summary`
  - `detected_at`
  - `resolved_at`
  - `owner`
  - `payload_json`

### 47.6 사후 검토 기준

아래 중 하나에 해당하면 postmortem 작성 대상이다.

- 실제 금전 손실 발생
- unwind engine 실패
- live bot 10분 이상 중단
- 거래소 auth 정책 변경을 사전 탐지하지 못함
- reconciliation job이 terminal 상태 불일치를 복구하지 못함

## 48. 현재 문서 기준 전체 설계 상태 재평가

이번 보강 이후의 주관적 진행 상태는 다음과 같다.

- PRD / 제품 방향: 95%
- 상위 아키텍처: 90%
- DB 모델: 85%
- API / UI 계약: 85%
- 운영 / 관찰성 / 장애 대응: 90%
- 거래소 adapter 공통 설계: 85%
- 거래소별 구현 계약: 65%
- 웹 UI 상세 설계: 75%

해석:

- 이제 이 문서는 "착수 전 상위 설계 문서" 수준은 넘었다
- 실제 구현 팀은 backend, frontend, infra, exchange adapter 작업을 병렬로 나눌 수 있다
- 가장 큰 잔여 리스크는 거래소별 공식 문서 pinning과 실제 live smoke 검증이다

## 49. Strategy Parameter Catalog 초안

초기 제품은 현물 차익거래 전략을 기준으로 시작하되, 전략 파라미터를 명시적으로 분리해서 저장한다.  
전략 구현 코드는 임의의 dict를 읽지 않고, 검증된 typed config만 받도록 설계한다.

### 49.1 전략 파라미터 분류

권장 분류:

- 시장 데이터 freshness
- 진입 조건
- 주문 생성 정책
- hedge 정책
- unwind 정책
- 리스크 한도
- 운영 모드

### 49.2 공통 파라미터

- `strategy_type`
- `enabled`
- `run_mode`
- `base_exchange`
- `hedge_exchange`
- `canonical_symbol`
- `poll_interval_ms`
- `decision_interval_ms`
- `dry_run`
- `shadow_mode`

설계 규칙:

- `run_mode`와 `dry_run`은 중복 표현이므로 최종 구현에서는 하나의 필드 체계로 정리
- `base_exchange`와 `hedge_exchange`는 동일 거래소 금지
- `canonical_symbol`은 `instrument_metadata`에 존재해야 함

### 49.3 시장 데이터 / freshness 파라미터

- `max_orderbook_age_ms`
- `max_balance_age_ms`
- `max_private_event_age_ms`
- `max_clock_skew_ms`
- `min_orderbook_depth_levels`

권장 초기값 예시:

- `max_orderbook_age_ms`: 1500
- `max_balance_age_ms`: 5000
- `max_private_event_age_ms`: 5000
- `max_clock_skew_ms`: 1000
- `min_orderbook_depth_levels`: 5

검증 규칙:

- 모든 age 값은 0보다 커야 함
- `max_balance_age_ms`는 `max_orderbook_age_ms`보다 작을 수 없음
- `min_orderbook_depth_levels`는 1 이상

### 49.4 진입 조건 파라미터

- `min_expected_profit_bps`
- `min_expected_profit_quote`
- `max_spread_bps`
- `min_available_depth_quote`
- `max_slippage_bps`
- `max_entry_frequency_per_minute`

권장 해석:

- `min_expected_profit_bps`: 수수료와 예상 슬리피지 반영 후 최소 기대 수익률
- `min_expected_profit_quote`: 절대 금액 기준 최소 기대 수익
- `max_spread_bps`: 비정상 스프레드 환경 차단용 상한

검증 규칙:

- `min_expected_profit_bps`는 음수 금지
- `max_slippage_bps`는 전략 허용 범위 내의 작은 값으로 제한
- `max_entry_frequency_per_minute`는 1 이상

### 49.5 주문 생성 파라미터

- `order_type_preference`
- `maker_only`
- `order_timeout_ms`
- `reprice_attempt_limit`
- `reprice_interval_ms`
- `cancel_on_signal_loss`

권장 enum:

- `order_type_preference`: `limit`, `market`, `limit_then_market`

검증 규칙:

- `maker_only=true`이면 `order_type_preference=market` 금지
- `reprice_attempt_limit`는 0 이상
- `order_timeout_ms`는 `decision_interval_ms`보다 충분히 커야 함

### 49.6 hedge / unwind 파라미터

- `hedge_required`
- `hedge_timeout_ms`
- `max_leg_latency_ms`
- `unwind_policy`
- `unwind_timeout_ms`
- `max_unwind_slippage_bps`

권장 enum:

- `unwind_policy`: `immediate_market_exit`, `aggressive_limit_exit`, `timeboxed_requote_then_market`, `manual_only`

검증 규칙:

- `hedge_required=true`이면 `max_leg_latency_ms` 필수
- `unwind_timeout_ms`는 `hedge_timeout_ms` 이상 권장
- `manual_only`는 `run_mode=live`에서 고위험 bot의 기본값으로 금지 가능

### 49.7 운영 파라미터

- `alert_cooldown_sec`
- `pause_on_reconciliation_failure`
- `pause_on_auth_failure`
- `pause_on_balance_stale`
- `max_consecutive_failures`

검증 규칙:

- `max_consecutive_failures`는 1 이상
- `alert_cooldown_sec`는 0 이상
- 운영 중단성 옵션은 기본값을 보수적으로 잡는다

### 49.8 파라미터 버전 관리 원칙

- strategy config는 schema version을 가진다
- 의미가 바뀌는 필드 변경은 breaking change로 간주
- deprecated 파라미터는 즉시 제거하지 말고 migration path를 문서화
- config diff는 필드 단위로 저장하고 UI에서 시각화 가능해야 함

## 50. Risk Limit Spec 초안

리스크 한도는 전략 로직 내부 if문으로 흩어지면 안 된다.  
별도 정책 객체로 평가하고, 위반 시 주문 생성 이전에 fail-closed 한다.

### 50.1 리스크 한도 분류

- bot 단위
- 거래소 단위
- 심볼 단위
- 전략 run 단위
- 시스템 전역

### 50.2 필수 한도

- `max_notional_per_order`
- `max_notional_per_symbol`
- `max_total_notional_per_bot`
- `max_net_exposure_quote`
- `max_open_orders`
- `max_daily_loss_quote`
- `max_daily_loss_bps`
- `max_reconciliation_backlog`
- `max_unwind_attempts`

### 50.3 bot 단위 한도

- 단일 bot이 동시에 가질 수 있는 총 노출 금액 제한
- bot별 최대 open order 수 제한
- bot별 연속 실패 횟수 상한

권장 예시:

- `max_total_notional_per_bot`
- `max_open_orders`
- `max_consecutive_failures`

### 50.4 거래소 단위 한도

- 특정 거래소 전체 노출 상한
- 특정 거래소 auth 장애 시 신규 주문 전면 차단
- 특정 거래소 rate limit 초과가 누적되면 cooldown

필드 예시:

- `max_notional_per_exchange`
- `cooldown_on_auth_failure_sec`
- `cooldown_on_rate_limit_sec`

### 50.5 심볼 단위 한도

- `BTC/KRW` 같은 특정 심볼 총 노출 제한
- 특정 심볼 변동성 급증 시 진입 차단

필드 예시:

- `max_notional_per_symbol`
- `max_daily_trades_per_symbol`
- `max_short_term_volatility_bps`

### 50.6 손실 한도

손실 한도는 실현 손실과 미실현 노출 둘 다 고려해야 한다.

- `max_daily_loss_quote`
- `max_daily_loss_bps`
- `max_unrealized_loss_quote`
- `max_unrealized_loss_bps`

트리거 규칙:

- 손실 한도 초과 시 해당 bot 신규 진입 차단
- 중대한 초과 시 전체 strategy run `paused`
- 연속 손실과 손실 금액을 함께 본다

### 50.7 운영 안정성 한도

- `max_orderbook_gap_events`
- `max_balance_stale_events`
- `max_private_ws_disconnects_per_hour`
- `max_reconciliation_backlog`

의미:

- 시장 데이터나 운영 상태가 불안정하면 수익 기회가 있어도 거래하지 않는다
- 안정성 한도는 financial limit와 동일한 우선순위로 평가

### 50.8 리스크 평가 순서

1. 시스템 전역 중단 조건
2. 거래소 건강 상태
3. 데이터 freshness
4. 심볼 거래 가능 상태
5. bot 단위 한도
6. 전략별 기대 수익 조건
7. 주문 생성 가능 여부

원칙:

- 앞 단계 실패 시 뒤 단계 평가 생략 가능
- 위반 사유는 모두 decision record에 남긴다

### 50.9 리스크 위반 표준 코드

- `RISK_MAX_NOTIONAL_EXCEEDED`
- `RISK_MAX_NET_EXPOSURE_EXCEEDED`
- `RISK_MAX_OPEN_ORDERS_EXCEEDED`
- `RISK_DAILY_LOSS_EXCEEDED`
- `RISK_DATA_FRESHNESS_FAILED`
- `RISK_CONNECTOR_UNHEALTHY`
- `RISK_RECONCILIATION_BACKLOG_HIGH`
- `RISK_UNWIND_IN_PROGRESS`

## 51. Config Schema / Validation Spec 초안

Control Plane은 사람이 읽기 쉬운 config를 받되, runtime에는 강한 validation을 통과한 결과만 배포한다.

### 51.1 권장 schema 계층

- `global_config`
- `exchange_profiles`
- `risk_profiles`
- `strategy_templates`
- `bot_instances`

의미:

- 전역 정책과 bot 개별 설정을 분리
- 공통 위험 한도는 profile로 재사용
- bot은 template + override 조합으로 생성

### 51.2 예시 구조

```yaml
schema_version: 1
global_config:
  environment: production
  timezone: UTC
exchange_profiles:
  upbit_main:
    exchange: upbit
    account_ref: secret://exchange/upbit/main
risk_profiles:
  conservative_krw:
    max_notional_per_order: "300000"
    max_daily_loss_quote: "50000"
strategy_templates:
  spot_arb_krw_btc:
    strategy_type: spot_arbitrage
    canonical_symbol: BTC/KRW
    min_expected_profit_bps: 12
bot_instances:
  arb_upbit_bithumb_btc_01:
    template: spot_arb_krw_btc
    base_exchange_profile: upbit_main
    hedge_exchange_profile: bithumb_main
    risk_profile: conservative_krw
```

### 51.3 validation 단계

1. schema validation
2. enum / type validation
3. cross-field validation
4. external reference validation
5. dry-run compile

### 51.4 필수 검증 규칙

- `schema_version` 존재
- bot 이름과 식별자는 고유
- exchange profile reference가 실제 존재
- 동일 bot에서 base/hedge 거래소 중복 금지
- symbol이 `instrument_metadata`에 존재
- risk limit가 음수 금지
- live 모드 bot은 필수 운영 옵션 누락 금지

### 51.5 cross-field validation 예시

- `maker_only=true`이면 market-only 정책 금지
- `dry_run=true`이면 live 전용 승인 필드 불필요
- `unwind_policy=manual_only`이면 특정 리스크 프로필에서는 금지 가능
- `max_total_notional_per_bot >= max_notional_per_order`
- `max_daily_loss_quote`가 0이면 live 실행 금지 가능

### 51.6 compile 단계의 의미

config compile 결과는 runtime에서 즉시 사용할 내부 스냅샷이다.

권장 산출물:

- resolved exchange references
- resolved risk profile
- resolved symbol metadata
- normalized decimals
- derived limits
- validation warnings

### 51.7 배포 승인 규칙

- validation error가 하나라도 있으면 배포 금지
- warning만 있는 config는 staging/dry-run만 허용 가능
- production assignment는 승인 이벤트와 audit log를 남긴다

### 51.8 Config Validation 실패 표준 코드

- `CONFIG_SCHEMA_INVALID`
- `CONFIG_REFERENCE_NOT_FOUND`
- `CONFIG_DUPLICATE_BOT_ID`
- `CONFIG_INVALID_EXCHANGE_PAIR`
- `CONFIG_INVALID_RISK_LIMIT`
- `CONFIG_SYMBOL_NOT_SUPPORTED`
- `CONFIG_LIVE_GUARD_FAILED`

## 52. 현재 문서 기준 다음 구현 묶음 제안

이 문서를 기준으로 실제 새 프로젝트를 시작한다면, 초기 구현 묶음은 다음처럼 나누는 것이 합리적이다.

### 52.1 Backend Core

- config schema / compiler
- risk evaluator
- strategy runtime shell
- order intent / order / fill repository
- reconciliation job skeleton

### 52.2 Exchange Adapter

- Upbit public REST / public WS / private REST / private WS
- Bithumb public REST / public WS / private REST
- Coinone public REST / public WS / private REST / private WS
- 공통 auth / limiter / retry / error mapper

### 52.3 Control Plane / UI

- dashboard read model
- bot / strategy run / order explorer API
- config management API
- alerts / audit API
- Bot Overview / Bot Detail / Order Explorer 초기 화면

### 52.4 Infra / Ops

- PostgreSQL / Redis / migration
- logging / metrics / tracing
- notifier
- incident / alert pipeline

### 52.5 가장 먼저 닫아야 할 남은 공백

- 거래소별 공식 문서 버전 pinning
- instrument metadata source 확정
- fee source of truth 확정
- secret manager 방식 확정
- live mode 승인 체계 확정

## 53. 주차별 Execution Plan 초안

이 섹션은 새 프로젝트를 8주 기준으로 처음 세팅하는 실행 계획 초안이다.  
실제 인력 수와 우선순위에 따라 6주 또는 10주로 압축/확장할 수 있다.

### 53.1 전체 원칙

- 주문 실행보다 read path와 안전장치를 먼저 완성
- live mode는 마지막 단계까지 열지 않음
- 각 주차는 "작동하는 좁은 slice"를 남겨야 함
- backend, frontend, infra, exchange adapter는 가능한 한 병렬 진행

### 53.2 Week 1: 기반 골격

목표:

- repository scaffold
- FastAPI 기본 앱
- PostgreSQL / Redis / Alembic 초기 세팅
- structured logging / metrics 골격
- config schema 초안

완료 기준:

- health endpoint 동작
- DB migration 1회 성공
- logging / metrics endpoint 확인
- config validation CLI 또는 내부 API 동작

### 53.3 Week 2: Core Domain + Read Path

목표:

- bots / strategy_runs / heartbeats / alerts schema 반영
- dashboard summary read model
- bot list / bot detail API
- 초기 UI shell

완료 기준:

- UI에서 bot 목록/상세 조회 가능
- alert와 heartbeat가 DB에 기록되고 조회 가능
- audit event 기본 기록 가능

### 53.4 Week 3: Market Data Connector

목표:

- Upbit public REST / WS
- Bithumb public REST / WS
- Coinone public REST / WS
- orderbook normalization
- instrument metadata 관리 방식 확정

완료 기준:

- 세 거래소 orderbook이 내부 표준 모델로 수집됨
- freshness 판단 가능
- connector health가 dashboard에 표시됨

### 53.5 Week 4: Private API + Config Compiler

목표:

- private balance adapter
- auth provider / limiter / retry 공통 모듈
- config compiler / risk profile / strategy template 반영
- config management API

완료 기준:

- 세 거래소 중 최소 2곳에서 private balance 성공
- config compile 결과가 DB에 versioned 저장
- invalid config 배포 차단 확인

### 53.6 Week 5: Strategy Runtime + Dry Run

목표:

- strategy worker shell
- decision record 생성
- risk evaluator
- order intent 생성
- dry-run end-to-end 연결

완료 기준:

- 실주문 없이 decision record와 order intent 생성
- freshness 실패/리스크 초과 시 fail-closed 확인
- Bot Detail에서 최근 전략 판단 흐름 조회 가능

### 53.7 Week 6: Order Execution + Reconciliation

목표:

- 실주문 adapter
- order / fill persistence
- reconciliation job
- order explorer UI

완료 기준:

- 최소 1개 거래소에서 테스트 주문 생성/조회/취소 성공
- REST/WS 상태 차이를 reconciliation이 복구
- order explorer에서 intent-order-fill 연결 조회 가능

### 53.8 Week 7: Hedge / Unwind / Alerts

목표:

- hedge latency tracking
- unwind engine
- incident / alert pipeline 강화
- operator actions UI

완료 기준:

- 한쪽 leg만 체결되는 시나리오에서 unwind 정책 동작
- critical alert가 UI와 notifier에 동시에 반영
- pause/resume, ack, config assignment 감사 로그 기록

### 53.9 Week 8: Shadow 운영 준비

목표:

- staging/shadow 환경 검증
- live smoke test 절차 정리
- runbook 최종 보강
- production gate 정의

완료 기준:

- shadow mode로 7일 운영 가능한 체크리스트 확보
- 주요 장애 대응 플레이북 검토 완료
- live enable 승인 절차 문서화 완료

## 54. 팀별 병렬 작업선 제안

### 54.1 Backend Core

- domain model
- repositories
- config compiler
- risk evaluator
- strategy runtime

### 54.2 Exchange Adapter

- Upbit adapter
- Bithumb adapter
- Coinone adapter
- 공통 auth / limiter / websocket supervisor

### 54.3 Frontend

- app shell
- dashboard
- bot detail
- order explorer
- alert center
- config viewer

### 54.4 Infra / Ops

- database / redis / migration pipeline
- logging / metrics / tracing
- deployment
- notifier / incident pipeline

### 54.5 작업 경계 원칙

- frontend는 DB 스키마가 아니라 read API contract만 의존
- strategy runtime은 거래소 raw payload가 아니라 normalized adapter output만 의존
- adapter 팀은 UI 요구사항을 몰라도 되고, 공통 internal contract만 맞추면 됨
- infra 팀은 business logic을 몰라도 배포/관찰성/비밀관리 계약만 맞추면 됨

## 55. 단계별 Exit Criteria

각 단계는 "구현 완료"가 아니라 "다음 단계로 넘어가도 안전한가"로 판정한다.

### 55.1 Core Exit Criteria

- migration 반복 실행 가능
- config validation 실패가 명확히 드러남
- health / metrics / logs 기본 관찰 가능

### 55.2 Market Data Exit Criteria

- 세 거래소 최소 1개 심볼 이상 정상 수집
- stale detection 동작
- reconnect / backoff 관찰 가능

### 55.3 Private API Exit Criteria

- auth 실패와 rate limit이 내부 표준 코드로 매핑됨
- balance snapshot이 저장되고 freshness 판단 가능
- secret rotation 절차 초안 완료

### 55.4 Dry Run Exit Criteria

- decision record 생성
- risk limit 차단 동작
- dry-run에서 intent 생성까지 end-to-end 동작

### 55.5 Execution Exit Criteria

- 최소 1개 거래소에서 테스트 주문 lifecycle 성공
- reconciliation이 상태 불일치 1종 이상 복구
- order/fill read model이 UI에 노출

### 55.6 Shadow Exit Criteria

- shadow mode 연속 운영
- sev-1 / sev-2 미발생
- alert noise가 허용 기준 이하
- 운영자가 runbook만 보고 주요 장애에 대응 가능

## 56. 현재 문서의 실무 활용 방법

이 문서는 단순 설명서가 아니라, 다음 세 가지 용도로 바로 쓸 수 있다.

### 56.1 아키텍처 기준서

- 어떤 기술 스택을 쓰는지
- 어떤 경계를 분리하는지
- 무엇을 먼저 만들고 무엇을 나중에 여는지

### 56.2 구현 계약서

- backend와 frontend의 API 계약
- strategy와 adapter의 내부 계약
- 운영과 보안의 승인 규칙

### 56.3 초기 PM 문서

- MVP 범위
- 리스크
- 주차별 계획
- 종료 기준

권장 다음 산출물:

- `implementation_tasks.md`
- `exchange_contract_upbit.md`
- `exchange_contract_bithumb.md`
- `exchange_contract_coinone.md`
- `frontend_wireframes.md`

## 57. 문제 우선순위 재정리

이 섹션은 기존 운영 경험과 현재 PRD의 요구사항을 기준으로, 무엇을 먼저 막아야 하는지 실무 우선순위로 다시 정리한 것이다.

### 57.1 P0: 자산 손실 또는 잘못된 주문으로 이어질 수 있는 문제

- stale orderbook 또는 stale balance를 정상 데이터로 오인하는 문제
- 주문 후 체결/잔고 재검증이 늦거나 누락되어 편측 포지션을 놓치는 문제
- 실행 모드 경계가 불명확해 dry-run, shadow, live가 섞이는 문제
- 설정 변경이 검증 없이 반영되어 위험 파라미터가 즉시 적용되는 문제

### 57.2 P1: 운영 불능 또는 장애 확산으로 이어질 수 있는 문제

- process alive만 보고 기능 alive를 놓치는 문제
- 알림, heartbeat, health, audit trail이 약해 운영자가 즉시 개입하지 못하는 문제
- 외부 거래소 장애가 전체 시스템 지연 또는 재시도 폭주로 번지는 문제
- 운영 명령의 승인 경계가 약해 실수로 중지, 재시작, 설정 반영이 수행되는 문제

### 57.3 P2: 구현 속도와 변경 안전성을 떨어뜨리는 문제

- 전략, 어댑터, 저장소, 운영 API의 책임이 섞이는 문제
- 읽기 모델과 쓰기 모델이 섞여 조회 요구가 쓰기 경로를 오염시키는 문제
- 거래소별 차이를 공통 계약 없이 처리해 새 거래소 추가 비용이 커지는 문제
- 상태 전이와 이벤트 규약이 약해 테스트와 재현이 어려워지는 문제

### 57.4 P3: 후속 확장을 지연시키는 문제

- UI, 백테스트, 리플레이, RBAC, SLO가 뒤늦게 덧붙는 문제
- 초기 문서와 실제 구현 계약이 분리되어 팀 간 해석 차이가 커지는 문제

## 58. 현재 운영 경험에서 반드시 계승할 강점

이 문서는 새 시스템을 처음부터 다시 만드는 문서지만, 기존 운영에서 이미 가치가 증명된 아래 원칙은 그대로 가져가야 한다.

### 58.1 데이터 품질 우선

- 주문장 freshness를 엄격하게 본다.
- 잔고 최신성과 주문장 최신성을 분리해서 판단한다.
- 거래 기회를 놓치더라도 잘못된 데이터로 주문하지 않는다.

### 58.2 운영자 가시성 우선

- keep-alive는 프로세스 생존과 기능 생존을 구분해서 본다.
- 운영자는 현재 상태, 설정 버전, 최근 주문, 이상 이벤트를 즉시 볼 수 있어야 한다.
- 알림과 관제는 부가 기능이 아니라 제품 기본 기능으로 둔다.

### 58.3 안전한 실행 모드

- dry-run, shadow, live를 제품 모델의 일부로 유지한다.
- live 진입 전에는 반드시 shadow 운영과 검증 단계를 둔다.
- 운영 명령은 감사 가능해야 하고, 위험 명령은 승인 경계를 둔다.

### 58.4 재현 가능성과 버전 관리

- 설정은 버전 단위로 관리한다.
- 주문 의사결정 근거는 재현 가능해야 한다.
- 핵심 동작은 로그, 메트릭, 이벤트로 남겨 사후 분석이 가능해야 한다.

## 59. 주요 리스크와 롤백 전략

### 59.1 문서 단계의 주요 리스크

| 리스크 | 영향 | 완화 전략 |
|---|---|---|
| 거래소 상세 계약이 늦어짐 | 구현 시작 후 어댑터별 재작업 증가 | 32, 34, 35, 36, 43절을 먼저 닫고 공통 인터페이스를 고정 |
| UI 요구가 중간에 커짐 | Control Plane 범위가 흔들림 | 30, 33, 41, 46절의 초기 UI 비목표를 유지 |
| 운영 보안 요구가 뒤늦게 강화됨 | 배포 직전 auth/RBAC 재설계 | 39절 기준으로 민감 동작 보호 규칙을 먼저 확정 |
| 전략 파라미터와 리스크 한도가 늦게 확정됨 | shadow 이후 live 진입 지연 | 49, 50, 51절을 live 전 필수 종료 조건으로 둠 |

### 59.2 구현 단계 롤백 원칙

- migration은 전진 전용으로 관리하고 destructive change는 명시적 승인 없이는 넣지 않는다.
- live 관련 기능은 dry-run, shadow와 분리된 플래그와 상태 전이로 감싼다.
- 거래소 어댑터는 공통 인터페이스 뒤에 두고, 특정 거래소 구현 실패가 전체 구조 변경으로 번지지 않게 한다.
- 운영 명령과 config deploy는 audit log를 남기고, 직전 안정 버전으로 되돌릴 수 있어야 한다.

## 60. 문제-요구사항-구현 단계 역추적 표

현재 문서에 흩어진 요구사항을 실무 추적용으로 묶으면 아래와 같다.

| 문제 묶음 | 핵심 대응 요구사항 | 우선 구현 단계 |
|---|---|---|
| stale data, 잘못된 주문 | 11.2 Strategy Worker, 12.1 안정성, ADR-003, ADR-004, 49절, 50절 | Step 1, Step 4, Step 5 |
| 운영자 가시성 부족 | 11.1 Control Plane, 11.4 운영 인터페이스, 23절, 25절, 47절 | Step 2, Step 3 |
| 실행 모드 혼선 | 11.5 실행 모드, ADR-005, 38절 상태 전이, 25.7 운영 모드 전환 규칙 | Step 5, Step 6, Step 7 |
| 거래소별 구현 차이와 오류 처리 | 11.3 Exchange Adapter, 32절, 34절, 35절, 36절, 43절 | Step 4 |
| 설정 오류와 위험 파라미터 반영 | 20절 migration 정책, 22절 decision record, 39절, 49절, 51절 | Step 1, Step 2 |
| 편측 포지션 및 사후 정합성 | 15절 스키마, 19절 event 규약, 38절 상태 전이, 44절, 45절 | Step 3, Step 5, Step 7 |
| UI와 운영 화면 범위 팽창 | 30절, 33절, 41절, 46절 | MVP 이후 또는 Step 7 병행 |

### 60.1 이 표의 사용 방법

- 새 구현 태스크를 만들 때는 반드시 위 표의 문제 묶음 하나와 연결한다.
- 연결되지 않는 작업은 지금 범위 밖인지, 아니면 요구사항이 빠졌는지 먼저 판단한다.
- live 전환 승인 시에는 P0, P1에 해당하는 행이 모두 닫혔는지 확인한다.
