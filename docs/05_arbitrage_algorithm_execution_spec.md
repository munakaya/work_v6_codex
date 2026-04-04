# Arbitrage Algorithm Execution Spec

이 문서는 재정거래 핵심 알고리즘을 실제 구현 단위로 쪼갠 실행 스펙이다.
비판적 검토 문서가 "무엇이 위험한가"를 다룬다면, 이 문서는 "어떤 순서로 어떤 값을 계산할 것인가"를 다룬다.


## 목표

- 진입 판단을 top-of-book 비교가 아니라 실행 가능 수익 평가로 바꾼다.
- 판단 결과를 항상 `accept` 또는 `reject(reason_code)`로 남긴다.
- execution 계층에 넘기기 전 reserve 단계까지 포함해 fail-closed로 끝낸다.


## 입력

필수 입력:

- `strategy_run_id`
- `bot_id`
- `canonical_symbol`
- `base_exchange`
- `hedge_exchange`
- 두 거래소 latest orderbook snapshot
- 두 거래소 balance snapshot
- risk/config snapshot
- open order / unwind / reservation 상태

보조 입력:

- connector health
- 최근 private event freshness
- 최근 체결 성공률
- 최근 reject / unwind 이력


## 출력

항상 아래 둘 중 하나를 만든다.

### 1. accept

- `decision_record`
- `reservation_plan`
- `order_intent_plan`

### 2. reject

- `decision_record`
- `reason_code`
- `reason_detail`


## 권장 판정 순서

### A. Gate Check

아래 항목을 계산 전에 먼저 본다.

- connector health ok
- public/private freshness ok
- balance freshness ok
- quote pair clock skew ok
- symbol tradable
- unwind in progress 아님
- open order cap 초과 아님

하나라도 실패하면 즉시 reject한다.

### B. Quote Pair Lock

- 두 거래소 snapshot을 같은 판단 윈도우로 묶는다.
- `abs(base.observed_at - hedge.observed_at) <= max_clock_skew_ms`
- 둘 다 `max_orderbook_age_ms` 이내여야 한다.

실패 시 `QUOTE_PAIR_SKEW_TOO_HIGH` 또는 `ORDERBOOK_STALE`.

### C. Candidate Size

목표 수량 `q`는 아래 최솟값으로 잡는다.

- buy side available quote 기반 수량
- sell side available base 기반 수량
- orderbook depth 기반 수량
- risk cap 기반 수량
- max_notional_per_order 기반 수량

`q <= 0`이면 reject한다.

### D. Executable Simulation

같은 `q`에 대해:

- buy VWAP
- sell VWAP
- total fee
- total slippage budget
- unwind buffer

를 계산한다.

핵심 결과:

- `executable_buy_cost_quote`
- `executable_sell_proceeds_quote`
- `executable_profit_quote`
- `executable_profit_bps`

둘 중 하나라도 기준 미만이면 reject한다.

### E. Reservation

아래를 원자적으로 reserve한다.

- buy side quote
- sell side base
- symbol exposure budget
- bot / exchange budget

reserve 실패 시 `RESERVATION_FAILED`.

### F. Entry Plan

MVP 기본안:

- 두 leg 모두 taker 기준
- 수익이 아니라 체결 확실성을 우선

생성 결과:

- leg A order intent draft
- leg B order intent draft
- hedge timeout
- unwind fallback policy

### G. Post-Submit Guard

제출 이후 아래를 watcher가 본다.

- leg latency
- fill imbalance
- residual exposure
- reservation release

실패 시 즉시 `unwind_required`.


## 필요한 내부 함수

최소 함수 분해:

1. `load_strategy_inputs`
2. `validate_gate_conditions`
3. `lock_quote_pair`
4. `compute_candidate_size`
5. `simulate_executable_edge`
6. `evaluate_risk_caps`
7. `reserve_capacity`
8. `build_order_intent_plan`
9. `emit_decision_record`


## 우선 구현 항목

### P0

- `lock_quote_pair`
- `simulate_executable_edge`
- `reserve_capacity`

### P1

- reject code 표준화
- re-entry cooldown
- recent execution quality input

### P2

- maker/taker adaptive entry
- dynamic hedge confidence
- symbol volatility adaptive threshold


## 코드 배치 제안

- `src/trading_platform/strategy/arbitrage_input_loader.py`
- `src/trading_platform/strategy/arbitrage_gate.py`
- `src/trading_platform/strategy/arbitrage_pricing.py`
- `src/trading_platform/strategy/arbitrage_reservation.py`
- `src/trading_platform/strategy/arbitrage_planner.py`
- `src/trading_platform/strategy/arbitrage_runtime.py`

한 파일이 모든 판단을 다 가지지 않게 분리한다.


## 구현 완료 기준

- top-of-book spread만으로 accept하지 않는다.
- decision record에 reject 이유가 항상 남는다.
- reservation 실패는 silent skip이 아니라 명시적 reject가 된다.
- stale / skew / depth 부족 / cap 초과를 각각 다른 reason code로 구분한다.
- live 이전에 dry-run과 shadow에서 같은 판단 결과를 비교할 수 있다.
