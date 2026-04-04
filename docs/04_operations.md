# Operations and Reliability

이 문서는 관측성, 배포, 운영 보안, 장애 대응 원칙을 정리한다. 운영 도구와 runbook 변경은 이 문서를 기준으로 맞춘다.

`private_http` 실연결 직전 준비와 운영 체크는 `04_private_http_go_live_checklist.md`를 함께 본다.


## 23. Observability Spec

새 프로젝트는 처음부터 관측 가능해야 한다.
즉, 로그와 메트릭은 나중에 붙이는 것이 아니라 제품 핵심 요구사항이다.

### 23.1 로그 규칙

모든 핵심 로그는 JSON structured logging으로 출력한다.

필수 공통 필드:

- `timestamp`
- `level`
- `service`
- `module`
- `event_name`
- `bot_id`
- `strategy_run_id`
- `trace_id`
- `message`

예시:

```json
{
  "timestamp": "2026-04-03T14:13:00Z",
  "level": "INFO",
  "service": "strategy-worker",
  "module": "arbitrage_engine",
  "event_name": "order_intent_created",
  "bot_id": "uuid",
  "strategy_run_id": "uuid",
  "trace_id": "trc_123",
  "message": "arbitrage opportunity accepted"
}
```

### 23.2 메트릭 초안

#### Control Plane

- `control_plane_http_requests_total`
- `control_plane_http_request_duration_seconds`
- `control_plane_active_bots`
- `control_plane_active_strategy_runs`

#### Strategy Worker

- `strategy_decisions_total`
- `strategy_decisions_rejected_total`
- `strategy_order_intents_total`
- `strategy_shadow_orders_total`
- `strategy_live_orders_total`
- `strategy_decision_duration_seconds`

#### Market Data

- `market_orderbook_updates_total`
- `market_orderbook_stale_total`
- `market_orderbook_age_ms`
- `market_ws_reconnects_total`

#### Orders

- `orders_submitted_total`
- `orders_failed_total`
- `orders_filled_total`
- `orders_cancelled_total`
- `order_submission_latency_ms`

#### Alerts

- `alerts_emitted_total`
- `alerts_acknowledged_total`

### 23.3 Alert 정책 초안

초기 버전에서 반드시 알림 대상이 되어야 하는 이벤트:

- heartbeat 누락
- market data stale 증가
- repeated order failure
- config apply 실패
- worker crash
- DB 또는 Redis 연결 불가

권장 alert level:

- `info`: 일반 운영 이벤트
- `warn`: 운영자가 봐야 하는 이상 징후
- `error`: 즉시 대응이 필요한 장애
- `critical`: 실주문 중단 또는 강제 정지 고려

### 23.4 Dashboard 초안

초기 Grafana 또는 운영 조회 화면에서 보여야 할 최소 패널:

- active bots
- active strategy runs
- heartbeat lag
- orderbook age by exchange
- decision accepted vs rejected
- live orders / shadow orders count
- alert event count by level

## 25. Deployment Runbook 초안

이 섹션은 새 프로젝트를 실제로 배포하고 운영할 때 필요한 최소 런북 초안이다.
초기 버전은 Docker Compose 기반 운영을 기준으로 한다.

### 25.1 배포 단위

초기 배포 단위는 다음 5개다.

- `control-plane`
- `strategy-worker`
- `postgres`
- `redis`
- `notifier-dispatcher` 또는 alert worker

선택 배포:

- `grafana`
- `prometheus`
- `nginx` 또는 reverse proxy

### 25.2 환경 구분

필수 환경은 아래 3개다.

- `local`
- `staging`
- `production`

환경별로 분리해야 하는 것:

- PostgreSQL DB
- Redis DB 또는 namespace
- config set
- secret source
- alert destination
- bot registration scope

### 25.3 필수 환경 변수 초안

#### 공통

- `APP_ENV`
- `LOG_LEVEL`
- `TZ`

#### Control Plane

- `CONTROL_PLANE_HOST`
- `CONTROL_PLANE_PORT`
- `DATABASE_URL`
- `REDIS_URL`
- `ADMIN_TOKEN`

#### Strategy Worker

- `WORKER_ID`
- `DATABASE_URL`
- `REDIS_URL`
- `CONFIG_SCOPE`
- `RUN_MODE`

#### Notification

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SLACK_WEBHOOK_URL`

### 25.4 Secret 관리 원칙

- `.env`는 저장소에 커밋하지 않는다.
- 운영 secret은 vault 또는 배포 환경 secret store를 우선 사용한다.
- local 개발 시에만 `.env.local` 또는 별도 local secret file 허용
- bot API key/secret은 strategy worker가 직접 읽되 Control Plane DB에는 평문 저장 금지

### 25.5 초기 배포 순서

#### Local

1. PostgreSQL 기동
2. Redis 기동
3. Alembic migration 적용
4. Control Plane 기동
5. Strategy Worker 기동
6. Health check 확인
7. dry-run smoke test 수행

#### Staging

1. DB backup 또는 빈 스테이징 DB 준비
2. migration 적용
3. Control Plane 배포
4. Worker 배포
5. metrics / health / alert 확인
6. shadow mode smoke test 수행

#### Production

1. maintenance window 확인
2. DB backup 확인
3. migration 적용
4. Control Plane rolling deploy
5. Worker deploy
6. health / ready / metrics 확인
7. bot registration 확인
8. dry-run 또는 shadow sanity 확인
9. 제한적 live enable

### 25.6 최초 기동 체크리스트

- `/api/v1/health` 응답 정상
- `/api/v1/ready` 응답 정상
- PostgreSQL 연결 정상
- Redis 연결 정상
- Prometheus scrape 정상
- bot register 정상
- heartbeat 적재 정상
- alert hook 정상
- config latest 조회 정상

### 25.7 운영 모드 전환 규칙

#### Dry-run -> Shadow

전환 전 조건:

- order intent 생성 정상
- decision record 적재 정상
- heartbeat 안정
- stale alert 비정상적으로 많지 않음

#### Shadow -> Live

전환 전 조건:

- shadow 결과가 기대값과 유사
- alert noise 정리 완료
- rate limit 정책 검증 완료
- stop command 즉시 반영 확인
- 운영자 승인 완료

### 25.8 장애 대응 우선순위

#### 1순위: 실주문 중지

다음 조건이면 즉시 live mode를 차단한다.

- repeated order failure 증가
- balance mismatch 반복 발생
- stale orderbook 급증
- exchange auth 오류 지속
- DB 또는 Redis 불안정

#### 2순위: worker 격리

- 특정 worker만 문제면 해당 worker만 stop
- 다른 worker는 정상 유지

#### 3순위: Control Plane read-only 전환

- 쓰기 경로 문제 발생 시 운영 조회 API만 유지하고 명령 API 차단 가능해야 한다.

### 25.9 운영 명령 런북

#### 전략 중지

1. `/api/v1/strategy-runs/{run_id}/stop` 호출
2. stop accepted 확인
3. worker 상태가 `stopped`로 전이되는지 확인
4. live order 제출이 더 이상 없는지 확인

#### bot 격리

1. bot status 확인
2. config assignment 해제 또는 disable config 적용
3. heartbeat 중단 확인
4. alert noise 정리

#### config 롤백

1. 이전 `config_version` 조회
2. 대상 bot에 재할당
3. 적용 이벤트 확인
4. post-apply sanity check 수행

### 25.10 릴리즈 체크리스트

- migration 검토 완료
- OpenAPI 변경 검토 완료
- alert rule 변경 검토 완료
- metrics 대시보드 영향 확인
- rollback plan 존재
- live mode 영향 범위 명시

## 39. 인증, 비밀관리, RBAC 초안

### 39.1 비밀관리 원칙

- 거래소 API secret은 DB 평문 저장 금지
- control plane은 secret metadata만 저장
- 실제 secret 값은 외부 secret manager 또는 로컬 encrypted file source 사용
- worker는 기동 시 필요한 secret만 메모리에 로드
- secret rotation은 bot 재기동 없이 가능하도록 versioned reference 사용

### 39.2 권장 권한 모델

초기 UI와 API는 최소 세 역할로 시작한다.

- `viewer`
- `operator`
- `admin`

권한 범위:

- `viewer`: 조회 전용, bot/주문/알림/로그 조회 가능
- `operator`: pause/resume, dry-run 전환, config 배포 승인 요청 가능
- `admin`: secret 등록, bot 생성, live 모드 전환 승인, 권한 관리 가능

### 39.3 민감 동작의 이중 보호

다음 동작은 단순 API 호출만으로 끝내지 않는다.

- live mode 전환
- 거래소 키 교체
- emergency stop 해제
- config version production assignment

권장 보호:

- reason 필드 필수
- audit log 기록
- 2단계 승인 또는 admin 권한 한정

### 39.4 Audit Log 초안

초기 MVP에서도 아래 이벤트는 별도 저장한다.

- 누가 언제 어떤 bot을 pause/resume 했는지
- 누가 어떤 config version을 배포했는지
- 누가 live mode를 활성화했는지
- 누가 secret reference를 교체했는지

추가 테이블 제안:

- `audit_events(id, actor_id, actor_role, action, target_type, target_id, payload_json, created_at)`

## 47. 운영자 장애 대응 플레이북 심화판

운영자는 장애 유형별로 같은 판단을 반복하지 않도록 표준 절차를 가져야 한다.

### 47.1 장애 등급

- `sev-1`: live 손실 위험 또는 자동매매 전면 중단
- `sev-2`: 일부 bot 거래 불가 또는 정합성 훼손 가능성 높음
- `sev-3`: 기능 일부 저하, 우회 가능
- `sev-4`: 관찰성/표시 문제

### 47.2 공통 초동 대응

1. Dashboard에서 영향 범위 확인
2. sev-1 또는 sev-2면 신규 진입 차단 여부 먼저 판단
3. 최근 alert, bot heartbeat, exchange connector health 확인
4. 관련 strategy run, order intent, order 상태 확인
5. raw error payload와 최근 reconciliation 이벤트 확인

### 47.3 장애 유형별 우선 절차

#### A. 거래소 Public WS 단절

1. connector 상태가 `degraded`로 전환되었는지 확인
2. REST fallback 동작 여부 확인
3. freshness SLA 초과 시 신규 주문 차단 확인
4. 재연결 backoff 루프가 정상인지 확인
5. 장기 단절 시 해당 거래소 사용 bot을 `paused` 또는 `degraded` 유지

#### B. 거래소 Private API 인증 실패

1. 특정 bot만 영향인지 전체 계정 영향인지 구분
2. key rotation 또는 IP 제한 변경 이력 확인
3. 최근 secret reference 변경 여부 확인
4. auth 실패가 지속되면 live 주문 차단
5. 필요 시 admin이 새 secret version 배포

#### C. 주문 제출 후 상태 미확정

1. exchange order id 생성 여부 확인
2. private WS event 수신 여부 확인
3. REST order detail 조회 수행
4. reconciliation job 수동 실행
5. terminal 상태 확정 전까지 동일 의도의 재주문 금지

#### D. 한쪽 leg만 체결

1. current exposure와 손실 위험 계산
2. unwind engine 자동 진입 여부 확인
3. 자동 unwind 실패 시 operator가 manual handoff 수행
4. 이후 동일 bot 신규 진입 일시 차단
5. incident record와 postmortem 후보로 표시

#### E. DB 또는 Redis 장애

1. control plane write path 영향 범위 확인
2. event bus 적재 실패 여부 확인
3. 전략 worker가 fail-closed 되었는지 확인
4. 정합성 훼손 가능 시 전체 live 신규 주문 중지
5. 복구 후 reconciliation full scan 수행

### 47.4 즉시 중단 기준

아래 조건 중 하나면 해당 bot 또는 전체 시스템의 신규 진입을 즉시 중단한다.

- private auth 실패 지속
- balance snapshot stale 지속
- orderbook freshness 실패 지속
- hedge mismatch 누적
- DB write 실패 또는 reconciliation backlog 급증
- 동일 exchange에서 terminal 상태 불일치 반복

### 47.5 장애 기록 표준

모든 sev-1/sev-2 장애는 아래를 남긴다.

- `incident_id`
- 발생 시각
- 감지 경로
- 영향 범위
- 최초 증상
- 초동 대응
- 최종 원인
- 손실 또는 미체결 영향
- 재발 방지 항목

추가 테이블 제안:

- `incident_events`
  - `id`
  - `severity`
  - `status`
  - `title`
  - `summary`
  - `detected_at`
  - `resolved_at`
  - `owner`
  - `payload_json`

### 47.6 사후 검토 기준

아래 중 하나에 해당하면 postmortem 작성 대상이다.

- 실제 금전 손실 발생
- unwind engine 실패
- live bot 10분 이상 중단
- 거래소 auth 정책 변경을 사전 탐지하지 못함
- reconciliation job이 terminal 상태 불일치를 복구하지 못함
