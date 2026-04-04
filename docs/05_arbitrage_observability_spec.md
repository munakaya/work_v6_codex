# Arbitrage Observability Spec

이 문서는 재정거래 전략 전용 관측 기준을 정한다.
공통 로그/메트릭 규칙은 `04_operations.md`를 따르고, 이 문서는 재정거래 판단, 상태 전이, 복구 흐름을 어떻게 보여야 하는지에 집중한다.


## 핵심 원칙

- "거래가 있었는가"보다 "왜 거래했거나 안 했는가"가 먼저 보여야 한다.
- 수익 지표보다 stale, skew, recovery, residual exposure가 더 먼저 보여야 한다.
- 운영 화면은 decision, lifecycle, invariant 위반을 섞지 않는다.


## 반드시 보여야 하는 질문

운영자는 아래 질문에 바로 답할 수 있어야 한다.

- 지금 accept가 줄어든 이유가 stale 때문인가, profit 부족 때문인가
- active entry가 몇 개인가
- `recovery_required` 또는 `unwind_in_progress`가 있는가
- invariant 위반이 있었는가
- residual exposure가 남아 있는 bot이 있는가
- 최근 live enable 이후 판단 품질이 나빠졌는가


## P0 메트릭

### 판단 품질

- `arbitrage_decisions_total{result=accept|reject}`
- `arbitrage_reject_reason_total{reason_code=...}`
- `arbitrage_executable_profit_quote`
- `arbitrage_executable_profit_bps`
- `arbitrage_reservation_failures_total`

### 데이터 일관성

- `arbitrage_orderbook_stale_reject_total`
- `arbitrage_quote_pair_skew_reject_total`
- `arbitrage_balance_stale_reject_total`

### 상태 전이

현재량(gauge 성격)으로 읽는 값:

- `arbitrage_active_entries`
- `arbitrage_lifecycle_state_total{state=...}`

누적 사건(counter 성격)으로 읽는 값:

- `arbitrage_recovery_required_total`
- `arbitrage_unwind_started_total`
- `arbitrage_manual_handoff_total`

### 불변조건

- `arbitrage_invariant_violations_total{invariant_code=...,severity=...}`
- `arbitrage_active_entry_conflicts_total`
- `arbitrage_residual_exposure_unknown_total`


## P1 메트릭

- `arbitrage_decision_duration_ms`
- `arbitrage_submit_to_first_fill_ms`
- `arbitrage_hedge_latency_ms`
- `arbitrage_residual_exposure_quote`
- `arbitrage_unwind_duration_ms`
- `arbitrage_shadow_live_decision_diff_total{mode_pair=dry_run_vs_shadow,diff_type=accept_mismatch|reason_code_mismatch|reservation_mismatch|target_qty_bucket_mismatch}`
- `arbitrage_replay_restored_total{stage=submitted|filled|unwind_started}`

원칙:

- 비교 단위는 같은 `quote_pair_id`를 가진 decision record 쌍이다.
- 두 모드 모두 decision record가 있을 때만 diff를 센다.
- 초기 live 승인 기준에서는 `accept_mismatch`, `reason_code_mismatch`가 0이어야 한다.
- `reservation_mismatch`, `target_qty_bucket_mismatch`가 있으면 원인 분석을 같이 남긴다.
- 원인 분석 최소 필드는 `time_window`, `top_reason`, `affected_bot_ids`, `suggested_action`이다.
- `replay restored`는 판단 품질 지표가 아니라 accounting 보정 지표로 읽는다.


## 경고 기준 초안

### 즉시 대응

- `recovery_required` active count > 0 in live
- `manual_handoff` active count > 0
- P0 invariant violation > 0
- residual exposure unknown > 0

### 빠른 확인 필요

- stale reject 비율 급증
- skew reject 비율 급증
- reservation failure 증가
- submit 후 first fill latency 악화

### 참고 지표

- accept/reject 비율 변화
- executable profit 분포 변화
- unwind duration 분포 변화


## 권장 대시보드 패널

### 1. Decision Quality

- accept vs reject 추이
- reject reason top N
- executable profit quote/bps 분포

### 2. Runtime State

- active entry 수
- lifecycle state 분포
- recovery_required / unwind_in_progress / manual_handoff count

### 3. Safety Signals

- invariant violation count
- residual exposure top bots
- stale/skew reject 추이

### 4. Execution Follow-through

- submit -> first fill latency
- hedge latency
- unwind duration


## 로그 필드 보강

재정거래 관련 핵심 로그는 공통 필드 외에 아래를 같이 남기는 편이 좋다.

- `decision_id`
- `quote_pair_id`
- `reason_code`
- `lifecycle_state`
- `invariant_code`
- `residual_exposure_quote`
- `buy_exchange`
- `sell_exchange`
- `canonical_symbol`


## 운영 화면 원칙

- decision list는 `reason_code` 중심
- runtime list는 `lifecycle_state` 중심
- incident list는 `invariant_code`와 `suggested_action` 중심

원칙:

- 한 화면에서 세 의미를 섞어 같은 색이나 같은 칼럼으로 표현하지 않는다.


## shadow -> live 확인용 요약

`05_arbitrage_shadow_live_gate.md`를 실제로 확인할 때는 최소한 아래 요약이 있어야 한다.

- 최근 7일 accept/reject 추이
  - `time_window`, `decision_count`, `accept_count`, `reject_count`
- reject code 분포
  - `reason_code`, `count`, `ratio`
- P0 invariant violation 건수
  - `invariant_code`, `severity`, `count`
- stale/skew/reject 분포
  - `reason_code`, `count`, `ratio`
- recovery_required / unwind_in_progress 사례 수
  - `state`, `count`
- 최근 recovery/unwind 사례
  - `strategy_run_id`, `lifecycle_state`, `residual_exposure_quote`, `action_taken`, `result`
- stale alert / connector degraded / reconciliation mismatch 건수와 `top_reason`
- stop command 반영 시간
  - `stop_requested_at` 이후 `accept_after_stop_count`, `order_intent_after_stop_count`
- 최근 operator drill 결과
  - `drill_type`, `incident_code`, `result`
- `accept_mismatch`, `reason_code_mismatch` 건수


## 구현 체크리스트

- 메트릭 이름은 공통 prefix를 쓴다.
- reject code와 lifecycle state를 같은 label 값으로 재사용하지 않는다.
- P0 메트릭 없이 live gate를 닫았다고 보지 않는다.
- 경고 기준은 문서만 두지 말고 alert rule로 옮긴다.
