# Arbitrage Incident Taxonomy

이 문서는 재정거래 전략 운영 중 발생하는 incident를 어떤 코드와 등급으로 분류할지 정한다.
목적은 `reason_code`, `lifecycle_state`, `invariant_code`, `incident_code`를 서로 섞어 쓰지 않게 만드는 것이다.


## 핵심 원칙

- `reason_code`는 판단 결과다.
- `lifecycle_state`는 현재 실행 상태다.
- `invariant_code`는 런타임 모순 감지다.
- `incident_code`는 운영 대응 단위다.

즉, 같은 사건에서도 네 값은 서로 다를 수 있다.


## 언제 incident를 만든다고 볼 것인가

아래 중 하나면 incident 후보로 본다.

- `recovery_required` 진입
- `manual_handoff` 진입
- P0 invariant 위반
- residual exposure가 허용 범위를 넘김
- stale/skew/reject가 짧은 시간에 비정상 급증
- stop/rollback이 필요한 운영 이벤트 발생


## 코드 체계

형식:

- `ARB-XXX`

초기 분류:

- `ARB-100` 계열: 데이터/판단 품질
- `ARB-200` 계열: 실행/체결 비정상
- `ARB-300` 계열: 복구/노출
- `ARB-400` 계열: 런타임 불변조건
- `ARB-500` 계열: 운영 개입/승인


## 권장 incident 코드

### ARB-101 ORDERBOOK_STALE_SPIKE

- 의미:
  - stale reject가 짧은 시간에 급증
- 대표 연결:
  - `reason_code=ORDERBOOK_STALE`
- 기본 등급:
  - `sev-2`

### ARB-102 QUOTE_PAIR_SKEW_SPIKE

- 의미:
  - skew reject가 급증
- 대표 연결:
  - `reason_code=QUOTE_PAIR_SKEW_TOO_HIGH`
- 기본 등급:
  - `sev-2`

### ARB-201 HEDGE_TIMEOUT

- 의미:
  - 진입 후 hedge latency가 기준 초과
- 대표 연결:
  - `lifecycle_state=recovery_required`
- 기본 등급:
  - `sev-1` live
  - `sev-2` shadow

### ARB-202 PARTIAL_FILL_IMBALANCE

- 의미:
  - 한쪽 leg partial fill 후 균형 회복이 안 됨
- 대표 연결:
  - `lifecycle_state=entry_open` 또는 `recovery_required`
- 기본 등급:
  - `sev-1` live

### ARB-301 RESIDUAL_EXPOSURE_HIGH

- 의미:
  - residual exposure가 허용 범위 초과
- 대표 연결:
  - `lifecycle_state=recovery_required|unwind_in_progress`
- 기본 등급:
  - `sev-1`

### ARB-302 MANUAL_HANDOFF_REQUIRED

- 의미:
  - 자동 복구로 더 진행하면 위험
- 대표 연결:
  - `lifecycle_state=manual_handoff`
- 기본 등급:
  - `sev-1`

### ARB-401 ACTIVE_ENTRY_CONFLICT

- 의미:
  - active entry uniqueness 위반
- 대표 연결:
  - `invariant_code=ARB_INV_ACTIVE_ENTRY_UNIQUENESS`
- 기본 등급:
  - `sev-1`

### ARB-402 ACCEPT_WITHOUT_RESERVATION

- 의미:
  - accept인데 reservation 근거가 없음
- 대표 연결:
  - `invariant_code=ARB_INV_ACCEPT_WITHOUT_RESERVATION`
- 기본 등급:
  - `sev-1`

### ARB-403 RESIDUAL_EXPOSURE_UNKNOWN

- 의미:
  - 노출을 계산할 수 없어 복구 판단이 불명확
- 대표 연결:
  - `invariant_code=ARB_INV_RESIDUAL_EXPOSURE_UNKNOWN`
- 기본 등급:
  - `sev-1`

### ARB-501 LIVE_GATE_BYPASS_ATTEMPT

- 의미:
  - shadow/live gate 미충족 상태에서 live enable 시도
- 대표 연결:
  - `05_arbitrage_shadow_live_gate.md`
- 기본 등급:
  - `sev-2`

### ARB-502 STOP_COMMAND_UNEFFECTIVE

- 의미:
  - stop command 이후 신규 진입 또는 live submit이 계속 발생
- 대표 연결:
  - 운영 명령 검증 실패
- 기본 등급:
  - `sev-1`


## 등급 결정 규칙

- 동일 코드라도 `live`가 `shadow`보다 더 높게 본다.
- residual exposure가 실제 자산 노출로 이어지면 `sev-1`이다.
- 단순 관측 이상이 아니라 stop/rollback이 필요하면 `sev-1` 또는 `sev-2`다.


## 관계 규칙

한 사건 예시:

- `reason_code=ARBITRAGE_OPPORTUNITY_FOUND`
- `lifecycle_state=recovery_required`
- `invariant_code` 없음
- `incident_code=ARB-201 HEDGE_TIMEOUT`

또 다른 예시:

- `reason_code=ARBITRAGE_OPPORTUNITY_FOUND`
- `lifecycle_state=decision_accepted`
- `invariant_code=ARB_INV_ACCEPT_WITHOUT_RESERVATION`
- `incident_code=ARB-402 ACCEPT_WITHOUT_RESERVATION`

원칙:

- incident는 운영 대응 단위를 대표한다.
- 화면과 알림은 incident 기준으로 묶고, 세부 원인은 아래 필드로 내려간다.


## 권장 산출물

incident 레코드는 최소한 아래를 가져야 한다.

- `incident_id`
- `incident_code`
- `severity`
- `status`
- `opened_at`
- `resolved_at`
- `bot_id`
- `strategy_run_id`
- `decision_id`
- `order_intent_id`
- `order_id`
- `reason_code`
- `lifecycle_state`
- `invariant_code`
- `summary`
- `suggested_action`


## 구현 체크리스트

- 같은 incident를 `reason_code`로 대체하지 않는다.
- 같은 사건이 여러 alert로 쪼개지면 incident로 묶는 기준을 먼저 정한다.
- 새 invariant를 추가하면 연결 incident 코드도 같이 검토한다.
- 플레이북과 incident taxonomy가 충돌하면 taxonomy를 먼저 바꾸지 말고 실제 대응 단위를 다시 본다.
