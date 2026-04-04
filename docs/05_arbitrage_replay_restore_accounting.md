# Arbitrage Replay Restore Accounting

이 문서는 재정거래 전략에서 `replay restored`를 무엇으로 볼지 최소 계약을 정한다.
목적은 runtime invariant와 observability에서 이 값을 품질 지표로 오해하지 않고, 계수 보정으로만 쓰게 만드는 것이다.


## 핵심 원칙

- `replay restored`는 전략 판단 성공이 아니다.
- `replay restored`는 로컬 런타임이 놓친 사건을 reconciliation 또는 replay가 나중에 계수상 복구한 것이다.
- 이 값은 품질 보정보다 accounting 보정에만 쓴다.


## 언제 쓰는가

아래처럼 로컬 기록이 늦거나 누락된 경우에만 쓴다.

- private event 유실 후 reconciliation이 submit 사실을 복구
- fill event 유실 후 거래소 조회로 fill 사실을 복구
- 프로세스 재시작 후 persisted state와 거래소 상태를 다시 맞추며 누락 사건을 복구

아래에는 쓰지 않는다.

- 정상 로컬 경로에서 이미 기록된 사건 재집계
- 전략 판단 품질을 좋게 보이기 위한 보정
- reject를 accept처럼 보이게 만드는 보정


## 최소 stage

- `submitted`
- `filled`
- `unwind_started`

원칙:

- MVP에서는 `accepted` stage를 replay restored로 두지 않는다.
- decision accept는 exchange 외부 증거로 복구하는 값이 아니라 전략 내부 기록으로 남겨야 한다.


## 최소 메트릭

- `arbitrage_replay_restored_total{stage=submitted|filled|unwind_started}`

해석:

- `stage=submitted`는 submit 사건을 로컬 실시간 경로가 아니라 사후 복구로 채운 수
- `stage=filled`는 fill 사건을 사후 복구로 채운 수
- `stage=unwind_started`는 unwind 시작 사건을 사후 복구로 채운 수


## invariant 연계 규칙

`05_arbitrage_runtime_invariants.md`의 metric/accounting consistency에서는 아래처럼 본다.

- `submitted_count <= accepted_count + replay_restored_total{stage=submitted}`
- `filled_count <= submitted_count + replay_restored_total{stage=filled}`
- `unwind_started_count <= recovery_required_count + replay_restored_total{stage=unwind_started}`

원칙:

- replay restored는 역전 자체를 정상화하는 예외값이지, 무제한 면책 수단이 아니다.
- replay restored가 반복적으로 크면 별도 운영 문제로 본다.


## 운영 해석 규칙

- replay restored가 0에 가깝다는 것이 정상에 가깝다.
- 값이 커지면 event 유실, reconnect 문제, reconciliation 의존 과다가 먼저 의심 대상이다.
- live 승인 판단에서는 replay restored가 잦으면 shadow 안정성이 낮다고 본다.


## 권장 산출물

- `stage`
- `strategy_run_id`
- `bot_id`
- `canonical_symbol`
- `restored_at`
- `restore_source`
- `observed_gap`


## 구현 체크리스트

- replay restored는 별도 메트릭/로그로 남긴다.
- 일반 counter를 조용히 덮어쓰는 방식으로 숨기지 않는다.
- runtime invariant는 replay restored를 반영하되, 품질 지표와 섞어 해석하지 않는다.
