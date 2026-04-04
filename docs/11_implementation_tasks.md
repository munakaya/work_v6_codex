# Implementation Task Board

이 문서는 설계 문서를 실제 구현 작업으로 옮길 때 쓰는 시작용 작업판이다. 세부 설계는 각 문서를 따르되, 구현 순서와 선행조건은 여기서 빠르게 판단한다.

## 1. 즉시 착수 가능 작업

### T1. 프로젝트 골격

- 목표: FastAPI 앱, 기본 패키지 구조, health endpoint, 설정 로더 골격 만들기
- 선행 문서: `00_system_overview.md`, `01_architecture.md`, `03_api_contracts.md`
- 완료 기준:
  - `/api/v1/health`, `/api/v1/ready` 라우트 존재
  - 앱 실행 엔트리포인트와 설정 모듈 분리
  - 로그 초기화 위치가 정해짐

### T2. 저장소 골격

- 목표: PostgreSQL, Redis, Alembic 연결 골격과 기본 스키마 만들기
- 선행 문서: `02_data_model.md`, `10_storage_sql_reference.md`
- 완료 기준:
  - Alembic initial revision 생성
  - `bots`, `strategy_runs`, `bot_heartbeats`, `alert_events` 테이블 생성 가능
  - Redis 연결과 key prefix 정책 반영

### T3. Control Plane 읽기 경로

- 목표: bot 목록/상세, heartbeat, alert 조회 API 먼저 열기
- 선행 문서: `03_api_contracts.md`, `04_operations.md`
- 완료 기준:
  - bot list/detail API 동작
  - 최근 heartbeat와 alert 조회 가능
  - request_id, 기본 에러 포맷 반영

### T4. 관측성 기본 세트

- 목표: structured logging, metrics, alert hook 기본 모듈 만들기
- 선행 문서: `04_operations.md`
- 완료 기준:
  - 로그 포맷 규칙 반영
  - metrics endpoint 또는 exporter 골격 존재
  - critical alert 전송 경로 1개 준비

## 2. 구현 직전 확정 필요 항목

- E1. 거래소 공식 문서 버전 pinning
  - 참조 문서: `06_exchange_adapter_core.md`, `06_exchange_protocol_reference.md`
- E2. symbol / fee / precision source of truth 확정
  - 참조 문서: `06_exchange_protocol_reference.md`
- E3. secret manager 방식 확정
  - 참조 문서: `04_operations.md`
- E4. live mode 승인 절차 확정
  - 참조 문서: `08_execution_risk_matrix.md`

## 3. 권장 구현 순서

1. T1 프로젝트 골격
2. T2 저장소 골격
3. T4 관측성 기본 세트
4. T3 Control Plane 읽기 경로
5. 거래소 public market data connector
6. config compiler + risk evaluator
7. strategy runtime + dry-run
7a. arbitrage executable edge / reservation
7b. arbitrage decision validation cases
7c. arbitrage reject-code precedence
7d. arbitrage lifecycle state machine
8. order execution + reconciliation
9. unwind + alert 강화
10. shadow 운영 검증

## 4. 작업선별 문서 진입점

- 백엔드 코어: `01_architecture.md`, `02_data_model.md`, `03_api_contracts.md`
- 운영/인프라: `04_operations.md`, `08_execution_risk_matrix.md`
- 전략/리스크: `05_strategy_records.md`, `05_trade_recovery.md`, `05_risk_and_config.md`
- 재정거래 구현 세부: `05_arbitrage_algorithm_review.md`, `05_arbitrage_algorithm_execution_spec.md`, `05_arbitrage_algorithm_validation_cases.md`, `05_arbitrage_reason_code_precedence.md`, `05_arbitrage_lifecycle_state_machine.md`
- 거래소 어댑터: `06_exchange_adapter_core.md`, `06_exchange_protocol_reference.md`, `06_exchange_validation.md`
- UI/프론트엔드: `07_ui_design.md`, `07_frontend_query_contract.md`
