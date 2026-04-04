# Arbitrage Recovery Trace Contract

이 문서는 재정거래 전략에서 `recovery trace`를 무엇으로 볼지 최소 계약을 고정한다.
목적은 여러 문서에서 recovery trace를 말하면서도, 저장 단위와 활성 상태 해석이 서로 달라지는 문제를 막는 것이다.


## 핵심 원칙

- `recovery trace`는 decision record를 대체하지 않는다.
- `recovery trace`는 복구가 필요한 entry 하나에 대한 append-only 사건 묶음이다.
- `recovery trace`가 active면 신규 진입보다 복구 판단이 우선이다.


## 최소 식별자

- `recovery_trace_id`
- `strategy_run_id`
- `bot_id`
- `canonical_symbol`
- `entry_decision_id`

원칙:

- 하나의 active entry에는 동시에 active recovery trace가 하나만 있어야 한다.
- recovery trace는 unwind action보다 상위 개념이다.
- unwind order가 없어도 recovery trace는 먼저 열릴 수 있다.


## 최소 필드

- `recovery_trace_id`
- `strategy_run_id`
- `bot_id`
- `canonical_symbol`
- `entry_decision_id`
- `trigger_type`
- `trigger_reason`
- `status`
- `residual_exposure_quote`
- `opened_at`
- `updated_at`
- `closed_at`
- `linked_unwind_action_id`
- `manual_handoff_required`


## 상태 정의

### `active`

- recovery가 아직 끝나지 않음
- 신규 진입 금지 근거로 사용 가능

### `resolved`

- 복구가 끝났고 residual exposure가 허용 범위 이내

### `handoff_required`

- 자동 복구를 더 진행하면 위험해서 운영자 개입 필요

### `cancelled`

- 잘못 열린 trace거나 중복 trace를 정리한 상태
- 운영상 정상 종료로 집계하지 않는다


## trigger_type 예시

- `submit_failure_after_accept`
- `hedge_timeout`
- `fill_imbalance`
- `reconciliation_mismatch`
- `residual_exposure_high`
- `invariant_violation`

원칙:

- `trigger_reason`은 자유 텍스트가 아니라 대표 code나 짧은 규격 문자열을 우선 쓴다.
- incident가 따로 생성되면 `incident_code`를 trace payload에 같이 남길 수 있다.


## active 판정 규칙

아래 중 하나면 `recovery trace active`로 본다.

- `status = active`
- `status = handoff_required`

아래는 active가 아니다.

- `status = resolved`
- `status = cancelled`


## unwind 와의 관계

- unwind action이 생성되면 같은 trace에 `linked_unwind_action_id`를 연결한다.
- unwind가 시작됐다고 trace를 닫지 않는다.
- trace는 residual exposure가 허용 범위 이내가 되고 종료 근거가 확인될 때 닫는다.


## lifecycle 연계 규칙

- active recovery trace가 있으면 최소 `recovery_required` 이상으로 해석한다.
- active recovery trace와 active unwind action이 함께 있으면 `unwind_in_progress`로 해석 가능하다.
- `manual_handoff_required = true` 또는 `status = handoff_required`면 `manual_handoff` 후보로 본다.


## 권장 산출물

- `recovery_trace_id`
- `trigger_type`
- `trigger_reason`
- `status`
- `residual_exposure_quote`
- `linked_unwind_action_id`
- `incident_code`
- `opened_at`
- `updated_at`
- `closed_at`


## 구현 체크리스트

- recovery trace는 append-only event 또는 상태 스냅샷 조합으로 구현할 수 있다.
- 다만 읽기 모델에서는 위 최소 필드를 같은 의미로 보여줘야 한다.
- lifecycle state와 invariant 계산은 같은 active 판정 규칙을 써야 한다.
