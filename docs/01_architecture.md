# Architecture and System Boundaries

이 문서는 시스템 경계, 계층 구조, 상태 전이 같은 상위 설계를 모은다. 구현 전에 컴포넌트 책임과 데이터 흐름을 맞추는 기준으로 사용한다.


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
