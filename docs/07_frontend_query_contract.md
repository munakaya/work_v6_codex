# Frontend Query Contract

이 문서는 프론트엔드가 Control Plane에서 어떤 조회 계약을 기대하는지 정의한다. 프론트엔드 구현과 백엔드 조회 API 조정 시 기준으로 사용한다.


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
