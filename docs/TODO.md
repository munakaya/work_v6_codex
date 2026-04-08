# TODO

이 문서는 아직 남아 있는 구현/운영 보강 항목을 짧게 적어두는 메모다.
이번 목록은 여러 참고 저장소를 검토해서 현재 저장소에 바로 도움이 되는 항목만 추렸다.

## 1. Hot config 적용/ack 계약

- config 일부만 재시작 없이 반영하는 규칙이 아직 없다.
- 최소 범위:
  - 즉시 반영 가능한 section 정의
  - `APPLIED`, `REJECTED`, `RESTART_REQUIRED` 같은 ack 계약 정의
  - 적용 후 runtime surface에서 변경 결과 확인 가능해야 함
- 참고:
  - `work_v6_gpt-pro/docs/hot_config_notes_v2_4.md`
  - `work_v6_gpt-pro/docs/release_candidate_checklist_v2_4.md`

## 2. PostgreSQL 실제 smoke runbook

- 로컬/메모리 검증은 늘었지만 실DB smoke 순서는 아직 약하다.
- 필요 항목:
  - 환경변수 준비
  - migration 적용 순서
  - 서버 기동 후 확인 API 목록
  - preflight와 실제 smoke를 구분한 스크립트/문서
- 참고:
  - `work_v6_gpt-pro/docs/postgres_smoke_runbook_v2_4.md`
  - `work_v6_gpt-pro/docs/final_gap_assessment_v2_4.md`

## 3. 거래소별 live smoke checklist

- private adapter는 골격만 있고, 실제 거래소 smoke 절차 문서가 더 구체적이면 좋다.
- 거래소별로 아래를 명시한다:
  - 인증 성공
  - 주문 가능 정보 조회
  - 소액 주문 제출/취소
  - 상태 조회
  - private WS 주문 이벤트 확인
  - timeline / balance / recovery surface 확인
- 참고:
  - `work_v6_gpt-pro/docs/live_smoke_checklist_v2_4.md`

## 4. RC/배포 체크리스트

- go-live 문서는 있지만 release candidate 관점의 공통 체크리스트가 아직 없다.
- 최소 항목:
  - compile/test
  - ready/runtime 핵심 endpoint 확인
  - PostgreSQL/Redis 실연결 확인
  - secret 배치 방식 확인
  - systemd 자동기동 / 재시작 정책 / 로그 rotate 확인
- 참고:
  - `work_v6_gpt-pro/docs/release_candidate_checklist_v2_4.md`
  - `work_v6_gpt-pro/docs/final_gap_assessment_v2_4.md`

## 5. 거래소 auth 단위 테스트

- 실제 private adapter를 붙일 때는 거래소별 서명 테스트를 먼저 추가하는 편이 안전하다.
- 우선 대상:
  - Upbit: repeated query order, JWT `query_hash`
  - Bithumb: timestamp, JWT `query_hash`
  - Coinone: signed payload/header
- 참고:
  - `work_v6_gpt-pro/tests/test_upbit_auth.py`
  - `work_v6_gpt-pro/tests/test_bithumb_auth.py`
  - `work_v6_gpt-pro/tests/test_coinone_auth.py`

## 6. 거래소 fixture / contract test 자산화

- 현재 문서에도 fixture와 mock payload가 미완료로 남아 있다.
- 실제 private/public adapter 구현 전에 아래 자산을 먼저 모으는 편이 안전하다:
  - 거래소별 정상 orderbook 응답
  - 주문 생성/조회/취소 응답
  - auth 실패 응답
  - rate limit 응답
  - partial fill / terminal fill 응답
- 참고:
  - `work_v6_claude/docs/exchange_adapter.md`
  - `work_v6_claude/test/unit/exchange_auth.test.ts`

## 7. 운영 알림 규칙 / 대시보드 구체화

- 운영 문서에 관측성 원칙은 있지만, 실제 알림 임계치와 대시보드 패널은 더 구체화할 여지가 있다.
- 최소 범위:
  - heartbeat 누락
  - circuit open 지속
  - unhedged position
  - API 에러 급증
  - orderbook latency p95
  - balance 급감
- 참고:
  - `work_v6_claude/docs/operations.md`

## 8. backtest / replay 실행 도구

- 현재 저장소 문서에도 backtesting / replay는 공백으로 남아 있다.
- 최소 목표:
  - 기록된 market/private event 재생 도구
  - 전략 판단 회귀 검증용 replay runner
  - 필요 시 csv export/import 또는 백업 보조 스크립트
- 참고:
  - `work_v6_claude/scripts/backtest.ts`
  - `work_v6_claude/scripts/csv_export.ts`
  - `work_v6_claude/scripts/csv_import.ts`

## 9. private WS 연결 상태 모니터링 표면

- 현재 문서에는 close code, ping scheduler, reconnect 정책이 있지만 런타임 표면은 더 구체화할 수 있다.
- 최소 범위:
  - 거래소별 private WS 연결 상태
  - 최근 disconnect 횟수
  - 마지막 성공 시각 / 마지막 실패 시각
  - close code 기반 분류 결과
  - runtime endpoint 또는 heartbeat 노출 방식 정의
- 참고:
  - `work_v4.1/packages/shared/src/network_monitor.ts`
  - `work_v4.1/docs/claude_result.md`

## 메모

- `spool`, `status file` 같은 항목은 외부 저장소 구조에는 맞지만 현재 저장소 구조와 바로 같지 않아서 이번 TODO에는 넣지 않았다.
- `trade lock`, `idempotency guard`는 중요하지만 현재 저장소 문서에도 관련 안전장치가 이미 흩어져 있어서, 이번 TODO에는 더 직접적인 공백만 남겼다.
- 거래소별 실제 주문/체결 구현은 여전히 공식 API 버전 pinning 이후에 진행하는 것이 맞다.
