# UI Design and User Flows

이 문서는 운영 UI의 범위, 화면 설계, 사용자 흐름을 모은다. 화면을 새로 추가하거나 범위를 조정할 때 먼저 확인한다.


## 30. 웹 UI 설계 진행 상태

웹 UI도 방향은 설계되어 있지만, 상세 화면 설계는 아직 초안 전 단계다.

### 30.1 현재 설계된 수준

문서상 이미 확정된 수준:

- Control Plane은 운영 조회와 명령을 담당
- 읽기 모델과 쓰기 모델 분리
- Grafana 기반 대시보드와 별도 운영 조회 API를 함께 고려

즉, UI는 "필수 운영 조회 화면" 위주로 가야 한다는 방향은 정해져 있다.

### 30.2 초기 UI 범위 제안

초기 웹 UI는 다음 5개 화면이면 충분하다.

1. Bot Overview
   - bot 목록
   - 상태
   - last seen
   - mode
   - assigned config version

2. Strategy Run Detail
   - run 상태
   - start/stop
   - 최근 decision count
   - reject reason 분포

3. Order / Fill Explorer
   - order_intents
   - orders
   - fills
   - exchange별 필터

4. Alert Center
   - alert 목록
   - level별 필터
   - acknowledge

5. Config Viewer
   - config scope
   - version history
   - latest assigned bots

### 30.3 아직 설계가 필요한 UI 항목

- 화면 IA
- 화면별 API dependency
- 인증 방식
- 관리자 권한 모델
- 다크/라이트 테마 여부
- Grafana와 자체 UI의 경계

### 30.4 UI 설계 상태 판단

- UI 역할 정의: 설계됨
- 초기 화면 목록: 설계됨
- 상세 와이어프레임: 미완료
- 프론트엔드 스택 결정: 미완료

즉, 웹 UI는 "무엇을 보여줘야 하는가"는 정리됐고, "어떻게 그릴 것인가"는 아직 남아 있다.

## 33. 웹 UI 상세 설계

웹 UI는 거래용 UI가 아니라 운영 UI다.
즉, 복잡한 차트 트레이딩 화면보다 "상태 확인, 이상 감지, 명령 실행"이 중심이어야 한다.

### 33.1 UI 목표

- 운영자가 현재 상태를 한눈에 본다.
- 문제 bot을 빠르게 찾는다.
- strategy run과 order flow를 추적한다.
- config 변경과 alert 확인을 처리한다.

### 33.2 프론트엔드 권장 스택

초기 버전 권장안:

- Next.js 또는 React + TypeScript
- TanStack Query
- Tailwind CSS
- shadcn/ui 또는 headless UI 계열 컴포넌트
- chart는 필요 최소만 사용

이유:

- 운영 UI는 복잡한 비주얼보다 빠른 개발과 명확한 상태 표현이 우선
- Control Plane API와 타입 연동이 쉬움

### 33.3 정보 구조(IA)

초기 IA 제안:

- `/bots`
- `/bots/{botId}`
- `/strategy-runs`
- `/strategy-runs/{runId}`
- `/orders`
- `/fills`
- `/alerts`
- `/configs`
- `/configs/{scope}`

### 33.4 화면 상세

#### 1. Bot Overview

목적:

- 전체 bot 상태를 빠르게 파악

주요 컬럼:

- bot key
- strategy
- mode
- status
- hostname
- last seen
- latest config version
- heartbeat lag

행동:

- 상세 이동
- stop / restart
- config assign

#### 2. Bot Detail

목적:

- 개별 bot의 최근 상태와 heartbeat, latest strategy run 확인

주요 섹션:

- bot summary
- latest heartbeat
- latest alerts
- recent order intents
- recent orders
- assigned config

#### 3. Strategy Run List / Detail

목적:

- 특정 run이 어떤 모드로 동작 중인지 확인

주요 정보:

- run status
- mode
- started_at / ended_at
- decision count
- reject reason distribution
- linked order intents

#### 4. Order / Fill Explorer

목적:

- 주문 흐름 추적

필터:

- bot
- strategy run
- exchange
- market
- status
- created range

테이블:

- order intent
- order
- fills

#### 5. Alert Center

목적:

- 경고와 장애를 우선순위대로 처리

필수 기능:

- level 필터
- acknowledged 필터
- bot 연관 링크
- acknowledge action

#### 6. Config Viewer

목적:

- config scope / version history 확인

필수 기능:

- latest config 조회
- version diff
- assigned bots 목록

### 33.5 상태 색상 규칙

- `running`: green
- `pending`: blue
- `stopped`: gray
- `failed`: red
- `warn`: amber
- `critical`: red 강조

운영 UI는 색상 규칙이 일관돼야 한다.

### 33.6 초기 UI에서 넣지 않을 것

- 고급 주문 수동 입력 화면
- 복잡한 캔들 차트
- 백테스트 리포트 대시보드
- 사용자별 커스텀 레이아웃

### 33.7 UI와 Grafana의 경계

자체 UI가 맡는 것:

- bot registry
- config version
- strategy run 상태
- order intent / order / fill 탐색
- alert ack
- 운영 명령

Grafana가 맡는 것:

- 시계열 heartbeat
- orderbook age 추이
- request latency
- alert volume trend

### 33.8 UI 상세 설계에서 다음으로 필요한 것

- 페이지별 wireframe
- 컴포넌트 목록
- route map
- API dependency map
- auth / RBAC 정책

## 41. UI 정보 구조와 핵심 사용자 흐름

33장의 웹 UI 상세 설계를 실제 제품 흐름 관점으로 다시 정리한다.

### 41.1 최상위 정보 구조

- Dashboard
- Bots
- Strategy Runs
- Orders / Fills
- Positions
- Alerts
- Configs
- Audit

### 41.2 Dashboard 핵심 카드

- 전체 bot 상태 요약
- exchange connector 상태
- 최근 1시간 alert 수
- 현재 degraded / paused bot 수
- 오늘 주문 건수, fill 건수, 실패 건수
- 최근 decision latency / order ack latency

### 41.3 Bot Detail 사용자 흐름

1. 운영자는 bot 목록에서 대상 bot 선택
2. 현재 run mode, strategy 상태, heartbeat freshness 확인
3. 최근 decision record와 latest alert 확인
4. 필요 시 pause/resume 또는 dry-run 전환 실행
5. 실행 내역은 audit trail에서 즉시 확인

### 41.4 Order Explorer 사용자 흐름

1. 거래소, bot, strategy run, 심볼, 시간 범위로 필터
2. order intent와 실제 order/fill를 한 화면에서 연결해 확인
3. 실패 주문은 internal error code와 raw payload를 함께 확인
4. replay/debug가 필요하면 decision record와 market snapshot으로 이동

### 41.5 Config 배포 사용자 흐름

1. 새 config version 생성
2. diff 확인
3. staging bot 또는 dry-run bot에 assignment
4. shadow 결과 확인
5. 승인 후 production assignment

### 41.6 초기 UI 비목표

- 차트 중심의 복잡한 수동 트레이딩 터미널
- 모바일 앱 우선 전략
- 사용자별 커스터마이징 대시보드
- 고급 BI 수준의 자유 질의 리포팅
