# Progress and Open Gaps

이 문서는 현재 설계 진행 상태와 남은 공백을 추적한다. 지금 무엇이 준비되었고 무엇이 아직 비어 있는지 빠르게 판단할 때 사용한다.


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
