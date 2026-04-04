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

- PostgreSQL, Redis 연결과 market data / strategy runtime 상태 포함 준비 상태 확인
- `strategy_runtime`에는 evaluation/persist/submit 카운터와 execution 모드(`simulate_success`, `simulate_failure`, `simulate_fill`, `private_stub`, `private_http`)도 포함
- `strategy_runtime`에는 현재 연결된 execution adapter 이름도 포함
- `recovery_runtime`에는 active trace 처리, submit-timeout watchdog, terminal evaluation close sync, auto resolve, manual handoff 승격 카운터가 포함
- `strategy_runtime.execution_mode=private_http`이고 execution이 켜져 있으면 `dependencies.private_execution`도 함께 검사
- 이때 `TP_STRATEGY_PRIVATE_EXECUTION_HEALTH_URL`이 없거나 health probe가 실패하면 ready는 `degraded`

### 18.3 Bot API

#### `GET /api/v1/recovery-traces`

목적:

- Redis runtime에 기록된 active recovery trace를 조회

주요 query:

- `bot_id`
- `run_id`
- `status`
- `lifecycle_state`
- `limit`

#### `GET /api/v1/recovery-traces/{recovery_trace_id}`

목적:

- recovery trace 단건 상세 조회

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/resolve`

목적:

- operator가 recovery trace를 `resolved`로 종료

요청 핵심 필드:

- `resolution_reason`
- `residual_exposure_quote` (`0`일 때만 resolve 허용)
- `verified_by`
- `summary`

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/handoff`

목적:

- operator가 recovery trace를 `manual_handoff` 상태로 승격

요청 핵심 필드:

- `handoff_reason`
- `verified_by`
- `summary`
- `operator_context`

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/start-unwind`

목적:

- operator가 recovery trace를 다시 `unwind_in_progress` 상태로 전환

요청 핵심 필드:

- `unwind_reason`
- `residual_exposure_quote` (주면 0 이상 숫자여야 함)
- `create_unwind_intent` (선택, true면 linked unwind intent 생성)
- `market`, `buy_exchange`, `sell_exchange`, `side_pair`, `target_qty`
  - `create_unwind_intent=true`일 때 필수
- `verified_by`
- `summary`
- `operator_context`

응답 핵심 필드:

- `lifecycle_state=unwind_in_progress`
- `linked_unwind_action_id`
- `created_unwind_intent` (`create_unwind_intent=true`일 때)

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/submit-unwind-order`

목적:

- operator가 linked unwind intent 아래 실제 unwind order를 생성

요청 핵심 필드:

- `exchange_name`
- `market`
- `side`
- `requested_qty`
- `requested_price` (선택)
- `exchange_order_id` (선택)

응답 핵심 필드:

- `lifecycle_state=unwind_in_progress`
- `linked_unwind_order_id`
- `created_unwind_order`

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/record-unwind-fill`

목적:

- operator가 linked unwind order에 실제 unwind fill을 기록
- recovery runtime이 즉시 돌면 `resolved / closed`까지 바로 반영될 수 있음

요청 핵심 필드:

- `exchange_trade_id`
- `fill_price`
- `fill_qty`
- `filled_at`
- `fee_asset` (선택)
- `fee_amount` (선택, 주면 0 이상 숫자여야 함)

응답 핵심 필드:

- `created_unwind_fill`
- `status`
- `lifecycle_state`
- `latest_evaluation`

#### `POST /api/v1/recovery-traces/{recovery_trace_id}/record-reconciliation`

목적:

- operator 또는 reconciliation job이 recovery trace에 정합성 결과를 기록
- `matched + open_order_count=0 + residual_exposure_quote=0`이면 recovery runtime이 즉시 `resolved / closed`까지 반영할 수 있음
- 단, 위 자동 종료 후보는 `observed_at`이 있어야 함
- `matched` 또는 `mismatch` reconciliation인데 `open_order_count`, `residual_exposure_quote`, `observed_at` 핵심 필드가 깨져 있거나 `observed_at`이 미래 시각이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `mismatch` reconciliation인데 `reconciliation_mismatch_streak`가 잘못된 값이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `reconciliation_result` 값 자체가 `matched` 또는 `mismatch`가 아니면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `reconciliation_result`가 없는데 다른 `reconciliation_*` 필드만 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- 단, 위 `matched` 결과라도 `observed_at`이 너무 오래됐으면 recovery runtime이 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 `observed_at`이 없으면 recovery runtime이 `manual_handoff`로 올릴 수 있음
- `mismatch + open_order_count=0 + residual_exposure_quote>0`이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `mismatch`가 같은 trace에서 반복되면 threshold 이후 `manual_handoff`로 승격될 수 있음
- `matched` 또는 `mismatch` reconciliation인데 `observed_order_ids`, `observed_fill_ids`, `observed_order_statuses`, `observed_balances` 중 하나라도 형식이 깨져 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `mismatch + open_order_count>0`이어도 `observed_order_statuses`가 전부 실패 terminal이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `mismatch + open_order_count>0`인데 `observed_order_statuses`가 전부 terminal이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `mismatch + open_order_count=0`인데 `observed_order_statuses`가 non-terminal이면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 `observed_fill_ids`, `observed_order_statuses`, `observed_balances`가 전부 비어 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `observed_order_ids`만 있는 경우는 자동 종료 근거로 보지 않음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 trace에 `intent` 문맥이 없거나, 관련 거래소 두 곳을 모두 식별할 수 없으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 trace에 `market` 자산 문맥이 없어 관련 자산을 식별할 수 없으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 `observed_order_statuses`에 `failed/cancelled/rejected/expired` 같은 실패 terminal 상태가 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 `observed_order_statuses`에 `submitted/new/partially_filled` 같은 non-terminal 상태가 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 `observed_balances`가 관련 거래소의 관련 자산을 전부 덮지 못하면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`인데 관련 거래소/자산이 있는 trace에서 `observed_balances` 자체가 없으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음
- `matched + open_order_count=0 + residual_exposure_quote=0`이어도 `observed_balances`에 관련 거래소의 관련 자산 locked 잔고가 남아 있으면 recovery runtime이 즉시 `manual_handoff`로 올릴 수 있음

요청 핵심 필드:

- `matched` (필수, true/false)
- `open_order_count` (필수, 0 이상 정수)
- `residual_exposure_quote` (필수, 0 이상 숫자)
- `reconciliation_reason` (선택)
- `observed_at` (선택, ISO datetime)
- `observed_order_ids` (선택, unique non-empty string 배열)
- `observed_fill_ids` (선택, unique non-empty string 배열)
- `observed_order_statuses` (선택, unique `{order_id, status}` 배열)
- `observed_balances` (선택, `{exchange_name, asset, free, locked}` 배열, `(exchange_name, asset)` 중복 금지)
- `summary` (선택)
- `source` (선택)
- `verified_by` (선택)
- `operator_context` (선택)

응답 핵심 필드:

- `reconciliation_result`
- `reconciliation_open_order_count`
- `reconciliation_residual_exposure_quote`
- `reconciliation_observed_at`
- `reconciliation_observed_order_ids`
- `reconciliation_observed_fill_ids`
- `reconciliation_observed_order_statuses`
- `reconciliation_observed_balances`
- `reconciliation_attempt_count`
- `reconciliation_mismatch_count`
- `reconciliation_mismatch_streak`
- `status`
- `lifecycle_state`
- `latest_evaluation`

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

#### `POST /api/v1/strategy-runs/{run_id}/evaluate-arbitrage`

목적:

- arbitrage strategy run에 대해 실행 가능 수익, gate, reservation을 평가
- `persist_intent=true`일 때만 accept 결과를 `order_intent`로 저장
- `execute=true`면 저장된 intent를 현재 execution adapter로 바로 실행
- background strategy runtime이 켜져 있으면 같은 평가 결과가 Redis latest evaluation cache에도 주기적으로 반영될 수 있음

요청 핵심 필드:

- `canonical_symbol`
- `market`
- `base_exchange`
- `hedge_exchange`
- `base_orderbook`
- `hedge_orderbook`
- `base_balance`
- `hedge_balance`
- `risk_config`
  - `slippage_buffer_bps` optional
  - `unwind_buffer_quote` optional
  - `rebalance_buffer_quote` optional
  - `taker_fee_bps_buy` optional
  - `taker_fee_bps_sell` optional
- `runtime_state`
- `persist_intent` optional boolean
- `execute` optional boolean

응답 핵심 필드:

- `bot_id`
- `strategy_run_id`
- `accepted`
- `reason_code`
- `lifecycle_preview`
- `decision_context`
- `candidate_size`
- `executable_edge`
  - `gross_profit_quote`
  - `fee_buy_quote`
  - `fee_sell_quote`
  - `buy_slippage_buffer_quote`
  - `sell_slippage_buffer_quote`
  - `unwind_buffer_quote`
  - `rebalance_buffer_quote`
  - `total_cost_adjustment_quote`
- `reservation_plan`
- `submit_failure_preview`
- `persisted_intent` optional

주의:

- `persist_intent=false`면 read-only backend에서도 평가만 가능
- `persist_intent=true`인데 backend가 read-only면 `STORE_MUTATION_UNAVAILABLE`
- `execute=true`면 `persist_intent=true`가 필수
- `execute=true`인데 strategy runtime execution이 꺼져 있으면 `STRATEGY_EXECUTION_DISABLED`
- 성공 시 `strategy.arbitrage_evaluated` event를 남긴다
- `persist_intent=true`로 저장되면 `strategy.arbitrage_intent_persisted` event를 추가로 남긴다

#### `GET /api/v1/strategy-runs/latest-evaluations`

목적:

- Redis runtime에 저장된 최신 arbitrage 평가 snapshot을 run 기준으로 모아 조회

필터:

- `limit`
- `bot_id`
- `accepted`
- `lifecycle_preview`
- `reason_code`
- `stale_after_seconds`
- `stale_only`

응답 핵심 필드:

- `bot_id`
- `strategy_run_id`
- `accepted`
- `reason_code`
- `lifecycle_preview`
- `recovery_trace_id` optional
- `recovery_status` optional
- `recovery_lifecycle_state` optional
- `recovery_updated_at` optional
- `cached_at`
- `count`
- `matched_count`
- `accepted_count`
- `rejected_count`
- `unique_bot_count`
- `newest_cached_at`
- `oldest_cached_at`
- `stale_after_seconds`
- `stale_count`
- `reason_code_counts`
- `lifecycle_preview_counts`
- item별 `cached_age_seconds`
- item별 `is_stale`

주의:

- Redis runtime이 꺼져 있으면 `REDIS_RUNTIME_UNAVAILABLE`
- Redis read 실패 시 `REDIS_RUNTIME_READ_FAILED`
- `accepted`는 `true|false`만 허용
- `stale_after_seconds`는 0 이상 정수만 허용
- `stale_only=true`면 `stale_after_seconds`를 같이 줘야 함

#### `GET /api/v1/strategy-runs/{run_id}/latest-evaluation`

목적:

- Redis runtime에 저장된 run 기준 최신 arbitrage 평가 snapshot 조회

응답 핵심 필드:

- `bot_id`
- `strategy_run_id`
- `accepted`
- `reason_code`
- `lifecycle_preview`
- `recovery_trace_id` optional
- `recovery_status` optional
- `recovery_lifecycle_state` optional
- `recovery_updated_at` optional
- `decision_context`
- `cached_at`
- `persisted_intent` optional

주의:

- Redis runtime이 꺼져 있으면 `REDIS_RUNTIME_UNAVAILABLE`
- 아직 평가가 없으면 `STRATEGY_EVALUATION_NOT_FOUND`

#### `GET /api/v1/strategy-runs/{run_id}`

목적:

- strategy run 상태 조회

### 18.7 Orders / Fills API

#### `GET /api/v1/order-intents`

목적:

- dry-run, shadow, live 전반의 의사결정 기록 조회

`decision_context` 최소 계약:

- `decision_id`
- `quote_pair_id`
- `computed.executable_profit_quote`
- `computed.executable_profit_bps`
- `computed.gross_profit_quote`
- `computed.depth_passed`
- `computed.buy_depth_levels`
- `computed.sell_depth_levels`
- `computed.buy_depth_notional_quote`
- `computed.sell_depth_notional_quote`
- `computed.fee_buy_quote`
- `computed.fee_sell_quote`
- `computed.buy_slippage_buffer_quote`
- `computed.sell_slippage_buffer_quote`
- `computed.unwind_buffer_quote`
- `computed.rebalance_buffer_quote`
- `computed.total_cost_adjustment_quote`
- `reservation.reservation_passed`
- `reason_code`

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
  "decision_context": {
    "decision_id": "uuid",
    "observed_at": "2026-04-03T14:13:00Z",
    "computed": {
      "executable_profit_quote": "1432.01",
      "executable_profit_bps": "11.67"
    },
    "decision": {
      "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND"
    }
  },
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
- `GET /api/v1/strategy-runs/latest-evaluations`
- `GET /api/v1/strategy-runs/{run_id}/latest-evaluation`
- `POST /api/v1/strategy-runs/{run_id}/evaluate-arbitrage`
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

- `exchange`: 현재 `upbit`, `bithumb`, `coinone`, `sample` 지원
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
- poll interval 기본값은 `3000ms`

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
- `limit`: 선택. `1`~`5`, 정렬/필터 후 상위 N개만 반환
- `include_empty`: 선택. 기본 `true`, `false`면 길이가 0인 stream은 제외
- `status`: 선택. `empty`, `fresh`, `stale` 중 하나
- `stale_only`: 선택. 기본 `false`, `true`면 stale stream만 반환
- `sort_by`: 선택. `stream_name`, `length`, `newest_age_seconds` 중 하나, 기본 `stream_name`
- `order`: 선택. `asc` 또는 `desc`, 기본 `asc`
- `stale_after_seconds`: 선택. 기본 `300`

응답 핵심 필드:

- `count`
- `matched_count`
- `non_empty_count`
- `total_length`
- `stale_after_seconds`
- `stale_count`
- `stale_only`
- `status`
- `status_counts`
- `overall_status`
- `limit`
- `has_more`
- `sort_by`
- `order`
- `stream_name`
- `length`
- `newest_age_seconds`
- `is_stale`
- `status`
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
