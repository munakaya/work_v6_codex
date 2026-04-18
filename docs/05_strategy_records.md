# Strategy Records and ADRs

이 문서는 전략 의사결정 기록 형식과 전략 ADR을 모은다. 전략 방향, 의사결정 근거, 기록 규칙을 맞출 때 먼저 확인한다.


## 22. Strategy Decision Record Format

전략 품질을 검증하고 shadow/live 비교를 가능하게 하려면, 주문 결과뿐 아니라 "왜 주문하려 했는지"를 기록해야 한다.
이를 위해 `Strategy Decision Record`를 별도 포맷으로 정의한다.

### 22.1 목적

- 전략 판단 근거 기록
- dry-run / shadow / live 결과 비교
- 사후 분석과 튜닝 근거 확보
- 재현 가능한 디버깅 데이터 확보

### 22.2 필수 필드

초기 초안은 `best bid / best ask` 중심이었지만, 현재 권장 형식은 "실행 가능 수익"과 "왜 reject됐는지"가 더 직접 드러나야 한다.
즉, decision record는 단순 시세 스냅샷이 아니라 `gate check + executable simulation + reservation 결과`를 같이 남겨야 한다.

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
    "quote_pair_id": "upbit:bithumb:XRP-KRW:2026-04-03T14:13:00Z",
    "best_bid_sell_exchange": "1023.2",
    "best_ask_buy_exchange": "1018.4",
    "balance_buy_exchange_quote": "1200000",
    "balance_sell_exchange_base": "1500",
    "orderbook_age_ms": {
      "upbit": 120,
      "bithumb": 180
    },
    "clock_skew_ms": 60,
    "connector_health": {
      "upbit": "healthy",
      "bithumb": "healthy"
    }
  },
  "constraints": {
    "min_expected_profit_quote": "1000",
    "min_expected_profit_bps": "8",
    "max_order_notional": "500000",
    "max_orderbook_age_ms": 1000,
    "max_clock_skew_ms": 1000
  },
  "gate_checks": {
    "connector_health_passed": true,
    "orderbook_freshness_passed": true,
    "clock_skew_passed": true,
    "balance_freshness_passed": true,
    "symbol_tradeable_passed": true,
    "unwind_block_passed": true
  },
  "computed": {
    "target_qty": "120.5",
    "executable_buy_cost_quote": "122707.20",
    "executable_sell_proceeds_quote": "124139.21",
    "executable_profit_quote": "1432.01",
    "executable_profit_bps": "11.67",
    "unwind_buffer_quote": "210.00",
    "depth_passed": true,
    "profit_passed": true,
    "risk_passed": true
  },
  "reservation": {
    "buy_quote_reserved": "122707.20",
    "sell_base_reserved": "120.5",
    "risk_budget_reserved": true,
    "reservation_passed": true
  },
  "decision": {
    "action": "create_order_intent",
    "reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
    "reason_message": "profit and freshness conditions satisfied"
  }
}
```

### 22.3 reason_code 카탈로그

#### accept 계열

- `ARBITRAGE_OPPORTUNITY_FOUND`

#### reject 계열

- `ORDERBOOK_STALE`
- `QUOTE_PAIR_SKEW_TOO_HIGH`
- `BALANCE_STALE`
- `BALANCE_INSUFFICIENT`
- `PROFIT_TOO_LOW`
- `EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH`
- `RISK_LIMIT_BLOCKED`
- `RESERVATION_FAILED`
- `PUBLIC_CONNECTOR_DEGRADED`
- `HEDGE_CONFIDENCE_TOO_LOW`
- `REENTRY_COOLDOWN_ACTIVE`
- `CONFIG_DISABLED`
- `DUPLICATE_INTENT_BLOCKED`

운영 중 필요한 code가 더 생기더라도 아래 원칙은 유지한다.

- gate 실패 code와 수익 실패 code를 섞지 않는다.
- risk 실패 code와 reservation 실패 code를 섞지 않는다.
- unwind 진입 이후 failure는 신규 진입 reject code와 구분한다.

### 22.4 저장 위치

- 운영 분석용: PostgreSQL `order_intents.decision_context`
- 실시간 디버깅용: structured log
- 필요 시 object storage에 raw decision archive 저장 가능

### 22.5 기록 원칙 보강

- accept뿐 아니라 reject도 동일한 입력 구조를 남긴다.
- `reason_code`는 하나만 대표로 남기되, 세부 실패 항목은 `gate_checks`, `computed`, `reservation`에서 다시 읽을 수 있어야 한다.
- top-of-book 수익과 executable 수익이 다를 수 있으므로, 최종 판단은 항상 executable 필드 기준으로 해석한다.

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
