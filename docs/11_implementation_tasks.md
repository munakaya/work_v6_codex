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
7e. arbitrage recovery trace contract
7f. arbitrage runtime invariants
7g. arbitrage invariant code catalog
7h. arbitrage shadow-live gate
7i. arbitrage observability spec
7j. arbitrage replay restore accounting
7k. arbitrage incident taxonomy
7l. arbitrage test matrix
7m. multi-exchange candidate selection
7n. pair-level trade lock / duplicate entry guard
7o. per-exchange freshness / rate-limit aware scheduling
8. order execution + reconciliation
9. unwind + alert 강화
10. shadow 운영 검증

## 3.1 다거래소 재정거래 확장 메모

- 현재 구현은 `base_exchange + hedge_exchange` 고정 2거래소 평가를 기본으로 둔다.
- 다음 확장은 "3개 거래소 이상을 동시에 읽고, 이번 틱의 최적 pair를 고른 뒤 기존 2-leg execution으로 진입"하는 방향으로 본다.
- 즉, execution을 3-leg로 바꾸는 작업이 아니라 candidate selection을 다거래소화하는 작업으로 정의한다.

권장 세부 작업:

- M1. `candidate_exchanges[]` 입력 계약 정의
- M2. 거래소별 snapshot/balance/freshness 수집기 분리
- M3. 유효 조합 생성과 양방향 평가
- M4. `selected_pair` ranking 규칙 확정
- M5. pair-level lock 추가
- M6. shadow/live 비교 지표에 "미선택 후보와 선택 후보 차이" 추가
- M7. API 계약과 runtime loader의 `base_exchange/hedge_exchange` 호환 전환안 정리
- M8. 전략 핫패스에서 direct REST 재조회 제거, `market-data collector -> snapshot cache -> strategy runtime` 단일 경로로 정리
  현재 상태: direct REST 재조회 제거와 실행 중 arbitrage run 기반 poll target 확장까지 반영. 남은 범위는 WS collector 우선 전환과 collector coverage 추가 보강.
- M9. direct market read API와 strategy runtime이 같은 공인 IP rate budget을 잠식하지 않도록 cached read 우선 정책 정리
- M10. public WS를 top priority source로 두고 REST는 fallback/보정으로 제한하는 전환안 정리

## 4. 작업선별 문서 진입점

- 백엔드 코어: `01_architecture.md`, `02_data_model.md`, `03_api_contracts.md`
- 운영/인프라: `04_operations.md`, `08_execution_risk_matrix.md`
- 전략/리스크: `05_strategy_records.md`, `05_trade_recovery.md`, `05_risk_and_config.md`
- 재정거래 구현 세부: `05_arbitrage_algorithm_review.md`, `05_arbitrage_algorithm_execution_spec.md`, `05_arbitrage_algorithm_validation_cases.md`, `05_arbitrage_reason_code_precedence.md`, `05_arbitrage_lifecycle_state_machine.md`, `05_arbitrage_recovery_trace_contract.md`, `05_arbitrage_runtime_invariants.md`, `05_arbitrage_invariant_code_catalog.md`, `05_arbitrage_shadow_live_gate.md`, `05_arbitrage_observability_spec.md`, `05_arbitrage_replay_restore_accounting.md`, `05_arbitrage_incident_taxonomy.md`, `05_arbitrage_test_matrix.md`
- 거래소 어댑터: `06_exchange_adapter_core.md`, `06_exchange_protocol_reference.md`, `06_exchange_validation.md`
- UI/프론트엔드: `07_ui_design.md`, `07_frontend_query_contract.md`
