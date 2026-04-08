# Operational Alerts and Dashboard Guide

이 문서는 운영 알림 규칙과 대시보드 패널을 더 구체적으로 적는다.
공통 원칙은 `04_operations.md`, 재정거래 전용 관측 기준은 `05_arbitrage_observability_spec.md`를 따른다.


## 1. 즉시 알림 대상

- heartbeat 누락
- `recovery_required` active count > 0 in live
- `manual_handoff` active count > 0
- P0 invariant violation > 0
- residual exposure unknown > 0
- PostgreSQL 또는 Redis 연결 불가

권장 level:

- `warn`: heartbeat 지연, stale 증가, API 에러 증가
- `error`: connector degraded 지속, repeated order failure, reconciliation mismatch 반복
- `critical`: live 주문 중단 판단이 필요한 경우


## 2. 빠른 확인 대상

- stale reject 비율 급증
- skew reject 비율 급증
- reservation failure 증가
- submit 후 first fill latency 악화
- balance 급감
- orderbook latency p95 악화


## 3. 대시보드 P0 패널

### Control Plane

- active bots
- active strategy runs
- write API 401/429 비율
- `/api/v1/ready` 상태 요약

### Market Data

- orderbook age by exchange
- market ws reconnects
- stale count / stale reject 추이

### Arbitrage Runtime

- accept vs reject 추이
- reject reason top N
- lifecycle state 분포
- recovery_required / unwind_in_progress / manual_handoff count

### Execution / Recovery

- submit -> first fill latency
- hedge latency
- unwind duration
- replay restored counter


## 4. 운영자가 바로 답해야 하는 질문

- 지금 reject가 늘어난 이유가 stale 때문인가, profit 부족 때문인가
- 지금 live에서 recovery가 열려 있는가
- residual exposure가 남아 있는가
- 최근 private connector 또는 private WS가 준비되지 않은 거래소가 있는가
- write API 보호가 비정상적으로 요청을 막고 있지는 않은가


## 5. 운영 화면 연결 원칙

- decision 화면은 `reason_code` 중심
- runtime 화면은 `lifecycle_state` 중심
- incident 화면은 `invariant_code`와 `suggested_action` 중심
- private connector와 private WS 표면은 별도 runtime 패널로 분리


## 6. 최소 패널 세트

1. Service health
2. Ready/read_store/redis_runtime
3. Bot heartbeat lag
4. Orderbook age by exchange
5. Decision quality
6. Runtime safety signals
7. Recovery/unwind
8. Private connector / private WS readiness
