# Arbitrage Reason Code Precedence

이 문서는 재정거래 판단에서 여러 실패가 동시에 보일 때 어떤 `reason_code`를 대표로 남길지 정한다.
목적은 동일 입력에 대해 구현마다 다른 reject code가 나오는 문제를 막는 것이다.


## 핵심 원칙

- 대표 `reason_code`는 하나만 남긴다.
- 하지만 세부 실패 항목은 `gate_checks`, `computed`, `reservation`에 모두 남긴다.
- 대표 code는 "가장 먼저 진입을 막아야 했던 이유"를 고른다.


## 우선순위

### 1. 시스템 / 운영 중단

가장 먼저 본다.

- `CONFIG_DISABLED`
- `RISK_UNWIND_IN_PROGRESS`
- 전역 emergency stop

이 단계가 실패하면 대표 `reason_code` 선정은 여기서 끝낸다.
단, 진단용 세부 필드는 채우기 위해 뒤 계산을 선택적으로 계속할 수 있다.

### 2. 데이터/시간 일관성

- `ORDERBOOK_STALE`
- `QUOTE_PAIR_SKEW_TOO_HIGH`
- `BALANCE_STALE`
- `BALANCE_INSUFFICIENT`는 잔고 부족일 때만 사용

원칙:

- stale / skew는 수익 계산보다 먼저 남긴다.
- balance freshness 실패는 `BALANCE_STALE`로 남기고 `BALANCE_INSUFFICIENT`로 뭉개지지 않는다.

### 3. 리스크/거래 가능 상태

- `RISK_LIMIT_BLOCKED`
- `DUPLICATE_INTENT_BLOCKED`
- `HEDGE_CONFIDENCE_TOO_LOW`
- `REENTRY_COOLDOWN_ACTIVE`

원칙:

- 거래 가능 상태가 아니면 profit이 양수여도 reject한다.
- `max_spread_bps` 같은 비정상 market 차단 규칙은 이 단계에서 `RISK_LIMIT_BLOCKED`로 본다.

### 4. 실행 가능 수익 부족

- `EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH`
- `PROFIT_TOO_LOW`

원칙:

- depth 반영 후 음수면 `EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH`
- 음수는 아니지만 기준 미만이면 `PROFIT_TOO_LOW`

### 5. reservation 실패

- `RESERVATION_FAILED`

원칙:

- 이 단계까지 왔다는 뜻은 gate와 risk와 profit은 모두 통과했다는 뜻이다.
- 따라서 reservation 실패는 더 앞선 reject code로 덮지 않는다.


## 대표 충돌 예시

### A. stale + 양수 spread

- 대표 code: `ORDERBOOK_STALE`

이유:

- stale 데이터에서는 수익 계산 결과를 신뢰하면 안 된다.

### B. skew 초과 + executable profit 부족

- 대표 code: `QUOTE_PAIR_SKEW_TOO_HIGH`

이유:

- quote pair 자체가 invalid라면 profit 계산은 참고값일 뿐이다.

### C. risk cap 초과 + reservation 실패

- 대표 code: `RISK_LIMIT_BLOCKED`

이유:

- reserve 전에 막았어야 하는 조건이 더 앞선 실패다.

### D. duplicate intent + cooldown

- 대표 code: `DUPLICATE_INTENT_BLOCKED`

이유:

- 같은 의사결정 경쟁을 먼저 막는 편이 replay와 운영 해석에 더 직접적이다.

### E. executable profit 음수 + high spread outlier

- 대표 code: `RISK_LIMIT_BLOCKED`

이유:

- `max_spread_bps`는 비정상 market 차단 규칙이므로 profit 계산보다 먼저 막아야 한다.


## 권장 구현 방식

1. gate 단계에서 candidate reason_code를 순서대로 평가
2. 첫 실패 code를 대표 code로 채택
3. 뒤 단계는 계산하더라도 대표 code를 바꾸지 않음
4. 상세 실패는 decision record 세부 필드에 모두 남김


## 구현 체크리스트

- 같은 입력에서 reason_code가 실행 순서에 따라 바뀌지 않아야 한다.
- validation cases와 precedence 문서가 충돌하면 precedence 문서를 먼저 수정하지 말고 왜 충돌했는지 확인한다.
- reject code 추가 시 이 문서에 우선순위를 같이 적는다.
