# Delivery Plan and Exit Criteria

이 문서는 구현 묶음, 주차별 계획, 병렬 작업선, 단계별 종료 기준을 모은다. 실제 실행 순서와 팀별 작업 분리를 조정할 때 기준으로 사용한다.


## 52. 현재 문서 기준 다음 구현 묶음 제안

이 문서를 기준으로 실제 새 프로젝트를 시작한다면, 초기 구현 묶음은 다음처럼 나누는 것이 합리적이다.

### 52.1 Backend Core

- config schema / compiler
- risk evaluator
- strategy runtime shell
- order intent / order / fill repository
- reconciliation job skeleton

### 52.2 Exchange Adapter

- Upbit public REST / public WS / private REST / private WS
- Bithumb public REST / public WS / private REST
- Coinone public REST / public WS / private REST / private WS
- 공통 auth / limiter / retry / error mapper

### 52.3 Control Plane / UI

- dashboard read model
- bot / strategy run / order explorer API
- config management API
- alerts / audit API
- Bot Overview / Bot Detail / Order Explorer 초기 화면

### 52.4 Infra / Ops

- PostgreSQL / Redis / migration
- logging / metrics / tracing
- notifier
- incident / alert pipeline

### 52.5 가장 먼저 닫아야 할 남은 공백

- 거래소별 공식 문서 버전 pinning
- instrument metadata source 확정
- fee source of truth 확정
- secret manager 방식 확정
- live mode 승인 체계 확정

## 53. 주차별 Execution Plan 초안

이 섹션은 새 프로젝트를 8주 기준으로 처음 세팅하는 실행 계획 초안이다.
실제 인력 수와 우선순위에 따라 6주 또는 10주로 압축/확장할 수 있다.

### 53.1 전체 원칙

- 주문 실행보다 read path와 안전장치를 먼저 완성
- live mode는 마지막 단계까지 열지 않음
- 각 주차는 "작동하는 좁은 slice"를 남겨야 함
- backend, frontend, infra, exchange adapter는 가능한 한 병렬 진행

### 53.2 Week 1: 기반 골격

목표:

- repository scaffold
- FastAPI 기본 앱
- PostgreSQL / Redis / Alembic 초기 세팅
- structured logging / metrics 골격
- config schema 초안

완료 기준:

- health endpoint 동작
- DB migration 1회 성공
- logging / metrics endpoint 확인
- config validation CLI 또는 내부 API 동작

### 53.3 Week 2: Core Domain + Read Path

목표:

- bots / strategy_runs / heartbeats / alerts schema 반영
- dashboard summary read model
- bot list / bot detail API
- 초기 UI shell

완료 기준:

- UI에서 bot 목록/상세 조회 가능
- alert와 heartbeat가 DB에 기록되고 조회 가능
- audit event 기본 기록 가능

### 53.4 Week 3: Market Data Connector

목표:

- Upbit public REST / WS
- Bithumb public REST / WS
- Coinone public REST / WS
- orderbook normalization
- instrument metadata 관리 방식 확정

완료 기준:

- 세 거래소 orderbook이 내부 표준 모델로 수집됨
- freshness 판단 가능
- connector health가 dashboard에 표시됨

### 53.5 Week 4: Private API + Config Compiler

목표:

- private balance adapter
- auth provider / limiter / retry 공통 모듈
- config compiler / risk profile / strategy template 반영
- config management API

완료 기준:

- 세 거래소 중 최소 2곳에서 private balance 성공
- config compile 결과가 DB에 versioned 저장
- invalid config 배포 차단 확인

### 53.6 Week 5: Strategy Runtime + Dry Run

목표:

- strategy worker shell
- decision record 생성
- risk evaluator
- order intent 생성
- dry-run end-to-end 연결

완료 기준:

- 실주문 없이 decision record와 order intent 생성
- freshness 실패/리스크 초과 시 fail-closed 확인
- Bot Detail에서 최근 전략 판단 흐름 조회 가능

### 53.7 Week 6: Order Execution + Reconciliation

목표:

- 실주문 adapter
- order / fill persistence
- reconciliation job
- order explorer UI

완료 기준:

- 최소 1개 거래소에서 테스트 주문 생성/조회/취소 성공
- REST/WS 상태 차이를 reconciliation이 복구
- order explorer에서 intent-order-fill 연결 조회 가능

### 53.8 Week 7: Hedge / Unwind / Alerts

목표:

- hedge latency tracking
- unwind engine
- incident / alert pipeline 강화
- operator actions UI

완료 기준:

- 한쪽 leg만 체결되는 시나리오에서 unwind 정책 동작
- critical alert가 UI와 notifier에 동시에 반영
- pause/resume, ack, config assignment 감사 로그 기록

### 53.9 Week 8: Shadow 운영 준비

목표:

- staging/shadow 환경 검증
- live smoke test 절차 정리
- runbook 최종 보강
- production gate 정의

완료 기준:

- shadow mode로 7일 운영 가능한 체크리스트 확보
- 주요 장애 대응 플레이북 검토 완료
- live enable 승인 절차 문서화 완료

## 54. 팀별 병렬 작업선 제안

### 54.1 Backend Core

- domain model
- repositories
- config compiler
- risk evaluator
- strategy runtime

### 54.2 Exchange Adapter

- Upbit adapter
- Bithumb adapter
- Coinone adapter
- 공통 auth / limiter / websocket supervisor

### 54.3 Frontend

- app shell
- dashboard
- bot detail
- order explorer
- alert center
- config viewer

### 54.4 Infra / Ops

- database / redis / migration pipeline
- logging / metrics / tracing
- deployment
- notifier / incident pipeline

### 54.5 작업 경계 원칙

- frontend는 DB 스키마가 아니라 read API contract만 의존
- strategy runtime은 거래소 raw payload가 아니라 normalized adapter output만 의존
- adapter 팀은 UI 요구사항을 몰라도 되고, 공통 internal contract만 맞추면 됨
- infra 팀은 business logic을 몰라도 배포/관찰성/비밀관리 계약만 맞추면 됨

## 55. 단계별 Exit Criteria

각 단계는 "구현 완료"가 아니라 "다음 단계로 넘어가도 안전한가"로 판정한다.

### 55.1 Core Exit Criteria

- migration 반복 실행 가능
- config validation 실패가 명확히 드러남
- health / metrics / logs 기본 관찰 가능

### 55.2 Market Data Exit Criteria

- 세 거래소 최소 1개 심볼 이상 정상 수집
- stale detection 동작
- reconnect / backoff 관찰 가능

### 55.3 Private API Exit Criteria

- auth 실패와 rate limit이 내부 표준 코드로 매핑됨
- balance snapshot이 저장되고 freshness 판단 가능
- secret rotation 절차 초안 완료

### 55.4 Dry Run Exit Criteria

- decision record 생성
- risk limit 차단 동작
- dry-run에서 intent 생성까지 end-to-end 동작

### 55.5 Execution Exit Criteria

- 최소 1개 거래소에서 테스트 주문 lifecycle 성공
- reconciliation이 상태 불일치 1종 이상 복구
- order/fill read model이 UI에 노출

### 55.6 Shadow Exit Criteria

- shadow mode 연속 운영
- sev-1 / sev-2 미발생
- alert noise가 허용 기준 이하
- 운영자가 runbook만 보고 주요 장애에 대응 가능

## 56. 현재 문서의 실무 활용 방법

이 문서는 단순 설명서가 아니라, 다음 세 가지 용도로 바로 쓸 수 있다.

### 56.1 아키텍처 기준서

- 어떤 기술 스택을 쓰는지
- 어떤 경계를 분리하는지
- 무엇을 먼저 만들고 무엇을 나중에 여는지

### 56.2 구현 계약서

- backend와 frontend의 API 계약
- strategy와 adapter의 내부 계약
- 운영과 보안의 승인 규칙

### 56.3 초기 PM 문서

- MVP 범위
- 리스크
- 주차별 계획
- 종료 기준

권장 다음 산출물:

- `implementation_tasks.md`
- `exchange_contract_upbit.md`
- `exchange_contract_bithumb.md`
- `exchange_contract_coinone.md`
- `frontend_wireframes.md`
