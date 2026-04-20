# Release Candidate Checklist

이 문서는 go-live 직전 공통 RC 점검 목록을 적는다.
`04_private_http_go_live_checklist.md`가 private_http 실연결에 더 가깝다면, 이 문서는 control plane 전체의 공통 배포 후보 점검에 가깝다.


## 1. 코드/테스트

- `python -m py_compile src/trading_platform/*.py src/trading_platform/strategy/*.py`
- 최근 추가한 `tools_for_ai` 회귀 스크립트 통과
- 변경 범위와 직접 연결된 smoke 스크립트 통과


## 2. 설정

- `TP_USE_SAMPLE_READ_MODEL=false`
- PostgreSQL/Redis 운영 값 확인
- `APP_ENV=staging|production`이면 `TP_ADMIN_TOKEN` 필수 적용 확인
- write API 기본 rate limit 값 확인
- `/dev/shm/keys` 배치 방식과 fallback 정책 확인


## 3. 서버 기동 후 API 확인

- `/api/v1/health`
- `/api/v1/ready`
- `/api/v1/runtime/streams`
- `/api/v1/runtime/private-connectors`
- `/api/v1/runtime/private-ws`
- 필요 시 `/api/v1/market-data/runtime`

핵심 확인:

- `ready.status == ok`
- `read_store.mode == postgres`
- `redis_runtime.enabled == true`
- `write_api_guard` 설정이 의도와 일치


## 4. 운영 환경 확인

- PostgreSQL 실연결 확인
- Redis 실연결 확인
- log directory 권한 확인
- systemd 또는 실행기 재시작 정책 확인
- 로그 rotate 또는 보존 정책 확인


## 5. 거래소/시크릿 확인

- trading key 파일 배치 확인
- 거래소별 private connector 상태 확인
- 거래소별 private WS auth-ready 상태 확인
- live smoke 전 최소 권한 계정 확인


## 6. 승인/중단 기준

승인:

- compile/test 통과
- ready/runtime 핵심 API 정상
- PostgreSQL/Redis 실연결 확인
- secret 배치와 key 파일 정책 확인

중단:

- `memory_*` 저장소로 폴백
- ready `degraded`
- 거래소 key 누락
- write API 인증/limit 오동작
