# Trade Recovery and Reconciliation

이 문서는 주문 정합성 확인과 hedge 실패 대응을 다룬다. 실주문 이후 사후 정합성과 편측 포지션 복구 기준은 이 문서를 따른다.


## 44. Order Reconciliation Job 상세 설계

실거래에서는 REST 응답, private websocket 이벤트, DB 기록이 항상 완전히 일치하지 않는다.
따라서 주문 정합성을 주기적으로 복구하는 reconciliation job이 필요하다.

### 44.1 목적

- 주문 상태 유실 복구
- fill 누락 복구
- partial fill 후 잔량 불일치 복구
- REST와 WS 간 상태 충돌 정리

### 44.2 입력 소스

- `orders`
- `trade_fills`
- `order_intents`
- private websocket event cache
- 거래소 REST order detail / open orders / completed orders

### 44.3 실행 트리거

- 주기 실행: 예를 들어 5초, 15초, 60초 티어
- 이벤트 기반 실행: WS disconnect, order timeout, fill mismatch
- 수동 실행: 운영자 요청

### 44.4 우선순위 큐

우선 복구 대상:

- `submitted` 상태가 오래 지속되는 주문
- partial fill 이후 업데이트가 멈춘 주문
- order intent 총 체결 수량과 order fill 합계가 맞지 않는 경우
- hedge leg 불균형이 존재하는 strategy run

### 44.5 핵심 알고리즘

1. 복구 후보 주문 집합 선택
2. 거래소별 bulk 조회 가능 시 bulk 조회 우선
3. 각 주문에 대해 raw 상태, 체결 수량, 잔량, 수수료, 최근 업데이트 시각 비교
4. DB와 차이가 있으면 append-only event 생성
5. 상태 승격 또는 정정 반영
6. 포지션/strategy run aggregate 재계산

### 44.6 상태 충돌 해결 규칙

우선순위:

1. 체결 내역 존재
2. 최신 거래소 REST order detail
3. private websocket 최신 event
4. 기존 DB 상태

해석 규칙:

- `filled`는 terminal 상태로 우선
- `cancelled`와 `filled`가 충돌하면 체결 수량 기준으로 분해 판단
- terminal 이후 non-terminal 상태가 오면 raw event는 저장하되 내부 상태는 되돌리지 않는다

### 44.7 이벤트 저장 규칙

추가 테이블 제안:

- `order_reconciliation_events`
  - `id`
  - `order_id`
  - `exchange`
  - `reason`
  - `before_state_json`
  - `after_state_json`
  - `raw_payload_json`
  - `created_at`

### 44.8 알림 규칙

다음은 alert를 발생시킨다.

- terminal 상태 불일치
- fill amount 불일치
- fee amount 불일치
- 2회 이상 복구 시도 후에도 상태 불명
- hedge pair 간 체결 불균형

## 45. Position Unwind Engine 상세 설계

차익거래 전략에서 가장 위험한 상황은 한쪽 거래만 체결되고 반대편 hedge가 실패하는 경우다.
이를 자동으로 줄이기 위한 unwind engine을 별도 책임으로 둔다.

### 45.1 목적

- 단일 거래소 노출을 빠르게 축소
- 의도하지 않은 방향성 포지션 축소
- 운영자 개입 전 1차 안전장치 제공

### 45.2 진입 조건

- 한 leg만 `filled` 또는 `partially_filled`
- 반대 leg가 `rejected`, `failed`, `expired`
- hedge leg latency가 허용치 초과
- net exposure가 전략 허용 범위를 초과

### 45.3 입력

- `positions`
- `orders`
- `trade_fills`
- latest orderbook snapshot
- configured unwind policy

### 45.4 unwind 정책 유형

- `immediate_market_exit`
- `aggressive_limit_exit`
- `timeboxed_requote_then_market`
- `manual_only`

초기 MVP 권장:

- 기본값은 `timeboxed_requote_then_market`
- 고위험 bot은 `immediate_market_exit`
- dry-run은 `manual_only`

### 45.5 기본 알고리즘

1. 순노출 자산과 수량 계산
2. 현재 시장 가격과 slippage budget 계산
3. unwind policy에 따라 주문 생성
4. 일정 시간 내 미체결이면 재호가 또는 시장가 탈출
5. 종료 후 residual exposure 재계산
6. 완전 해소 실패 시 `critical` alert

### 45.6 보호 규칙

- stale orderbook 상태에서 시장가 unwind 금지 여부를 정책화
- balance snapshot stale이면 신규 전략 진입 금지, unwind는 별도 예외 규칙 적용
- 동일 포지션에 대해 중복 unwind 주문 생성 금지
- operator 수동 개입 중에는 자동 unwind 중단 옵션 제공

### 45.7 기록 규칙

모든 unwind 시도는 decision record와 별도 trace를 남긴다.

추가 테이블 제안:

- `unwind_actions`
  - `id`
  - `strategy_run_id`
  - `position_id`
  - `policy`
  - `trigger_reason`
  - `exposure_before_json`
  - `action_order_intent_id`
  - `result_status`
  - `exposure_after_json`
  - `created_at`

### 45.8 운영 알림

다음은 즉시 알림 대상이다.

- unwind engine 진입
- market exit 수행
- residual exposure가 기준 초과
- 2회 이상 unwind 실패
- manual handoff 필요 상태 전환
