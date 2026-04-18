# Arbitrage Algorithm Execution Spec

이 문서는 재정거래 핵심 알고리즘을 실제 구현 단위로 쪼갠 실행 스펙이다.
비판적 검토 문서가 "무엇이 위험한가"를 다룬다면, 이 문서는 "어떤 순서로 어떤 값을 계산할 것인가"를 다룬다.


## 목표

- 진입 판단을 top-of-book 비교가 아니라 실행 가능 수익 평가로 바꾼다.
- 판단 결과를 항상 `accept` 또는 `reject(reason_code)`로 남긴다.
- execution 계층에 넘기기 전 reserve 단계까지 포함해 fail-closed로 끝낸다.
- 단일 거래소 쌍 고정 평가에서 벗어나, 같은 코인에 대해 3개 거래소 이상을 동시에 비교한 뒤 이번 틱의 최적 진입 쌍을 선택할 수 있게 한다.


## 입력

필수 입력:

- `strategy_run_id`
- `bot_id`
- `canonical_symbol`
- `candidate_exchanges[]`
- 거래소별 latest orderbook snapshot
- 거래소별 balance snapshot
- risk/config snapshot
- open order / unwind / reservation 상태

보조 입력:

- connector health
- 최근 private event freshness
- 최근 체결 성공률
- 최근 reject / unwind 이력
- 거래소별 fetch freshness / rate-limit 상태


## 모델 변경 메모

- 현재 구현은 `base_exchange + hedge_exchange` 2거래소 쌍 입력을 전제로 한다.
- 목표 구조는 `candidate_exchanges[]`를 입력으로 받아, 런타임 안에서 모든 유효 조합을 평가한 뒤 1개의 `selected_pair`를 고르는 방식이다.
- 즉시 API 계약을 전면 변경하지 않더라도, 내부 설계 기준은 "다거래소 후보 평가 -> 최적 pair 선택 -> 기존 2-leg execution 진입"으로 맞춘다.
- execution 자체는 여전히 `buy leg 1개 + sell leg 1개`의 2-leg 주문으로 유지한다.


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
- symbol tradable
- unwind in progress 아님
- open order cap 초과 아님

하나라도 실패하면 즉시 reject한다.

### B. Candidate Exchange Filter

- `candidate_exchanges[]`에서 이번 틱에 평가 가능한 거래소만 남긴다.
- 각 거래소별로 아래를 먼저 걸러낸다.
  - latest orderbook snapshot 존재
  - latest balance snapshot 존재
  - `max_orderbook_age_ms` 이내
  - connector degraded / rate-limited가 아님
- 평가 가능한 거래소가 2개 미만이면 즉시 reject한다.

### C. Quote Pair Lock

- 필터를 통과한 거래소들의 조합을 만든다.
- 각 조합에 대해 두 거래소 snapshot을 같은 판단 윈도우로 묶는다.
- `abs(left.observed_at - right.observed_at) <= max_clock_skew_ms`
- 둘 다 `max_orderbook_age_ms` 이내여야 한다.

실패 시 `QUOTE_PAIR_SKEW_TOO_HIGH` 또는 `ORDERBOOK_STALE`.

### D. Pair Ranking and Candidate Selection

- 각 거래소 조합을 양방향으로 평가한다.
  - `left -> right`
  - `right -> left`
- 각 방향 평가 결과는 모두 `accept` 또는 `reject(reason_code)`로 남긴다.
- `accept`된 후보가 여러 개면 아래 우선순위로 `selected_pair`를 고른다.
  - executable profit quote 최대
  - executable profit bps 최대
  - orderbook freshness 우수
  - 최근 submit/recovery 상태가 더 안정적인 쪽
- `accept`가 하나도 없으면 전체 틱을 reject한다.

### E. Candidate Size

목표 수량 `q`는 아래 최솟값으로 잡는다.

- buy side available quote 기반 수량
- sell side available base 기반 수량
- orderbook depth 기반 수량
- risk cap 기반 수량
- max_notional_per_order 기반 수량

`q <= 0`이면 reject한다.

### F. Executable Simulation

같은 `q`에 대해:

- buy VWAP
- sell VWAP
- total fee
- buy leg slippage budget
- sell leg slippage budget
- rebalance buffer
- unwind buffer

를 계산한다.

핵심 결과:

- `executable_buy_cost_quote`
- `executable_sell_proceeds_quote`
- `gross_profit_quote`
- `executable_profit_quote`
- `executable_profit_bps`

둘 중 하나라도 기준 미만이면 reject한다.

### G. Reservation

아래를 원자적으로 reserve한다.

- buy side quote
- sell side base
- symbol exposure budget
- bot / exchange budget
- `selected_pair` 단위 중복 진입 방지 락

reserve 실패 시 `RESERVATION_FAILED`.

### H. Entry Plan

MVP 기본안:

- 두 leg 모두 taker 기준
- 수익이 아니라 체결 확실성을 우선

생성 결과:

- leg A order intent draft
- leg B order intent draft
- hedge timeout
- unwind fallback policy

### I. Post-Submit Guard

제출 이후 아래를 watcher가 본다.

- leg latency
- fill imbalance
- residual exposure
- reservation release

실패 시 즉시 `recovery_required`.
자동 unwind 조건이 맞으면 다음 상태는 `unwind_in_progress`.


## 필요한 내부 함수

최소 함수 분해:

1. `load_strategy_inputs`
2. `collect_candidate_exchange_snapshots`
3. `filter_candidate_exchanges`
4. `enumerate_quote_pairs`
5. `validate_gate_conditions`
6. `lock_quote_pair`
7. `compute_candidate_size`
8. `simulate_executable_edge`
9. `rank_candidate_pairs`
10. `reserve_capacity`
11. `build_order_intent_plan`
12. `emit_decision_record`


## 우선 구현 항목

### P0

- `collect_candidate_exchange_snapshots`
- `enumerate_quote_pairs`
- `rank_candidate_pairs`
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
- `src/trading_platform/strategy/arbitrage_candidate_sets.py`
- `src/trading_platform/strategy/arbitrage_gate.py`
- `src/trading_platform/strategy/arbitrage_pricing.py`
- `src/trading_platform/strategy/arbitrage_reservation.py`
- `src/trading_platform/strategy/arbitrage_planner.py`
- `src/trading_platform/strategy/arbitrage_runtime.py`

한 파일이 모든 판단을 다 가지지 않게 분리한다.


## 구현 완료 기준

- top-of-book spread만으로 accept하지 않는다.
- 같은 코인에 대해 3개 거래소 이상이 주어지면 모든 유효 조합을 평가한 뒤 1개의 `selected_pair`만 실행 경로로 넘긴다.
- decision record에 reject 이유가 항상 남는다.
- reservation 실패는 silent skip이 아니라 명시적 reject가 된다.
- stale / skew / depth 부족 / cap 초과를 각각 다른 reason code로 구분한다.
- live 이전에 dry-run과 shadow에서 같은 판단 결과를 비교할 수 있다.
