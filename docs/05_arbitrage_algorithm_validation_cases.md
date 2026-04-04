# Arbitrage Algorithm Validation Cases

이 문서는 재정거래 핵심 알고리즘 구현 후 반드시 통과해야 하는 판단 케이스를 정리한다.
목적은 "수익이 나 보이면 진입" 같은 낙관적 구현을 막고, accept/reject를 고정된 입력으로 검증하는 것이다.


## 검증 원칙

- 각 케이스는 `accept` 또는 `reject(reason_code)`가 분명해야 한다.
- 같은 입력이면 `dry-run`, `shadow`, `live`에서 판단 결과가 같아야 한다.
- top-of-book 기준 기대 수익이 아니라 executable edge 기준으로 평가한다.


## P0 필수 케이스

### C1. 정상 진입

- 조건:
  - 두 거래소 orderbook fresh
  - clock skew 허용 범위 이내
  - depth 충분
  - executable profit 양수
  - balance / risk reservation 성공
- 기대 결과:
  - `accept`
  - `reason_code=ARBITRAGE_OPPORTUNITY_FOUND`

### C2. top-of-book 양수지만 depth 반영 후 음수

- 조건:
  - 1호가 기준 spread는 양수
  - 목표 수량을 depth로 확장하면 VWAP 기준 기대 수익 음수
- 기대 결과:
  - `reject`
  - `reason_code=EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH`

### C3. 한쪽 orderbook stale

- 조건:
  - base exchange orderbook age는 기준 이내
  - hedge exchange orderbook age는 기준 초과
- 기대 결과:
  - `reject`
  - `reason_code=ORDERBOOK_STALE`

### C4. quote pair skew 초과

- 조건:
  - 두 거래소 snapshot age는 각각 기준 이내
  - 하지만 두 snapshot observed_at 차이가 `max_clock_skew_ms` 초과
- 기대 결과:
  - `reject`
  - `reason_code=QUOTE_PAIR_SKEW_TOO_HIGH`

### C5. balance reservation 실패

- 조건:
  - 수익 계산은 양수
  - buy quote 또는 sell base reservation 실패
- 기대 결과:
  - `reject`
  - `reason_code=RESERVATION_FAILED`

### C6. risk cap 초과

- 조건:
  - executable profit은 양수
  - `max_notional_per_order` 또는 `max_total_notional_per_bot` 초과
- 기대 결과:
  - `reject`
  - `reason_code=RISK_LIMIT_BLOCKED`


## P1 강화 케이스

### C7. recent unwind 직후 재진입

- 조건:
  - 직전 판단에서 unwind가 발생
  - cooldown 기간 내 같은 symbol 재진입 시도
- 기대 결과:
  - `reject`
  - `reason_code=REENTRY_COOLDOWN_ACTIVE`

### C8. hedge confidence 부족

- 조건:
  - 한쪽 거래소 health 불안정
  - 최근 private event lag 또는 체결 실패율 상승
- 기대 결과:
  - `reject`
  - `reason_code=HEDGE_CONFIDENCE_TOO_LOW`

### C9. 중복 intent 경쟁

- 조건:
  - 같은 bot, 같은 symbol, 같은 방향의 판단이 이미 예약 또는 제출 대기 상태
- 기대 결과:
  - `reject`
  - `reason_code=DUPLICATE_INTENT_BLOCKED`


## P2 운영 케이스

### C10. stale 상태에서는 진입 금지, unwind는 허용

- 조건:
  - 신규 진입 판단 시 balance stale
  - 별도 unwind action은 필요한 상태
- 기대 결과:
  - 신규 진입은 `reject`
  - `reason_code=BALANCE_STALE`
  - unwind 경로는 별도 정책으로 계속 허용

### C11. high spread outlier

- 조건:
  - spread가 지나치게 커서 오히려 비정상 market 가능성 큼
  - `max_spread_bps` 초과
- 기대 결과:
  - `reject`
  - `reason_code=RISK_LIMIT_BLOCKED`

### C12. reservation 성공 후 submit 실패

- 조건:
  - 판단은 accept
  - submit 단계에서 한쪽 leg가 실패
- 기대 결과:
  - decision record는 accept로 남음
  - 이후 상태는 최소 `recovery_required`로 전이
  - 정책이 자동 복구를 허용하면 `unwind_in_progress`로 이어질 수 있음


## 권장 테스트 형식

테스트 레벨:

1. pure function unit test
2. dry-run integration test
3. shadow replay test

권장 산출물:

- `decision_input.json`
- `expected_decision.json`
- `expected_reason_code`


## 구현 체크리스트

- C1~C6 없이는 live 진입 금지
- C7~C9 없이는 shadow 안정화 전환 금지
- C10~C12는 운영 런북과 같이 검증
