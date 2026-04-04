# Arbitrage Runtime Invariants

이 문서는 재정거래 전략 런타임에서 항상 지켜야 하는 불변조건을 정한다.
목적은 알고리즘이 맞아 보여도 운영 중 상태 오염, 중복 진입, 노출 누락이 생기는 문제를 fail-closed로 막는 것이다.


## 핵심 원칙

- invariant 위반은 "조용한 보정"보다 먼저 감지하고 기록한다.
- invariant가 깨지면 신규 진입보다 상태 보존과 복구가 우선이다.
- 한 번의 좋은 판단보다, 깨진 상태를 빨리 찾는 편이 더 중요하다.


## 범위

이 문서는 재정거래 진입 판단 이후의 런타임 불변조건을 다룬다.
즉, `decision_context`, `order_intents`, `orders`, `trade_fills`, `reservation`, `lifecycle state`가 서로 모순되지 않아야 한다.

코드 이름은 `05_arbitrage_invariant_code_catalog.md`를 따른다.


## P0 불변조건

### I1. active entry uniqueness

대표 `invariant_code`:

- `ARB_INV_ACTIVE_ENTRY_UNIQUENESS`

- 같은 `bot_id + canonical_symbol`에 active entry는 하나만 있어야 한다.
- 아래 상태 중 하나라도 있으면 active로 본다.
  - `decision_accepted`
  - `intent_created`
  - `entry_submitting`
  - `entry_open`
  - `recovery_required`
  - `unwind_in_progress`

위반 시:

- 신규 진입 즉시 차단
- 신규 판단 단계라면 `DUPLICATE_INTENT_BLOCKED` 재사용 가능
- 이미 런타임 진입 후라면 별도 invariant alert를 남김

### I2. accept without reservation 금지

대표 `invariant_code`:

- `ARB_INV_ACCEPT_WITHOUT_RESERVATION`

- `decision.reason_code = ARBITRAGE_OPPORTUNITY_FOUND`이면 `reservation.reservation_passed = true`여야 한다.
- reservation이 false 또는 누락이면 accept로 보면 안 된다.

위반 시:

- accept 집계 금지
- 상태는 `recovery_required` 또는 `manual_handoff`

### I3. intent/order market consistency

대표 `invariant_code`:

- `ARB_INV_INTENT_ORDER_MARKET_MISMATCH`

- `order.market`은 linked `order_intent.market`과 같아야 한다.
- `order.exchange_name`은 linked intent의 `buy_exchange` 또는 `sell_exchange` 중 하나여야 한다.
- 재정거래 쌍의 양 leg는 서로 다른 거래소여야 한다.

위반 시:

- 신규 submit 금지
- 신규 판단/submit 직전 단계라면 `ORDER_VALIDATION_FAILED` 재사용 가능
- 이미 제출 후 발견되면 critical alert와 recovery 판단 우선

### I4. fill quantity upper bound

대표 `invariant_code`:

- `ARB_INV_FILL_QTY_EXCEEDED`

- 한 주문의 fill 합계는 `requested_qty`를 넘으면 안 된다.
- 허용 오차가 필요하면 수치로 문서화해야 한다. 현재는 0으로 본다.

위반 시:

- fill 반영 자체는 `FILL_VALIDATION_FAILED`로 거절 가능
- reconciliation 우선 실행

### I5. residual exposure visibility

대표 `invariant_code`:

- `ARB_INV_RESIDUAL_EXPOSURE_UNKNOWN`

- `entry_open`, `recovery_required`, `unwind_in_progress` 중 하나면 residual exposure를 계산할 수 있어야 한다.
- 계산 불가 상태를 정상으로 넘기면 안 된다.

위반 시:

- 신규 진입 금지
- `manual_handoff` 우선 검토


## P1 불변조건

### I6. lifecycle / order terminal consistency

대표 `invariant_code`:

- `ARB_INV_CLOSED_WITH_ACTIVE_EXECUTION`

- lifecycle이 `closed`면 관련 주문은 모두 terminal이어야 한다.
- active unwind가 남아 있으면 `closed`가 될 수 없다.

### I7. reject / side-effect consistency

대표 `invariant_code`:

- `ARB_INV_REJECT_WITH_SIDE_EFFECT`

- 대표 decision이 reject면 신규 order intent draft가 생기면 안 된다.
- reject 후 side-effect가 있다면 별도 recovery trace로 남겨야 한다.

### I8. hedge balance claim consistency

대표 `invariant_code`:

- `ARB_INV_HEDGE_BALANCE_CLAIM_FALSE`

- lifecycle이 `hedge_balanced`면 순노출이 허용 범위 이내여야 한다.
- 양 leg 체결 수량 차이가 허용 오차를 넘으면 `hedge_balanced`로 두면 안 된다.

### I9. reason code / lifecycle consistency

대표 `invariant_code`:

- `ARB_INV_REASON_LIFECYCLE_CONFLICT`

- `decision_rejected`와 `decision_accepted`는 동시에 성립하면 안 된다.
- `recovery_required` 상태에서는 decision accept 여부보다 recovery signal이 더 강하다.


## P2 불변조건

### I10. config immutability during active entry

대표 `invariant_code`:

- `ARB_INV_CONFIG_CHANGED_DURING_ACTIVE_ENTRY`

- active entry 동안 linked config version은 바뀌지 않는 편이 안전하다.
- 바뀌어야 한다면 기존 entry와 새 entry를 명확히 분리해야 한다.

### I11. metric/accounting consistency

대표 `invariant_code`:

- `ARB_INV_METRIC_ACCOUNTING_CONFLICT`

- accept count, submit count, filled count, unwind count는 같은 run/window에서 역전되면 안 된다.
- 예:
  - filled > submitted
  - submitted > accepted + replay restored TODO(verify)


## 권장 감지 방식

1. decision 직후 검사
2. order submit 직후 검사
3. fill 반영 직후 검사
4. reconciliation job 직후 검사
5. runtime summary API 또는 alert evaluator에서 주기 검사

원칙:

- "나중에 reconciliation이 맞춰주겠지"를 기본 전제로 두지 않는다.


## 권장 산출물

불변조건 위반 시 최소한 아래를 남긴다.

- `invariant_code`
- `severity`
- `bot_id`
- `strategy_run_id`
- `order_intent_id`
- `order_id`
- `detected_at`
- `before_state`
- `observed_values`
- `suggested_action`


## 권장 코드 배치

- `src/trading_platform/strategy/arbitrage_invariants.py`
- `src/trading_platform/strategy/arbitrage_runtime_assertions.py`


## 구현 체크리스트

- invariant 위반은 warn만 찍고 지나가지 않는다.
- P0 위반은 신규 진입 차단과 연결한다.
- lifecycle state 계산과 invariant 계산은 같은 입력 기준으로 실행한다.
- validation case 외에 invariant violation case를 따로 만든다.
- recovery 문서와 충돌하면 invariant를 완화하지 말고 왜 충돌하는지 먼저 확인한다.
