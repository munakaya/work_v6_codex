# Migration Layout

이 디렉터리는 초기 PostgreSQL 스키마를 revision 단위 SQL 파일로 관리한다.

- `versions/0001_initial_core_tables.sql`: enum, bots, config, strategy run 핵심 테이블
- `versions/0002_market_and_balance_snapshots.sql`: market/balance snapshot
- `versions/0003_order_flow.sql`: order intent, order, fill
- `versions/0004_operations.sql`: heartbeat, positions, alerts

현재는 Alembic 의존성을 추가하지 않은 상태라 SQL 파일을 먼저 source of truth로 둔다. 이후 Alembic을 도입할 때 같은 revision 번호와 역할을 유지한다.
