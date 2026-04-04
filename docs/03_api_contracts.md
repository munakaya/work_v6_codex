# API Contracts

이 문서는 Control Plane API 계약과 OpenAPI 초안을 모은다. 백엔드 구현과 프론트엔드 연동 시 source of truth로 사용한다.


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

- PostgreSQL, Redis 연결과 market data runtime 상태 포함 준비 상태 확인

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

#### Public Market Data

- `GET /api/v1/market-data/orderbook-top`
- `GET /api/v1/market-data/orderbook-top/cached`
- `GET /api/v1/market-data/runtime`
- `GET /api/v1/market-data/snapshots`
- `GET /api/v1/market-data/events`
- `POST /api/v1/market-data/poll`

#### Bots

- `POST /api/v1/bots/register`
- `GET /api/v1/bots`
- `GET /api/v1/bots/events`
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
- `GET /api/v1/strategy-runs/events`
- `GET /api/v1/strategy-runs/{run_id}`
- `POST /api/v1/strategy-runs/{run_id}/start`
- `POST /api/v1/strategy-runs/{run_id}/stop`

#### Orders and Fills

- `GET /api/v1/order-intents`
- `GET /api/v1/order-intents/{intent_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/events`
- `GET /api/v1/orders/{order_id}`
- `GET /api/v1/fills`

#### Alerts

- `GET /api/v1/alerts`
- `GET /api/v1/alerts/events`
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

#### `GET /api/v1/market-data/orderbook-top`

쿼리:

- `exchange`: 현재 `upbit`, `sample` 지원
- `market`: 예시 `KRW-BTC`

응답:

```json
{
  "success": true,
  "data": {
    "exchange": "upbit",
    "market": "KRW-BTC",
    "best_bid": "101574000",
    "best_ask": "101598000",
    "bid_volume": "0.00035401",
    "ask_volume": "0.00623162",
    "exchange_timestamp": "2026-04-04T01:19:53.387000Z",
    "received_at": "2026-04-04T01:19:53.512000Z",
    "exchange_age_ms": 125,
    "stale": false,
    "source_type": "rest"
  },
  "error": null
}
```

#### `GET /api/v1/market-data/orderbook-top/cached`

쿼리:

- `exchange`: 예시 `sample`, `upbit`
- `market`: 예시 `KRW-BTC`

응답:

```json
{
  "success": true,
  "data": {
    "exchange": "sample",
    "market": "KRW-BTC",
    "best_bid": "101574000",
    "best_ask": "101598000",
    "bid_volume": "0.00035401",
    "ask_volume": "0.00623162",
    "exchange_timestamp": "2026-04-04T01:31:15.272709Z",
    "received_at": "2026-04-04T01:31:15.272727Z",
    "exchange_age_ms": 0,
    "stale": false,
    "source_type": "sample"
  },
  "error": null
}
```

#### `GET /api/v1/market-data/runtime`

목적:

- poller runtime 상태와 Redis에 남아 있는 최신 snapshot 확인

응답 핵심 필드:

- `runtime.enabled`
- `runtime.state`
- `runtime.exchange`
- `runtime.markets`
- `runtime.last_success_at`
- `runtime.last_error_message`
- `snapshots`
- `snapshot_count`

#### `GET /api/v1/market-data/snapshots`

목적:

- Redis에 남아 있는 cached market snapshot 목록 조회

쿼리:

- `limit`: 기본 20, 최대 100
- `exchange`: 선택
- `market`: 선택

#### `POST /api/v1/market-data/poll`

목적:

- 지정한 거래소/마켓의 최신 snapshot을 즉시 수집하고 Redis cache를 갱신

요청 핵심 필드:

- `exchange`
- `markets`

헤더:

- `X-Trace-Id`: 선택. 주면 생성되는 `market.orderbook_top.updated` 이벤트의 `trace_id`로 그대로 기록

#### `GET /api/v1/market-data/events`

쿼리:

- `limit`: 기본 20, 최대 100
- `before_stream_id`: 선택. 주면 그 stream id보다 오래된 이벤트부터 조회
- `event_type`: 선택
- `trace_id`: 선택
- `exchange`: 선택
- `market`: 선택

응답:

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "stream_id": "1775266477835-0",
        "event_id": "evt_xxx",
        "event_type": "market.orderbook_top.updated",
        "event_version": 1,
        "occurred_at": "2026-04-04T01:34:37.833672Z",
        "producer": "control-plane",
        "trace_id": null,
        "payload": {
          "exchange": "sample",
          "market": "KRW-BTC",
          "stale": false,
          "source_type": "sample",
          "exchange_age_ms": 0
        }
      }
    ],
    "count": 1,
    "has_more": false,
    "next_before_stream_id": null,
    "newest_stream_id": "1775266477835-0",
    "oldest_stream_id": "1775266477835-0"
  },
  "error": null
}
```

#### `GET /api/v1/runtime/streams`

목적:

- Redis runtime stream의 현재 길이와 oldest/newest 경계를 한 번에 확인

쿼리:

- `stream_name`: 선택. `market_events`, `bot_events`, `strategy_events`, `order_events`, `alert_events` 중 하나
- `include_empty`: 선택. 기본 `true`, `false`면 길이가 0인 stream은 제외

응답 핵심 필드:

- `stream_name`
- `length`
- `newest_stream_id`
- `newest_occurred_at`
- `oldest_stream_id`
- `oldest_occurred_at`

#### `GET /api/v1/bots/events`

쿼리:

- `limit`: 기본 20, 최대 100
- `before_stream_id`: 선택
- `event_type`: 선택
- `trace_id`: 선택
- `bot_id`: 선택
- `bot_key`: 선택

#### `GET /api/v1/strategy-runs/events`

쿼리:

- `limit`: 기본 20, 최대 100
- `before_stream_id`: 선택
- `event_type`: 선택
- `trace_id`: 선택
- `bot_id`: 선택
- `run_id`: 선택
- `config_scope`: 선택

#### `GET /api/v1/orders/events`

쿼리:

- `limit`: 기본 20, 최대 100
- `before_stream_id`: 선택
- `event_type`: 선택
- `trace_id`: 선택
- `bot_id`: 선택
- `order_id`: 선택
- `order_intent_id`: 선택
- `exchange_name` 또는 `exchange`: 선택

#### `GET /api/v1/alerts/events`

쿼리:

- `limit`: 기본 20, 최대 100
- `before_stream_id`: 선택
- `event_type`: 선택
- `trace_id`: 선택
- `bot_id`: 선택
- `alert_id`: 선택
- `level`: 선택

공통 응답 형태:

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "stream_id": "1775266477835-0",
        "event_id": "evt_xxx",
        "event_type": "bot.state.updated",
        "event_version": 1,
        "occurred_at": "2026-04-04T01:34:37.833672Z",
        "producer": "control-plane",
        "trace_id": null,
        "payload": {
          "bot_id": "uuid"
        }
      }
    ],
    "count": 1,
    "has_more": false,
    "next_before_stream_id": null,
    "newest_stream_id": "1775266477835-0",
    "oldest_stream_id": "1775266477835-0"
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
