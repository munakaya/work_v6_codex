# Trading Platform Overview

이 문서는 새 트레이딩 플랫폼의 제품 관점 기준서다. 비전, 목표, 핵심 요구사항, MVP 범위를 먼저 읽고 전체 방향을 맞춘다.


## 1. 문서 목적

이 문서는 기존 `work_v4` 코드베이스를 직접 수정하기 위한 문서가 아니다.
이 문서는 기존 운영 경험에서 검증된 요구사항을 바탕으로, 새 자동매매 플랫폼을 처음부터 설계하고 구현하기 위한 PRD(Product Requirements Document)다.

핵심 목표는 다음과 같다.

- 봇 스크립트 묶음이 아니라 운영 가능한 트레이딩 플랫폼을 만든다.
- 전략, 거래소 연결, 상태 저장, 운영 관제를 명확히 분리한다.
- dry-run, shadow, live 실행 모드를 처음부터 제품 개념으로 포함한다.
- 파일 기반 운영이 아니라 DB, 이벤트, 관측성 중심 구조로 설계한다.

## 2. 배경

기존 시스템에서 확인된 운영 현실은 다음과 같다.

- 주문장 freshness가 실제 수익성과 안정성에 직접 영향을 준다.
- 단순 프로세스 생존 여부만으로는 정상 동작을 판단할 수 없다.
- 주문 후 잔고 및 체결 상태 재검증이 반드시 필요하다.
- 운영자가 즉시 볼 수 있는 상태 조회와 알림 체계가 필요하다.
- 설정 변경, 전략 중지, 재시작 같은 운영 개입은 시스템 기본 기능이어야 한다.

따라서 새 프로젝트는 "거래소 API를 호출하는 스크립트"가 아니라, "전략 실행 + 상태 저장 + 운영 제어 + 관측성"을 갖춘 시스템으로 설계해야 한다.

## 3. 제품 비전

새 프로젝트의 비전은 다음과 같다.

여러 거래소에 대해 공통된 방식으로 시장 데이터를 수집하고, 전략 워커가 이를 바탕으로 주문 의도를 생성하며, Control Plane이 상태/설정/운영 관제를 담당하는 이벤트 기반 트레이딩 플랫폼을 만든다.

이 플랫폼은 다음 특성을 가져야 한다.

- 거래소 추가가 쉽다.
- 전략 추가가 쉽다.
- 운영자가 시스템 상태를 즉시 파악할 수 있다.
- 실주문 전 dry-run과 shadow 검증이 가능하다.
- 장애와 오작동을 빨리 감지할 수 있다.

## 4. 목표

### 4.1 제품 목표

- 차익거래 전략 1개를 안정적으로 운영 가능한 수준으로 구현한다.
- 2~3개 거래소에 대해 공통 어댑터 구조를 제공한다.
- Control Plane을 통해 봇 상태, 설정 버전, 주문 이력, 알림 이벤트를 조회할 수 있어야 한다.
- 운영 중 실주문과 비실주문 모드를 안전하게 전환할 수 있어야 한다.

### 4.2 기술 목표

- Python 3.12 기반 비동기 아키텍처
- FastAPI 기반 Control Plane
- PostgreSQL 기반 영속 저장
- Redis 기반 hot state / event backbone
- 구조화 로그 + metrics + alert hook 기본 제공

### 4.3 운영 목표

- health check, heartbeat, alert가 제품 기본 기능일 것
- 운영자가 재시작/중지/설정 반영 상태를 확인할 수 있을 것
- 주문 실패, 응답 지연, stale data 증가 같은 운영 이슈를 관측 가능할 것

## 5. 비목표

초기 버전에서 아래는 목표가 아니다.

- 10개 이상의 거래소 동시 지원
- 다양한 전략 동시 제공
- 복잡한 웹 프론트엔드
- 완성형 백테스트 플랫폼
- 멀티 테넌트 SaaS 구조
- Kubernetes 전제 배포

초기 버전은 "기능 수"보다 "실행 품질과 운영 가능성"에 집중한다.

## 6. 핵심 사용자

### 6.1 운영자

시스템을 실제로 실행하고 상태를 확인하며, 설정을 바꾸고, 장애 시 개입하는 사용자다.

운영자가 원하는 것:

- 현재 어떤 봇이 살아있는지
- 어떤 전략이 어떤 설정 버전으로 동작 중인지
- 주문이 정상적으로 발생했는지
- 이상 상황이 발생했는지
- 즉시 중지할 수 있는지

### 6.2 전략 개발자

전략 로직과 리스크 규칙을 작성하는 사용자다.

전략 개발자가 원하는 것:

- 거래소 세부 구현을 몰라도 전략 작성 가능
- dry-run / shadow로 안전하게 검증 가능
- 입력 데이터와 실행 결과를 재현 가능
- 공통 도메인 모델을 재사용 가능

### 6.3 플랫폼 개발자

거래소 어댑터, 저장소, Control Plane, 알림, 배포를 구현하는 사용자다.

플랫폼 개발자가 원하는 것:

- 명확한 계층 경계
- 테스트 가능한 구조
- 모듈 간 계약이 분명한 인터페이스
- 운영 문제를 진단 가능한 로그/메트릭

## 7. 제품 원칙

### 7.1 운영 경험에서 반드시 계승할 규칙

- 주문장 freshness를 엄격하게 검사한다.
- 잔고 최신성과 주문장 최신성을 분리해서 본다.
- keep-alive는 프로세스 생존과 기능 생존을 구분해서 본다.
- 주문 후 반드시 체결/잔고를 재검증한다.
- 설정은 버전 관리 가능해야 한다.
- 운영자 관제와 알림은 선택 기능이 아니라 기본 기능이다.
- dry-run, shadow, live 실행 모드를 시스템 개념으로 명시한다.

### 7.2 설계 원칙

- 전략과 인프라를 분리한다.
- 읽기 모델과 쓰기 모델을 분리한다.
- 외부 시스템 연결은 어댑터 계층으로 격리한다.
- 파일 저장이 아니라 상태 모델과 이벤트 모델을 우선 정의한다.
- 모든 핵심 동작은 로그와 메트릭으로 관측 가능해야 한다.

## 8. 권장 기술 스택

### 8.1 애플리케이션

- Python 3.12
- FastAPI
- Pydantic v2
- asyncio

### 8.2 데이터 및 이벤트

- PostgreSQL
- Redis
- Redis Streams 또는 NATS
- SQLAlchemy 2
- Alembic

### 8.3 운영

- Docker Compose
- Prometheus
- Grafana
- JSON structured logging
- Telegram 또는 Slack notifier

## 11. 기능 요구사항

### 11.1 Control Plane

필수 기능:

- bot registry
- config version 관리
- bot 상태 조회 API
- 전략 실행 상태 조회 API
- 주문/체결 조회 API
- alert event 조회 API
- 운영 명령 API
  - start strategy
  - stop strategy
  - restart worker
  - apply config version

### 11.2 Strategy Worker

필수 기능:

- 시장 데이터 수신
- 전략 조건 평가
- OrderIntent 생성
- dry-run / shadow / live 실행 모드 지원
- 주문 후 체결/잔고 재검증
- heartbeat 전송
- structured log 발행

### 11.3 Exchange Adapter

거래소별 최소 계약:

- public orderbook REST
- public orderbook WS
- private balance
- private place order
- private order status
- rate limit 처리
- 오류 분류 및 재시도 정책

### 11.4 운영 인터페이스

필수 기능:

- alert hook
- heartbeat monitor
- stale data monitor
- order failure alert
- config apply result tracking

### 11.5 실행 모드

시스템은 아래 세 모드를 지원해야 한다.

- `dry-run`: 주문 의도만 계산, 외부 주문 호출 없음
- `shadow`: 주문 의도와 결과 추정 기록, 실주문 없음
- `live`: 실제 주문 실행

## 12. 비기능 요구사항

### 12.1 안정성

- 봇 heartbeat 누락 감지
- stale orderbook 감지
- 주문 실패 시 재시도 정책
- worker 단위 재시작 가능

### 12.2 관측성

- JSON structured logs
- bot, strategy, exchange 단위 metrics
- health endpoint
- alert hooks

### 12.3 보안

- 비밀정보는 저장소에 포함하지 않음
- 설정 템플릿과 실제 설정 분리
- API key / secret / token 암호화 또는 외부 secret source 사용

### 12.4 테스트 가능성

- 단위 테스트: 도메인, 전략 계산, 저장소 계약
- 통합 테스트: 거래소 mock, DB, Redis, API
- e2e 테스트: dry-run / shadow 흐름

## 13. MVP 범위

초기 버전은 아래 범위로 제한한다.

- FastAPI Control Plane 1개
- PostgreSQL 1개
- Redis 1개
- 거래소 어댑터 2~3개
- 차익거래 전략 1개
- dry-run + shadow + live 모드
- Telegram 알림
- 최소 운영 조회 API

## 14. 새 프로젝트 구현 순서

### Step 1. 도메인과 스키마 확정

- 핵심 엔티티 정의
- API 스키마 정의
- 이벤트 스키마 정의
- DB 테이블 초안 정의

### Step 2. Control Plane 구현

- health check
- bot registry
- config service
- status read API
- alert webhook endpoint

### Step 3. 저장소와 이벤트 백본 구현

- PostgreSQL schema
- Redis key / stream 규약
- repositories
- config version persistence

### Step 4. 거래소 어댑터 구현

MVP에서는 거래소 2~3개만 구현한다.

### Step 5. 전략 엔진 MVP 구현

- 차익거래 전략 1개
- freshness 검사
- min profit 검사
- OrderIntent 생성

### Step 6. Shadow Mode 검증

- 실주문 없이 판단 품질 검증
- alert / report / state 관찰

### Step 7. 제한된 Live Mode 전환

- 한 전략
- 한 코인 또는 소수 코인
- 낮은 볼륨
- 강한 안전장치

## 16. 성공 기준

초기 버전 성공 기준은 다음과 같다.

- 운영자가 Control Plane에서 봇 상태와 주문 이력을 볼 수 있다.
- dry-run과 shadow 모드에서 전략 의사결정이 기록된다.
- live 모드에서 제한된 전략이 안전하게 실행된다.
- 주문 실패, stale data, heartbeat 이상이 알림으로 전달된다.
- 전략, 거래소, 저장소, 알림 계층이 명확히 분리돼 테스트 가능하다.

## 17. 결론

새 프로젝트의 본질은 봇 스크립트 집합이 아니다.

최종적으로 만들고 싶은 것은 다음이다.

- 전략이 명확히 분리된 트레이딩 엔진
- 거래소 추가가 쉬운 어댑터 구조
- 읽기 모델과 운영 모델이 분리된 Control Plane
- DB 기반의 조회 가능 이력
- dry-run, shadow, live 전환이 가능한 실행 모델
- 관측 가능하고 테스트 가능한 운영 플랫폼

즉, 새 프로젝트는 "자동매매 코드"가 아니라 "트레이딩 운영 시스템"이어야 한다.
