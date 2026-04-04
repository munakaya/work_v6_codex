# Arbitrage Shadow to Live Gate

이 문서는 재정거래 전략을 `shadow`에서 `live`로 올릴 때 필요한 승인 기준을 정한다.
목적은 "대충 잘 돌아 보인다"는 이유로 live를 여는 일을 막는 것이다.
일반 운영 전환 규칙은 `04_operations.md`, 설정 안전장치는 `05_risk_and_config.md`를 따르고, 이 문서는 재정거래 전략 전용 보강 기준으로 읽는다.


## 핵심 원칙

- live 전환은 기능 완료가 아니라 위험 승인이다.
- 알고리즘 품질, 런타임 안정성, 운영 대응 가능성이 모두 닫혀야 한다.
- 하나라도 불명확하면 live를 열지 않는다.


## P0 필수 게이트

### 1. 판단 일관성

- 같은 입력이면 `dry-run`, `shadow`에서 같은 `accept/reject(reason_code)`가 나와야 한다.
- `05_arbitrage_algorithm_validation_cases.md`의 C1~C6이 모두 닫혀 있어야 한다.
- reject 대표 code는 `05_arbitrage_reason_code_precedence.md`와 충돌하면 안 된다.

### 2. 실행 가능 수익 기준

- top-of-book 양수만으로 accept한 흔적이 없어야 한다.
- decision record에 `computed.executable_profit_quote`, `computed.executable_profit_bps`, `reservation.reservation_passed`가 남아야 한다.
- `accept without reservation` 사례는 0이어야 한다.

### 3. 상태 전이와 불변조건

- `05_arbitrage_lifecycle_state_machine.md` 기준으로 `accept -> intent -> submit/open -> balanced/closed` 흐름이 읽혀야 한다.
- `05_arbitrage_runtime_invariants.md`의 P0 invariant 위반은 0이어야 한다.
- active entry uniqueness 위반 사례가 있으면 live 금지다.

### 4. 복구 가능성

- 한쪽 leg만 체결되는 시나리오에서 `recovery_required`가 잡혀야 한다.
- unwind 또는 manual handoff 경로가 실제로 보이고, 운영자가 읽을 수 있어야 한다.
- `residual exposure visibility`가 안 보이면 live 금지다.


## P1 운영 게이트

### 5. 관측성과 알림

- 운영자가 아래를 바로 볼 수 있어야 한다.
  - 최근 accept/reject 추이
  - stale/skew reject 추이
  - active entry 수
  - recovery_required / unwind_in_progress 상태
  - critical alert

### 6. Shadow 안정성

- 연속 shadow 운영 중 decision record 누락이 없어야 한다.
- stale alert, connector degraded, reconciliation mismatch는 승인 산출물에 건수와 `top_reason`이 같이 남아야 한다.
- 위 세 항목에 unresolved critical 사례가 있으면 live 금지다.
- stop command 확인에서는 `stop_requested_at` 이후 같은 bot의 새 accept decision record와 새 order intent가 0이어야 한다.
- shadow 비교 지표에서 `accept_mismatch`, `reason_code_mismatch`는 0이어야 한다.
- `reservation_mismatch`, `target_qty_bucket_mismatch`가 있으면 원인 분석이 승인 산출물에 남아야 한다.

원인 분석 최소 필드:

- `time_window`
- `top_reason`
- `affected_bot_ids`
- `suggested_action`

### 7. 운영자 대응 가능성

- operator가 `bot stop`, `config rollback`, `alert ack`, `manual handoff`를 수행할 수 있어야 한다.
- 장애 플레이북에서 A~E 유형을 따라가며 필요한 정보가 실제로 조회돼야 한다.

운영자 drill 결과 최소 필드:

- `drill_type`
- `started_at`
- `completed_at`
- `bot_id`
- `incident_code`
- `result`
- `verified_by`


## live 금지 조건

아래 중 하나라도 있으면 live를 열지 않는다.

- C1~C6 중 미완료 케이스 존재
- P0 invariant 위반 존재
- recovery_required 상태를 정상 종료로 오해할 가능성 존재
- residual exposure 계산 불가
- shadow 결과와 decision record 계약 불일치
- 승인 윈도우에서 `accept_mismatch` 또는 `reason_code_mismatch` > 0
- 운영자 stop/rollback 절차 미검증
- 아래 문서의 미완성 또는 TODO가 live 안전성에 직접 연결됨
  - `05_arbitrage_recovery_trace_contract.md`
  - `05_arbitrage_replay_restore_accounting.md`
  - `05_arbitrage_observability_spec.md`의 shadow diff 규칙


## 권장 승인 산출물

- 최근 shadow 운영 요약
  - `time_window`
  - `mode`
  - `bot_ids`
  - `decision_count`
  - `accept_count`
  - `reject_count`
- validation case 결과표
  - `case_id`
  - `expected_result`
  - `observed_result`
  - `pass_fail`
  - `evidence_ref`
- invariant 위반 건수
  - `invariant_code`
  - `severity`
  - `count`
- stale/skew/reject 분포
  - `reason_code`
  - `count`
  - `ratio`
- stale alert / connector degraded / reconciliation mismatch 건수와 `top_reason`
- shadow diff 지표 요약
  - `reservation_mismatch`, `target_qty_bucket_mismatch`가 있으면 `time_window`, `top_reason`, `affected_bot_ids`, `suggested_action` 포함
- recovery/unwind 사례 요약
  - `strategy_run_id`
  - `lifecycle_state`
  - `residual_exposure_quote`
  - `action_taken`
  - `result`
- stop command 확인 결과
  - `bot_id`
  - `stop_requested_at`
  - `last_accept_before_stop_at`
  - `accept_after_stop_count`
  - `order_intent_after_stop_count`
  - `verified_by`
- 운영자 drill 결과
  - `drill_type`
  - `started_at`
  - `completed_at`
  - `bot_id`
  - `incident_code`
  - `result`
  - `verified_by`
- 승인자와 승인 시각


## 권장 승인 순서

1. 전략 구현 담당자가 validation/invariant 결과 제출
2. 운영 담당자가 alert/runbook/read-model 확인
3. admin이 live enable 범위와 롤백 경로 확인
4. 제한적 bot, 제한적 notional로 live 시작


## 초기 live 범위 권장

- bot 수 제한
- 심볼 수 제한
- 거래소 조합 제한
- `max_notional_per_order` 보수적 적용
- shadow 기록은 live와 동일하게 계속 적재


## 구현 체크리스트

- live 승인 기준은 문서가 아니라 자동 체크 항목으로도 옮긴다.
- shadow가 길었다는 이유만으로 live를 열지 않는다.
- "수익이 났다"보다 "틀렸을 때 바로 멈출 수 있다"를 더 높은 기준으로 둔다.
