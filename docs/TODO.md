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

## 2. 거래소 fixture / contract test 자산화

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

## 3. backtest / replay 실행 도구

- 입력 payload replay runner는 추가됐지만, event-level replay와 import/export는 아직 없다.
- 최소 목표:
  - 기록된 market/private event 재생 도구
  - 필요 시 csv export/import 또는 백업 보조 스크립트
- 참고:
  - `work_v6_claude/scripts/backtest.ts`
  - `work_v6_claude/scripts/csv_export.ts`
  - `work_v6_claude/scripts/csv_import.ts`

## 메모

- `spool`, `status file` 같은 항목은 외부 저장소 구조에는 맞지만 현재 저장소 구조와 바로 같지 않아서 이번 TODO에는 넣지 않았다.
- `trade lock`, `idempotency guard`는 중요하지만 현재 저장소 문서에도 관련 안전장치가 이미 흩어져 있어서, 이번 TODO에는 더 직접적인 공백만 남겼다.
- 거래소별 실제 주문/체결 구현은 여전히 공식 API 버전 pinning 이후에 진행하는 것이 맞다.
