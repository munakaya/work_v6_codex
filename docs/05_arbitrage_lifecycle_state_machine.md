# Arbitrage Lifecycle State Machine

이 문서는 재정거래 판단 이후 상태가 어떻게 흘러야 하는지 정한다.
핵심 목적은 `accept`를 "수익 실현 완료"로 오해하는 문제를 막고, 언제 recovery로 넘어가야 하는지를 fail-closed로 고정하는 것이다.


## 핵심 원칙

- `accept`는 기회 발견이지 성공 종료가 아니다.
- 신규 진입 판단과 실주문 이후 복구 판단은 같은 상태로 섞지 않는다.
- 한 symbol, 한 bot 기준으로 active entry는 하나만 유지한다.
- `recovery_required`가 되면 신규 진입은 막고 복구를 먼저 본다.


## 이 문서의 범위

이 문서는 개념 상태 전이를 다룬다.
즉, PostgreSQL enum이나 단일 DB 컬럼을 바로 바꾸자는 뜻이 아니다.

현재 구현에서는 아래를 조합해서 상태를 읽는다.

- `strategy_runs.status`
- `order_intents.status`
- `orders.status`
- `trade_fills`
- `alert_events`
- `unwind_actions` 또는 TODO(verify) recovery trace


## 권장 개념 상태

### 1. `decision_rejected`

- 의미:
  - gate, risk, executable profit, reservation 중 하나에서 진입이 막힘
- 근거:
  - decision record 존재
  - `decision.reason_code != ARBITRAGE_OPPORTUNITY_FOUND`
- 후속:
  - 신규 진입 판단 가능

### 2. `decision_accepted`

- 의미:
  - 실행 가능 수익과 reservation까지 통과
  - 아직 order intent 생성 전 또는 생성 직후
- 근거:
  - `decision.reason_code = ARBITRAGE_OPPORTUNITY_FOUND`
  - reservation passed
- 주의:
  - 이 상태만으로는 포지션 안전을 보장하지 않는다

### 3. `intent_created`

- 의미:
  - 양 leg order intent가 생성됨
  - 아직 거래소 제출 전
- 근거:
  - 관련 `order_intents` 존재
  - status는 `created` 또는 `simulated`
- 후속:
  - execution 계층이 submit 담당

### 4. `entry_submitting`

- 의미:
  - 한쪽 또는 양쪽 leg가 거래소 제출 중
- 근거:
  - `orders`가 생겼지만 terminal 상태 아님
  - `order_intents.status = submitted` 또는 대응 raw event 존재
- 주의:
  - 가장 위험한 전이 시작점

### 5. `entry_open`

- 의미:
  - 한쪽 또는 양쪽 leg가 partial/open 상태
  - 순노출 가능성이 열려 있음
- 근거:
  - `orders.status in (new, partially_filled)`
- 후속:
  - fill imbalance, timeout, hedge latency를 지속 감시

### 6. `hedge_balanced`

- 의미:
  - 양 leg 체결 결과가 전략 허용 오차 내에서 균형
- 근거:
  - 두 leg fill 합계와 순노출이 허용 범위 이내
  - recovery 조건 미충족
- 주의:
  - 이 상태가 되어야 entry가 정상 종료로 본다

### 7. `recovery_required`

- 의미:
  - 신규 진입을 더 보면 안 되고 복구 판단을 우선해야 함
- 진입 조건:
  - 한 leg fill, 반대 leg reject/expired/failed
  - hedge timeout 초과
  - residual exposure 초과
  - reconciliation mismatch 지속
- 후속:
  - 신규 진입 차단
  - unwind 또는 manual handoff 결정

### 8. `unwind_in_progress`

- 의미:
  - recovery 엔진이 복구 주문을 생성했고 아직 종료 안 됨
- 근거:
  - unwind action active
  - 또는 recovery trace active
- 후속:
  - 신규 진입 금지
  - 종료 후 exposure 재평가

### 9. `closed`

- 의미:
  - 정상 종료 또는 복구 종료 후 순노출이 해소됨
- 근거:
  - 모든 관련 주문 terminal
  - residual exposure 허용 범위 이내
  - active unwind 없음

### 10. `manual_handoff`

- 의미:
  - 자동 판단으로 더 진행하면 위험
- 진입 조건:
  - unwind 반복 실패
  - stale 상태에서 market exit 금지 정책
  - 거래소 상태 이상으로 자동 해소 불가
- 후속:
  - 운영자 확인 전 신규 진입 금지


## 상태 전이 규칙

기본 흐름:

1. `decision_rejected`
2. `decision_accepted`
3. `intent_created`
4. `entry_submitting`
5. `entry_open`
6. `hedge_balanced`
7. `closed`

위험 흐름:

1. `decision_accepted`
2. `intent_created`
3. `entry_submitting`
4. `entry_open`
5. `recovery_required`
6. `unwind_in_progress`
7. `closed` 또는 `manual_handoff`


## 우선순위 규칙

여러 신호가 동시에 보이면 아래 상태가 더 강하다.

1. `manual_handoff`
2. `unwind_in_progress`
3. `recovery_required`
4. `entry_open`
5. `entry_submitting`
6. `hedge_balanced`
7. `intent_created`
8. `decision_accepted`
9. `decision_rejected`
10. `closed`

원칙:

- 위험 상태가 안전 상태를 덮는다.
- `closed`는 마지막 정리 상태이지, 중간 강한 상태를 덮는 근거가 아니다.
- `closed`는 active entry나 recovery 증거가 하나도 남지 않았을 때만 선택한다.
- terminal order 하나만 보고 `closed`로 내리면 안 된다.


## fail-closed 규칙

- `recovery_required`, `unwind_in_progress`, `manual_handoff` 중 하나면 신규 진입 금지
- `entry_open`이 오래 지속되면 자동으로 `recovery_required` 평가
- decision record가 accept여도 hedge 균형 전에는 성공으로 집계하지 않음
- order intent 하나가 `submitted`여도 반대편 leg 증거가 없으면 `entry_submitting`으로 유지


## 구현 힌트

상태는 새 테이블을 바로 만들기보다 파생 계산으로 먼저 구현하는 편이 안전하다.

권장 함수:

1. `derive_arbitrage_lifecycle_state`
2. `detect_recovery_required`
3. `compute_residual_exposure`
4. `classify_terminal_outcome`

권장 배치:

- `src/trading_platform/strategy/arbitrage_state_machine.py`
- `src/trading_platform/strategy/arbitrage_recovery_guard.py`


## 구현 체크리스트

- accept를 성공 종료로 집계하지 않는다.
- recovery 상태에서는 duplicate intent 차단보다 먼저 신규 진입을 막는다.
- `hedge_balanced`와 `closed`를 같은 뜻으로 쓰지 않는다.
- 운영 화면은 decision 결과와 lifecycle 상태를 구분해서 보여준다.
- validation case 추가 시 정상 흐름과 recovery 흐름을 둘 다 만든다.
