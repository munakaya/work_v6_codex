# Arbitrage Test Matrix

이 문서는 재정거래 전략 구현 시 무엇을 어떤 테스트 레벨에서 검증해야 하는지 한 표로 묶는다.
목적은 validation case, runtime invariant, incident 대응이 따로 놀지 않게 만드는 것이다.


## 핵심 원칙

- 판단 검증과 운영 검증은 따로 본다.
- pure function test로 끝나는 항목과 shadow replay까지 가야 하는 항목을 구분한다.
- P0 항목은 누락되면 live를 열지 않는다.


## 테스트 레벨

### L1. Pure Function Unit Test

- 입력과 출력이 완전히 고정된 계산/판단 로직
- 예:
  - executable profit 계산
  - reject reason precedence
  - candidate size 계산

### L2. Runtime State Test

- 상태 전이와 invariant 계산
- 예:
  - lifecycle state derive
  - active entry uniqueness
  - residual exposure 계산

### L3. Dry-run Integration Test

- 저장소, strategy runtime shell, decision record 적재까지 포함
- 실주문 없이 `decision -> intent -> state` 흐름 검증

### L4. Replay / Shadow Test

- 실제 또는 기록된 event 순서로 replay
- timing, skew, stale, partial fill 같은 운영성 문제 검증

### L5. Operational Drill

- operator 대응, stop, rollback, manual handoff 같은 운영 절차 검증


## P0 테스트 매트릭스

| ID | 검증 대상 | 기대 결과 | 최소 레벨 | 연결 문서 |
|---|---|---|---|---|
| M1 | 정상 실행 가능 수익 계산 | `accept`, `ARBITRAGE_OPPORTUNITY_FOUND` | L1 | `05_arbitrage_algorithm_validation_cases.md` C1 |
| M2 | depth 반영 후 수익 음수 | `reject`, `EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH` | L1 | `05_arbitrage_algorithm_validation_cases.md` C2 |
| M3 | stale orderbook | `reject`, `ORDERBOOK_STALE` | L1 | `05_arbitrage_algorithm_validation_cases.md` C3 |
| M4 | quote pair skew 초과 | `reject`, `QUOTE_PAIR_SKEW_TOO_HIGH` | L1 | `05_arbitrage_algorithm_validation_cases.md` C4 |
| M5 | reservation 실패 | `reject`, `RESERVATION_FAILED` | L1 | `05_arbitrage_algorithm_validation_cases.md` C5 |
| M6 | risk cap 초과 | `reject`, `RISK_LIMIT_BLOCKED` | L1 | `05_arbitrage_algorithm_validation_cases.md` C6 |
| M7 | reject code precedence | 같은 입력에서 대표 `reason_code` 고정 | L1 | `05_arbitrage_reason_code_precedence.md` |
| M8 | accept 이후 상태 전이 | `decision_accepted -> intent_created -> entry_submitting/open` | L2 | `05_arbitrage_lifecycle_state_machine.md` |
| M9 | active entry uniqueness | 중복 active entry 차단 | L2 | `05_arbitrage_runtime_invariants.md` I1 |
| M10 | accept without reservation | invariant 위반 또는 reject 처리 | L2 | `05_arbitrage_runtime_invariants.md` I2 |
| M11 | residual exposure visibility | 계산 불가면 정상 종료 금지 | L2 | `05_arbitrage_runtime_invariants.md` I5 |
| M12 | submit 실패 후 recovery | `recovery_required` 또는 recovery trace 전이 | L3 | `05_arbitrage_algorithm_validation_cases.md` C12 |


## P1 테스트 매트릭스

| ID | 검증 대상 | 기대 결과 | 최소 레벨 | 연결 문서 |
|---|---|---|---|---|
| M13 | unwind 직후 재진입 | `REENTRY_COOLDOWN_ACTIVE` | L1 | `05_arbitrage_algorithm_validation_cases.md` C7 |
| M14 | hedge confidence 부족 | `HEDGE_CONFIDENCE_TOO_LOW` | L1 | `05_arbitrage_algorithm_validation_cases.md` C8 |
| M15 | duplicate intent 경쟁 | `DUPLICATE_INTENT_BLOCKED` | L2 | `05_arbitrage_algorithm_validation_cases.md` C9 |
| M16 | lifecycle closed consistency | active unwind 있으면 `closed` 금지 | L2 | `05_arbitrage_runtime_invariants.md` I6 |
| M17 | hedge_balanced claim | 순노출 초과면 `hedge_balanced` 금지 | L2 | `05_arbitrage_runtime_invariants.md` I8 |
| M18 | stale/skew spike incident | `ARB-101`, `ARB-102` 분류 가능 | L4 | `05_arbitrage_incident_taxonomy.md` |
| M19 | hedge timeout incident | `ARB-201` 분류와 sev 분기 | L4 | `05_arbitrage_incident_taxonomy.md` |
| M20 | stop command ineffective | `ARB-502` 분류와 live 차단 | L5 | `05_arbitrage_incident_taxonomy.md` |


## P2 테스트 매트릭스

| ID | 검증 대상 | 기대 결과 | 최소 레벨 | 연결 문서 |
|---|---|---|---|---|
| M21 | stale 상태 신규 진입 금지, unwind 허용 | 신규 진입 `BALANCE_STALE`, unwind는 정책대로 | L3 | `05_arbitrage_algorithm_validation_cases.md` C10 |
| M22 | high spread outlier | `RISK_LIMIT_BLOCKED` | L1 | `05_arbitrage_algorithm_validation_cases.md` C11 |
| M23 | config immutability during active entry | 기존 entry/새 entry 분리 | L3 | `05_arbitrage_runtime_invariants.md` I10 |
| M24 | shadow-live decision diff | `accept_mismatch=0`, `reason_code_mismatch=0`, 나머지 diff는 분석 가능 | L4 | `05_arbitrage_observability_spec.md`, `05_arbitrage_shadow_live_gate.md` |
| M25 | live gate bypass 시도 | `ARB-501` 분류 | L5 | `05_arbitrage_shadow_live_gate.md`, `05_arbitrage_incident_taxonomy.md` |


## 최소 live 전 체크 세트

live 전에는 최소 아래를 닫는다.

- M1 ~ M12
- M13 ~ M17
- M19
- M20

즉:

- 판단 품질
- 상태 전이
- invariant
- recovery
- stop/incident 대응

이 다섯 묶음이 모두 확인돼야 한다.


## 권장 산출물

- `test_case_id`
- `test_level`
- `input_fixture`
- `expected_result`
- `observed_result`
- `linked_reason_code`
- `linked_lifecycle_state`
- `linked_invariant_code`
- `linked_incident_code`


## 구현 체크리스트

- 새 validation case를 추가하면 이 표에도 넣는다.
- 새 invariant를 추가하면 최소 L2 테스트를 같이 만든다.
- 새 incident code를 추가하면 최소 L4 또는 L5 테스트를 같이 만든다.
- 미확정 계약 항목은 live gate 대상이면 별도 pending 목록으로 올린다.
