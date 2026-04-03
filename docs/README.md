# Documentation Index

이 저장소의 설계 문서는 역할별로 분리되어 있다. 먼저 `00_system_overview.md`를 읽고, 이후 작업 범위에 맞는 세부 문서로 내려간다. 기존 병합 문서의 섹션 번호는 참조 호환성을 위해 그대로 유지했다.

- `00_system_overview.md`: 제품 비전, 목표, 요구사항, MVP 범위, 구현 순서
- `01_architecture.md`: 시스템 구조, 디렉터리 구조, 상태 전이
- `02_data_model.md`: PostgreSQL, Redis, migration 정책
- `03_api_contracts.md`: API 명세와 OpenAPI 초안
- `04_operations.md`: observability, deployment, auth/RBAC, 장애 대응
- `05_strategy_and_risk.md`: 전략/리스크 설계 인덱스
  관련 상세 문서: `05_strategy_records.md`, `05_trade_recovery.md`, `05_risk_and_config.md`
- `06_exchange_adapters.md`: 거래소 설계 인덱스
  관련 상세 문서: `06_exchange_adapter_core.md`, `06_exchange_protocol_reference.md`, `06_exchange_validation.md`
- `07_ui_and_control_plane.md`: UI 설계 인덱스
  관련 상세 문서: `07_ui_design.md`, `07_frontend_query_contract.md`
- `08_execution_plan.md`: 실행 계획 인덱스
  관련 상세 문서: `08_progress_and_gaps.md`, `08_delivery_plan.md`, `08_execution_risk_matrix.md`
- `09_openapi_reference.md`: OpenAPI YAML 전문
- `10_storage_sql_reference.md`: Alembic initial migration SQL 전문
