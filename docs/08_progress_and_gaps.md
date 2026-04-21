# Progress and Open Gaps

이 문서는 현재 저장소의 설계 문서 완성도와 실제 구현/운영 준비도를 함께 보되,
둘을 같은 숫자로 섞어 과장하지 않기 위한 상태 메모다.
문서를 많이 썼는지보다, 지금 이 저장소가 어디까지 실제로 닫혀 있는지를 빠르게 판단할 때 사용한다.


## 24. 이 문서를 읽는 방식

이 문서를 볼 때는 아래 두 축을 분리해서 읽는다.

- 설계 완성도: 문서와 계약이 얼마나 정리되어 있는가
- 구현 준비도: 현재 코드가 local, staging, live 직전 기준으로 얼마나 닫혀 있는가

현재 저장소는 설계 완성도는 높은 편이지만, 실거래 준비도는 아직 중간 이하 구간이다.
특히 private execution 최종 경로, public WS-first collector, 정식 테스트 스위트, live/shadow 편차 계측, private balance refresh 관측성 보강이 아직 남아 있다.


## 31. 설계 문서 기준 진행 상태

### 31.1 비교적 안정된 영역

- 제품 비전 / 목표 / 비목표
- 상위 아키텍처와 구성 요소 분리
- PostgreSQL, Redis, runtime, control plane의 책임 분리
- API 초안과 OpenAPI 초안
- Redis key / stream 규약
- 운영 runbook과 smoke checklist의 기본 뼈대
- 재정거래 전략 문서군과 recovery 문서군
- 거래소 adapter 공통 방향과 validation 관점

### 31.2 아직 초안이거나 후속 구체화가 필요한 영역

- 거래소별 상세 contract와 실거래 edge case 표
- UI 상세 설계와 frontend query contract의 운영 수준 보강
- OpenAPI 완성본
- Redis event catalog 상세판
- migration revision 단위 문서
- alert threshold와 운영 지표 임계값
- live 승인 절차와 운영 역할 분담 문서

### 31.3 아직 약한 영역

- auth / RBAC 전체 설계
- object storage 사용 여부
- backtesting / replay 운영 절차
- 운영자 workflow 상세 문서
- SLO / SLA 정의

### 31.4 설계 완성도 재평가

문서 기준 현재 평가는 아래 정도가 맞다.

- PRD / 제품 방향: 90%
- 상위 아키텍처: 85%
- 데이터 모델: 80%
- API 계약: 80%
- 운영 문서: 75%
- 거래소 adapter 공통 설계: 75%
- 거래소별 상세 계약: 55%
- 웹 UI 상세 설계: 60%

해석:

- 프로젝트 착수용 상위 설계는 이미 충분하다.
- 반면 "문서가 많다"는 이유로 실제 구현 준비도까지 높다고 보면 안 된다.
- 지금 필요한 것은 PRD 확장보다 실거래에 직접 연결되는 공백을 닫는 일이다.


## 42. 구현 준비도와 실거래 준비도

### 42.1 현재 코드에서 이미 닫힌 항목

- control plane read/write 기본 API 골격
- PostgreSQL/Redis/readiness 기본 점검 경로
- private REST connector 최소 계약
- `private_http`가 임시 외부 위임 경로라는 메타데이터 노출
- in-process `private_connectors` execution path 추가
- Redis runtime의 `redis-cli` 의존 제거
- 운영 환경 write API fail-closed 기동 정책
- cached snapshot 우선 로딩과 direct REST 재조회 제거
- `tools_for_ai` 기반 실행형 회귀 케이스 축적

### 42.2 아직 실거래 전환을 막는 핵심 공백

- `private_connectors` 내장 execution path는 추가됐지만, cancel flow / 실계정 smoke / reconciliation 자동화는 미완료
- `private_http`는 아직 임시 외부 delegate 경로
- public WS-first collector 미완료
- collector coverage 확장 미완료
- pair-level trade lock 운영 검증/지표 보강 필요
- private balance refresh 관측성/캐시 정책 보강 필요
- 정식 `pytest/tests/CI` 체계 부재
- malformed `private_http` 응답의 서버 레벨 회귀 확대 필요
- live/shadow/sim 편차 계측 부재

### 42.3 구현 준비도 재평가

현재 저장소의 구현 준비도는 아래 정도가 맞다.

- local 개발/기능 검증 준비도: 80%
- staging 배포 준비도: 60%
- shadow 운영 준비도: 55%
- restricted live smoke 준비도: 40%
- 지속 운영 가능한 live readiness: 30%

해석:

- local에서 기능을 붙이고 회귀를 돌리는 기반은 꽤 올라와 있다.
- staging과 shadow는 가능하지만, 운영 편차와 실행 경로 안전장치가 아직 부족하다.
- live readiness는 private connector 존재만으로 높게 볼 수 없고, execution path, collector, CI, 운영 편차 계측, private balance refresh 관측성이 닫혀야 한다.


## 48. 지금 가장 중요한 잔여 리스크

### 48.1 실거래 경로 리스크

- private REST connector는 이제 `private_connectors` execution path까지 편입됐지만 cancel flow, 실계정 smoke, reconciliation 자동화가 남아 있다.
- `private_http`는 계속 임시 경로이며, 외부 executor 의존 fallback을 아직 유지한다.

### 48.2 market data 리스크

- direct REST 재조회는 제거됐지만 public WS가 아직 기본 경로가 아니다.
- collector coverage가 충분하지 않아 `MARKET_SNAPSHOT_NOT_FOUND` 계열 실패를 완전히 낮추지 못했다.

### 48.3 동시성/중복 진입 리스크

- `(market, selected_pair)` 기준 pair-level lock과 `PAIR_LOCK_ACTIVE` fail-closed 경로는 들어갔다.
- 다거래소 candidate selection도 `selected_pair`/미선택 후보 기록까지 포함해 일반화됐다. 남은 공백은 편차 계측과 운영 지표 보강이다.

### 48.4 운영 검증 리스크

- 실행형 케이스는 쌓였지만 정식 테스트 집계/발견 체계가 없다.
- live/shadow/sim 편차를 운영 지표로 직접 보지 못한다.


## 54. 현재 상태 한 줄 요약

현재 저장소는 "설계 문서는 착수 가능 수준 이상"이지만, "실거래 준비가 거의 끝난 상태"는 아니다.
보다 정확한 표현은 아래에 가깝다.

- 설계 문서: 상위 구조는 충분히 정리됨
- 구현 상태: local/staging 검증 기반은 형성됨
- 실거래 상태: 아직 핵심 실행 공백이 남아 있음

다음 우선순위는 문서 확장보다 아래 작업들이다.

1. public WS-first collector 전환
2. `tools_for_ai` 핵심 케이스의 정식 테스트 승격
3. private execution 최종 경로 정리
4. live/shadow/sim 편차 계측 추가
5. private balance refresh 관측성 보강
