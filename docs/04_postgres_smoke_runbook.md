# PostgreSQL Smoke Runbook

이 문서는 PostgreSQL을 실제로 붙인 상태에서 control plane을 빠르게 확인하는 최소 절차를 적는다.
메모리 저장소 smoke와 구분해서, 여기서는 `read_store=postgres`가 실제로 잡히는지 확인하는 데 집중한다.


## 목적

- PostgreSQL DSN이 실제로 붙는지 확인
- migration 적용 순서를 고정
- 서버 기동 후 최소 확인 API를 짧은 순서로 정리
- preflight와 smoke를 분리


## 1. 준비

필수 환경 변수:

- `TP_POSTGRES_DSN`
- `TP_REDIS_URL`
- `TP_ENABLE_POSTGRES_MUTATION=true`
- 필요 시 `TP_ADMIN_TOKEN`

권장:

- `TP_USE_SAMPLE_READ_MODEL=false`
- `TP_STRATEGY_RUNTIME_ENABLED=false`
- `TP_RECOVERY_RUNTIME_ENABLED=false`

확인:

- PostgreSQL 인스턴스가 실행 중이어야 한다.
- Redis도 같이 실행 중이어야 `/api/v1/ready`가 `ok`가 된다.
- `TP_POSTGRES_DSN`에는 비밀값이 들어가므로 로그나 문서에 그대로 남기지 않는다.


## 2. Preflight

1. `PYTHONPATH=src ./.venv/bin/python tools_for_ai/db_inspect.py`
2. `.tmp/db_report/` 안에 현재 DB 구조 리포트가 생성됐는지 확인
3. migration 디렉터리와 DB 구조가 크게 어긋나지 않는지 확인
4. `TP_USE_SAMPLE_READ_MODEL`이 꺼져 있는지 다시 확인

성공 기준:

- DB 접속이 되고 구조 리포트가 생성됨
- 민감정보가 리포트에 노출되지 않음


## 3. Migration 적용

현재 저장소는 migration SQL 기준 문서를 `10_storage_sql_reference.md`에 두고 있다.
실제 적용 방식은 운영 스크립트나 수동 SQL 실행 방식 중 하나를 택하되, 아래 순서는 고정한다.

1. 빈 DB 또는 staging 대상 DB 준비
2. schema 생성
3. 초기 migration 적용
4. bot / strategy / order / alert 관련 테이블 생성 확인
5. 인덱스와 제약조건 확인

성공 기준:

- 테이블 생성 실패 없음
- 핵심 조회 API가 startup 직후 schema error 없이 동작


## 4. 서버 기동

권장 기동 조건:

- strategy runtime 비활성화
- recovery runtime 비활성화
- sample read model 비활성화

최소 확인 순서:

1. 서버 기동
2. `/api/v1/health`
3. `/api/v1/ready`
4. `/api/v1/bots`
5. `/api/v1/configs/{config_scope}/latest` 또는 `/api/v1/configs/{config_scope}/versions`

`/api/v1/ready`에서 꼭 봐야 할 값:

- `data.status == "ok"`
- `data.read_store.mode == "postgres"`
- `data.readiness_checks.dependencies_ready == true`
- `data.readiness_checks.redis_runtime_ready == true`
- `data.readiness_checks.read_store_ready == true`


## 5. Smoke Write

`TP_ENABLE_POSTGRES_MUTATION=true`일 때만 진행한다.

최소 순서:

1. `POST /api/v1/bots/register`
2. `POST /api/v1/bots/{bot_id}/heartbeat`
3. `GET /api/v1/bots`
4. `GET /api/v1/bots/{bot_id}`
5. 필요 시 `POST /api/v1/configs`

`TP_ADMIN_TOKEN`이 켜져 있으면 write 요청은 `Authorization: Bearer <token>`이 필요하다.

성공 기준:

- 등록한 bot이 read API에서 다시 조회됨
- heartbeat가 최근 시각으로 반영됨
- write API가 인증/기본 rate limit 정책과 충돌하지 않음


## 6. 실패 시 우선 확인

- `/api/v1/ready`가 `degraded`인지
- `read_store.mode`가 `postgres`가 아니라 `memory_*`로 내려갔는지
- 최근 `logs/`에서 `postgres`, `migration`, `store`, `ready` 관련 에러가 있는지
- `TP_USE_SAMPLE_READ_MODEL`이 잘못 켜져 있지 않은지


## 7. 종료 기준

이 runbook은 아래를 만족하면 통과로 본다.

- preflight 성공
- migration 성공
- `/api/v1/ready`가 `ok`
- `read_store.mode == "postgres"`
- 최소 write/read smoke 성공
