# Arbitrage Algorithm Critical Review

이 문서는 현물 재정거래 핵심 알고리즘을 비판적으로 다시 보고, MVP에서 먼저 고쳐야 할 설계 빈칸을 정리한다.
현재 문서들은 리스크, 기록, unwind는 잘 정의돼 있지만, "언제 진입하고 언제 포기하는가"의 핵심 순서가 아직 느슨하다.


## 핵심 결론

현재 설계는 안전장치가 많지만, 진입 알고리즘이 top-of-book 기준의 단순 기회 탐지로 해석될 여지가 있다.
재정거래의 실제 위험은 진입 후가 아니라 "잘못된 진입을 허용한 순간"에 시작된다.
따라서 핵심 알고리즘은 `수익 계산`보다 `fail-closed 진입 차단기`로 먼저 설계해야 한다.


## 현재 설계에서 위험한 점

### 1. 실행 가능 수익과 표시 수익이 분리돼 있지 않다

- 현재 문서는 `best bid / best ask`, `expected_profit`를 기록하지만, 체결 가능한 수량 기준 VWAP 계산이 중심 규칙으로 고정돼 있지 않다.
- top-of-book spread가 커 보여도 실제 depth를 타면 즉시 음수로 바뀔 수 있다.

필수 보강:

- 진입 판단은 항상 `실행 가능 수익(executable edge)` 기준으로만 한다.
- 양 거래소 orderbook depth를 같은 수량으로 시뮬레이션한 뒤 수익을 계산한다.

### 2. 두 leg의 비대칭 위험이 진입 전에 충분히 차단되지 않는다

- 현재 문서는 hedge 실패 후 unwind를 잘 다루지만, "왜 애초에 그 진입을 허용했는가"는 약하다.
- 한쪽 거래소는 얇고 다른 쪽은 두꺼운 경우, 기대 수익보다 hedge 실패 확률이 더 큰데도 진입될 수 있다.

필수 보강:

- 진입 전에 `max_leg_latency_ms`, depth, 최근 체결 성공률, connector health를 함께 본다.
- 어느 한쪽이라도 hedge confidence가 낮으면 진입하지 않는다.

### 3. 스냅샷 일관성 규칙이 약하다

- 두 거래소 시세가 서로 다른 시점일 수 있는데, 현재 문서만으로는 이것이 확실히 reject된다고 보기 어렵다.

필수 보강:

- 두 거래소 quote는 `max_clock_skew_ms` 안에 들어온 pair만 비교한다.
- 한쪽 snapshot만 새롭고 한쪽은 오래되면 무조건 reject한다.

### 4. 잔고 예약과 중복 진입 차단이 핵심 알고리즘에 내장돼 있지 않다

- duplicate intent 방지는 문서에 있지만, "이번 판단이 아직 제출 안 된 다른 판단과 같은 자금을 잡아먹는가"가 명확하지 않다.

필수 보강:

- 진입 판단 직후 `quote/base balance reservation`을 먼저 잡는다.
- reservation 실패면 기회가 있어도 진입하지 않는다.

### 5. churn 방지 규칙이 약하다

- spread가 임계값 주변에서 흔들리면 짧은 시간에 create/cancel/re-enter가 반복될 수 있다.

필수 보강:

- `enter_threshold`와 `reenter_threshold`를 분리한다.
- 최근 reject/stop/unwind 직후 cooldown을 둔다.


## 권장 핵심 알고리즘 V2

### 단계 0. 사전 차단

- connector health
- private/public freshness
- clock skew
- balance freshness
- symbol tradeability
- open order / unwind in progress

하나라도 실패하면 즉시 reject한다.

### 단계 1. Quote Lock

- 두 거래소 snapshot을 같은 판정 윈도우로 묶는다.
- lock된 snapshot 쌍이 아니면 계산하지 않는다.

### 단계 2. Executable Simulation

같은 목표 수량 `q`에 대해 아래를 계산한다.

- buy VWAP + taker fee + slippage buffer
- sell VWAP - taker fee - slippage buffer
- residual inventory impact
- expected unwind cost buffer

최종 판단 값:

- `executable_profit_quote`
- `executable_profit_bps`

이 값이 둘 다 기준 미만이면 reject한다.

### 단계 3. Capacity Reservation

- buy side quote 자금 예약
- sell side base inventory 예약
- symbol / bot / exchange risk budget 예약

reservation이 실패하면 reject한다.

### 단계 4. Entry Plan Selection

MVP 권장:

- 기본은 `hedge-first safety`보다 `simultaneous taker-taker`
- 한쪽만 maker로 남기는 전략은 후순위

이유:

- 초기 단계에서는 수익 최대화보다 편측 체결 위험 축소가 더 중요하다.

### 단계 5. Post-Entry Guard

- leg latency 초과
- partial fill imbalance
- exposure 한도 초과

위 셋 중 하나면 즉시 `recovery_required`로 전이한다.
자동 복구 정책이 켜져 있으면 이후 `unwind_in_progress`로 이어진다.


## 추가로 필요한 reject code

- `QUOTE_PAIR_SKEW_TOO_HIGH`
- `EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH`
- `RESERVATION_FAILED`
- `HEDGE_CONFIDENCE_TOO_LOW`
- `REENTRY_COOLDOWN_ACTIVE`
- `UNWIND_BUFFER_TOO_LARGE`


## 구현 우선순위 제안

1. executable VWAP 기반 수익 계산
2. quote pair lock / skew reject
3. balance and risk reservation
4. re-entry cooldown / hysteresis
5. 이후 maker 전략, adaptive execution 최적화


## 최종 판단

초기 제품의 핵심 알고리즘은 "기회를 잘 찾는 알고리즘"보다 "나쁜 진입을 확실히 막는 알고리즘"이어야 한다.
현재 설계는 복구와 리스크 문서는 강하지만, 진입 알고리즘 자체는 아직 낙관적이다.
MVP는 수익 극대화보다 `depth 반영`, `snapshot 일관성`, `reservation`, `fail-closed`를 먼저 구현하는 편이 맞다.
