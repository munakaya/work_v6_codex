# Execution Plan and Progress Tracking

이 문서는 다음 우선 문서, 설계 진행률, 남은 공백, 주차별 실행 계획, 역할 분담, 종료 기준을 추적한다. 구현 우선순위와 live 전환 준비 상태를 판단할 때 사용한다.


## 24. 다음 우선 문서

이 문서 다음으로 바로 작성할 가치가 큰 문서는 아래 순서다.

1. OpenAPI YAML 초안
2. Alembic initial migration 문서
3. Redis event catalog
4. Strategy ADR
5. Deployment runbook

## 31. 전체 설계 진행 상황

지금까지 문서 기준으로 보면 전체 설계 진행 상황은 아래 정도다.

### 31.1 완료된 영역

- 제품 비전
- 제품 목표 / 비목표
- 핵심 사용자 정의
- 제품 원칙
- 권장 기술 스택
- 목표 아키텍처
- 권장 디렉터리 구조
- 기능 요구사항
- 비기능 요구사항
- MVP 범위
- 구현 순서
- 초기 PostgreSQL 스키마 초안
- API 명세 초안
- OpenAPI YAML 초안
- Redis key / stream 규약
- migration 정책
- decision record format
- observability spec
- deployment runbook
- strategy ADR

### 31.2 아직 초안 수준인 영역

- 거래소별 상세 어댑터 계약
- UI 상세 설계
- OpenAPI 완성본
- Redis event catalog 상세판
- migration 실제 revision 파일 수준 설계
- alert rule 임계치 값
- 전략별 리스크 규칙 상세값

### 31.3 아직 거의 시작하지 않은 영역

- 프론트엔드 실제 스택 선택
- auth / RBAC
- object storage 사용 여부
- backtesting / replay spec
- 운영자 워크플로우 문서
- SLO / SLA 정의

### 31.4 현재 진척도 판단

내 기준으로는 지금 문서 설계는 다음 정도까지 왔다.

- 시스템/제품 아키텍처: 85%
- 데이터 모델: 75%
- API 설계: 70%
- 운영 설계: 80%
- 거래소 세부 설계: 40%
- UI 세부 설계: 35%

전체적으로 보면 "프로젝트 착수 가능한 수준의 상위 설계는 완료" 상태다.
다음 단계는 더 많은 PRD 확장이 아니라, 거래소 상세 설계와 UI 상세 설계를 별도 문서로 파고드는 것이 맞다.

## 42. 설계 완료 기준과 남은 공백

이 문서는 이미 새 프로젝트 착수를 위한 상위 설계 문서로 사용할 수 있다.
다만 실제 구현 직전에는 아래 공백을 닫아야 한다.

### 42.1 구현 착수 가능 항목

- control plane API 골격
- PostgreSQL schema 1차 migration
- Redis stream/key 규약 기반 event bus 골격
- strategy worker runtime 골격
- observability/logging/notifier 기본 모듈
- Bot Overview, Bot Detail, Order Explorer 초기 UI

### 42.2 구현 직전 추가 확정이 필요한 항목

- Upbit / Bithumb / Coinone 공식 API 문서 버전 pinning
- 거래소별 symbol normalization 규칙
- 수수료 계산 source of truth
- 최소 주문 수량/금액 validation 규칙
- live mode 승인 절차와 실제 운영 책임자
- secret manager 방식

### 42.3 문서 기준 완료 정의

다음 조건을 만족하면 "설계 1차 완료"로 본다.

- PRD, 아키텍처, DB, API, 운영, UI, adapter 설계가 한 문서 안에서 충돌 없이 연결됨
- 전략 판단부터 주문, fill, 포지션, alert, audit까지 이벤트 흐름이 정의됨
- 거래소 구현 시 필요한 auth, endpoint, error mapping의 초안이 존재함
- production 이전에 필요한 test matrix와 approval gate가 정의됨

### 42.4 다음 상세 문서 후보

- 거래소별 symbol / fee / precision 규약서
- Order reconciliation job 상세 설계
- Position unwind engine 상세 설계
- Frontend API query contract 문서
- 운영자 장애 대응 플레이북 심화판

## 48. 현재 문서 기준 전체 설계 상태 재평가

이번 보강 이후의 주관적 진행 상태는 다음과 같다.

- PRD / 제품 방향: 95%
- 상위 아키텍처: 90%
- DB 모델: 85%
- API / UI 계약: 85%
- 운영 / 관찰성 / 장애 대응: 90%
- 거래소 adapter 공통 설계: 85%
- 거래소별 구현 계약: 65%
- 웹 UI 상세 설계: 75%

해석:

- 이제 이 문서는 "착수 전 상위 설계 문서" 수준은 넘었다
- 실제 구현 팀은 backend, frontend, infra, exchange adapter 작업을 병렬로 나눌 수 있다
- 가장 큰 잔여 리스크는 거래소별 공식 문서 pinning과 실제 live smoke 검증이다

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

## 57. 문제 우선순위 재정리

이 섹션은 기존 운영 경험과 현재 PRD의 요구사항을 기준으로, 무엇을 먼저 막아야 하는지 실무 우선순위로 다시 정리한 것이다.

### 57.1 P0: 자산 손실 또는 잘못된 주문으로 이어질 수 있는 문제

- stale orderbook 또는 stale balance를 정상 데이터로 오인하는 문제
- 주문 후 체결/잔고 재검증이 늦거나 누락되어 편측 포지션을 놓치는 문제
- 실행 모드 경계가 불명확해 dry-run, shadow, live가 섞이는 문제
- 설정 변경이 검증 없이 반영되어 위험 파라미터가 즉시 적용되는 문제

### 57.2 P1: 운영 불능 또는 장애 확산으로 이어질 수 있는 문제

- process alive만 보고 기능 alive를 놓치는 문제
- 알림, heartbeat, health, audit trail이 약해 운영자가 즉시 개입하지 못하는 문제
- 외부 거래소 장애가 전체 시스템 지연 또는 재시도 폭주로 번지는 문제
- 운영 명령의 승인 경계가 약해 실수로 중지, 재시작, 설정 반영이 수행되는 문제

### 57.3 P2: 구현 속도와 변경 안전성을 떨어뜨리는 문제

- 전략, 어댑터, 저장소, 운영 API의 책임이 섞이는 문제
- 읽기 모델과 쓰기 모델이 섞여 조회 요구가 쓰기 경로를 오염시키는 문제
- 거래소별 차이를 공통 계약 없이 처리해 새 거래소 추가 비용이 커지는 문제
- 상태 전이와 이벤트 규약이 약해 테스트와 재현이 어려워지는 문제

### 57.4 P3: 후속 확장을 지연시키는 문제

- UI, 백테스트, 리플레이, RBAC, SLO가 뒤늦게 덧붙는 문제
- 초기 문서와 실제 구현 계약이 분리되어 팀 간 해석 차이가 커지는 문제

## 58. 현재 운영 경험에서 반드시 계승할 강점

이 문서는 새 시스템을 처음부터 다시 만드는 문서지만, 기존 운영에서 이미 가치가 증명된 아래 원칙은 그대로 가져가야 한다.

### 58.1 데이터 품질 우선

- 주문장 freshness를 엄격하게 본다.
- 잔고 최신성과 주문장 최신성을 분리해서 판단한다.
- 거래 기회를 놓치더라도 잘못된 데이터로 주문하지 않는다.

### 58.2 운영자 가시성 우선

- keep-alive는 프로세스 생존과 기능 생존을 구분해서 본다.
- 운영자는 현재 상태, 설정 버전, 최근 주문, 이상 이벤트를 즉시 볼 수 있어야 한다.
- 알림과 관제는 부가 기능이 아니라 제품 기본 기능으로 둔다.

### 58.3 안전한 실행 모드

- dry-run, shadow, live를 제품 모델의 일부로 유지한다.
- live 진입 전에는 반드시 shadow 운영과 검증 단계를 둔다.
- 운영 명령은 감사 가능해야 하고, 위험 명령은 승인 경계를 둔다.

### 58.4 재현 가능성과 버전 관리

- 설정은 버전 단위로 관리한다.
- 주문 의사결정 근거는 재현 가능해야 한다.
- 핵심 동작은 로그, 메트릭, 이벤트로 남겨 사후 분석이 가능해야 한다.

## 59. 주요 리스크와 롤백 전략

### 59.1 문서 단계의 주요 리스크

| 리스크 | 영향 | 완화 전략 |
|---|---|---|
| 거래소 상세 계약이 늦어짐 | 구현 시작 후 어댑터별 재작업 증가 | 32, 34, 35, 36, 43절을 먼저 닫고 공통 인터페이스를 고정 |
| UI 요구가 중간에 커짐 | Control Plane 범위가 흔들림 | 30, 33, 41, 46절의 초기 UI 비목표를 유지 |
| 운영 보안 요구가 뒤늦게 강화됨 | 배포 직전 auth/RBAC 재설계 | 39절 기준으로 민감 동작 보호 규칙을 먼저 확정 |
| 전략 파라미터와 리스크 한도가 늦게 확정됨 | shadow 이후 live 진입 지연 | 49, 50, 51절을 live 전 필수 종료 조건으로 둠 |

### 59.2 구현 단계 롤백 원칙

- migration은 전진 전용으로 관리하고 destructive change는 명시적 승인 없이는 넣지 않는다.
- live 관련 기능은 dry-run, shadow와 분리된 플래그와 상태 전이로 감싼다.
- 거래소 어댑터는 공통 인터페이스 뒤에 두고, 특정 거래소 구현 실패가 전체 구조 변경으로 번지지 않게 한다.
- 운영 명령과 config deploy는 audit log를 남기고, 직전 안정 버전으로 되돌릴 수 있어야 한다.

## 60. 문제-요구사항-구현 단계 역추적 표

현재 문서에 흩어진 요구사항을 실무 추적용으로 묶으면 아래와 같다.

| 문제 묶음 | 핵심 대응 요구사항 | 우선 구현 단계 |
|---|---|---|
| stale data, 잘못된 주문 | 11.2 Strategy Worker, 12.1 안정성, ADR-003, ADR-004, 49절, 50절 | Step 1, Step 4, Step 5 |
| 운영자 가시성 부족 | 11.1 Control Plane, 11.4 운영 인터페이스, 23절, 25절, 47절 | Step 2, Step 3 |
| 실행 모드 혼선 | 11.5 실행 모드, ADR-005, 38절 상태 전이, 25.7 운영 모드 전환 규칙 | Step 5, Step 6, Step 7 |
| 거래소별 구현 차이와 오류 처리 | 11.3 Exchange Adapter, 32절, 34절, 35절, 36절, 43절 | Step 4 |
| 설정 오류와 위험 파라미터 반영 | 20절 migration 정책, 22절 decision record, 39절, 49절, 51절 | Step 1, Step 2 |
| 편측 포지션 및 사후 정합성 | 15절 스키마, 19절 event 규약, 38절 상태 전이, 44절, 45절 | Step 3, Step 5, Step 7 |
| UI와 운영 화면 범위 팽창 | 30절, 33절, 41절, 46절 | MVP 이후 또는 Step 7 병행 |

### 60.1 이 표의 사용 방법

- 새 구현 태스크를 만들 때는 반드시 위 표의 문제 묶음 하나와 연결한다.
- 연결되지 않는 작업은 지금 범위 밖인지, 아니면 요구사항이 빠졌는지 먼저 판단한다.
- live 전환 승인 시에는 P0, P1에 해당하는 행이 모두 닫혔는지 확인한다.
