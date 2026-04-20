# Private HTTP Go-Live Checklist

이 문서는 `private_http` 실행 어댑터를 실제 외부 executor에 붙이기 전 마지막 준비와 운영 체크리스트를 정리한다.

목표는 단순하다.

- 잘못된 환경으로 live를 켜지 않는다
- health는 되는데 주문이 안 나가는 상태를 빨리 찾는다
- 문제 생기면 바로 `shadow` 또는 execution off로 되돌린다
- `private_http`가 최종 실행 경로가 아니라 임시 외부 위임 경로라는 점을 운영 화면에서 항상 보이게 유지한다


## 1. 언제 이 문서를 쓰는가

아래 조건이 모두 맞을 때 쓴다.

- control plane은 이미 기동된다
- PostgreSQL / Redis 연결이 된다
- `private_http` adapter 내부 검증은 통과했다
- 이제 실제 외부 private executor URL과 token을 넣으려 한다


## 2. 실연결 전에 준비할 것

필수 설정:

- `TP_STRATEGY_RUNTIME_EXECUTION_ENABLED=true`
- `TP_STRATEGY_RUNTIME_EXECUTION_MODE=private_http`
- `TP_STRATEGY_PRIVATE_EXECUTION_URL`
- `TP_STRATEGY_PRIVATE_EXECUTION_HEALTH_URL`
- `TP_STRATEGY_PRIVATE_EXECUTION_TIMEOUT_MS`
- `TP_REDIS_URL`
- `TP_POSTGRES_DSN`

선택 설정:

- `TP_STRATEGY_PRIVATE_EXECUTION_TOKEN`
- `TP_STRATEGY_RUNTIME_AUTO_UNWIND_ON_FAILURE`
- `TP_RECOVERY_RUNTIME_ENABLED=true`
- `TP_RECOVERY_RUNTIME_INTERVAL_MS`
- `TP_RECOVERY_RUNTIME_SUBMIT_TIMEOUT_SECONDS`
- `TP_RECOVERY_RUNTIME_HANDOFF_AFTER_SECONDS`
- `TP_RECOVERY_RUNTIME_RECONCILIATION_MISMATCH_HANDOFF_COUNT`
- `TP_RECOVERY_RUNTIME_RECONCILIATION_STALE_AFTER_SECONDS`

준비 원칙:

- key/token은 저장소에 넣지 않는다
- `.env`를 자동 생성하지 않는다
- 운영자는 쉘 export, secret store, systemd/Kubernetes secret 같은 방식으로만 넣는다


## 3. Live 전 체크

반드시 확인:

- `/api/v1/ready`에서 `dependencies.private_execution.configured=true`
- `/api/v1/ready`에서 `dependencies.private_execution.reachable=true`
- `strategy_runtime.execution_enabled=true`
- `strategy_runtime.execution_mode=private_http`
- `strategy_runtime.execution_adapter=private_http`
- `strategy_runtime.execution_path_kind=temporary_external_delegate`
- `strategy_runtime.execution_path_temporary=true`
- `dependencies.private_execution.temporary=true`
- Redis / PostgreSQL dependency가 같이 정상

보면 좋은 것:

- 최근 로그에 `private execution` 관련 `ERROR`, `Traceback`가 없는지
- 최근 `strategy_events`, `recovery_traces`가 비정상적으로 쌓이지 않는지
- `latest-evaluation`가 stale 상태로 오래 남지 않는지


## 4. 실연결 순서

권장 순서:

1. `shadow` bot 하나만 대상으로 시작
2. `/api/v1/ready`와 health probe 확인
3. `POST /api/v1/strategy-runs/{run_id}/evaluate-arbitrage`를 `persist_intent=true`, 필요 시 `execute=true`로 소량 검증
4. `latest-evaluation`, `orders`, `fills`, `recovery-traces`를 바로 확인
5. 이상 없으면 제한된 bot 수로 확대

처음부터 하지 말 것:

- 여러 bot 동시 live
- recovery runtime 없이 execution만 켜기
- health probe 없이 `TP_STRATEGY_PRIVATE_EXECUTION_URL`만 넣고 시작


## 5. 최소 smoke test

최소 성공 경로:

- `evaluate-arbitrage` 호출
- `submit_result.outcome=submitted` 또는 `filled`
- `latest-evaluation` 갱신
- 주문이 생기면 `orders` 조회 가능
- 체결이 생기면 `fills` 조회 가능

최소 실패 경로:

- 외부 executor가 실패 응답
- `submit_result.outcome=submit_failed`
- `lifecycle_preview=recovery_required` 또는 `unwind_in_progress`
- 필요 시 `recovery-traces` 생성

최소 timeout 경로:

- `submitted` 후 체결이 안 들어옴
- `TP_RECOVERY_RUNTIME_SUBMIT_TIMEOUT_SECONDS` 이후 recovery trace가 열림


## 6. 운영 중 꼭 볼 것

우선순위가 높은 신호:

- `/api/v1/ready`가 `degraded`로 바뀜
- `dependencies.private_execution.reachable=false`
- `submit_failure_count` 증가
- `recovery trace`가 반복적으로 `active` 또는 `handoff_required`로 남음
- `latest-evaluation`가 오래 `entry_submitting` 상태에 머묾

운영자가 바로 확인할 것:

- executor health URL 응답
- 최근 `strategy_runtime_failed`, `recovery_runtime_failed`, `redis_runtime_failed`
- 대상 run의 `latest-evaluation`
- 대상 run의 `recovery-traces`


## 7. 문제 생기면 바로 할 일

가장 빠른 완화:

- `TP_STRATEGY_RUNTIME_EXECUTION_ENABLED=false`
- 또는 대상 bot/run을 `shadow`로 유지
- 새 live bot 등록/시작 중지

이미 recovery로 넘어간 경우:

- `recovery-traces` 조회
- 필요 시 `handoff`
- 필요 시 `start-unwind`
- 필요 시 `submit-unwind-order`
- 필요 시 `record-unwind-fill`


## 8. 롤백 기준

즉시 롤백:

- health는 정상인데 실제 submit이 반복 실패
- 같은 유형의 `submit_failed`가 짧은 시간에 반복
- `manual_handoff`가 빠르게 누적
- 외부 executor 응답 형식이 기대와 다름

롤백 방법:

1. execution off
2. 대상 run stop
3. active recovery trace 확인
4. unresolved trace가 있으면 operator 처리
5. 원인 정리 후 다시 shadow부터 재시작


## 9. 완료 기준

key 넣기 전 단계 완료는 아래로 본다.

- `private_http` adapter fail-closed 검증 통과
- server flow 검증 통과
- follow-up 검증 통과
- 운영자가 필요한 env 이름과 확인 순서를 안다
- 문제 시 execution off와 recovery runbook 경로가 있다

실연결 완료는 아래가 추가로 필요하다.

- 실제 executor health 확인
- 실제 submit success/failure/timeout smoke test 확인
- 제한된 shadow/live 운영 확인
