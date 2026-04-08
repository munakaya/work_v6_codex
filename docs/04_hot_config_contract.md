# Hot Config Contract

이 문서는 config 할당과 적용 결과 ack의 최소 계약을 정한다.
현재 구현은 `assign-config`와 `config-ack` 두 단계로 나뉜다.


## 흐름

1. 운영자가 새 config version 생성
2. 운영자가 bot에 config version 할당
3. control plane은 새 assignment를 `pending`으로 기록
4. bot 또는 worker가 적용 결과를 `config-ack`로 보고
5. control plane은 `applied`, `rejected`, `restart_required` 중 하나로 상태를 갱신


## ack 상태

- `APPLIED`
- `REJECTED`
- `RESTART_REQUIRED`

응답과 bot detail에는 소문자 상태로 저장한다.

- `pending`
- `applied`
- `rejected`
- `restart_required`


## hot reload 가능 section

현재 최소 범위:

- `arbitrage_runtime.risk_config`
- `arbitrage_runtime.runtime_state.open_order_cap`
- `arbitrage_runtime.runtime_state.remaining_bot_notional`

위 경로만 바뀌면 `apply_policy=hot_reload`가 될 수 있다.
그 외 변경은 `restart_required`로 분류한다.


## 응답 핵심 필드

- `apply_status`
- `apply_policy`
- `changed_sections`
- `hot_reloadable_sections`
- `restart_required_sections`
- `acknowledged_at`
- `ack_message`


## 현재 한계

- 실제 worker가 section별로 부분 적용했는지까지는 아직 검증하지 않는다.
- 현재는 latest assignment 기준으로만 ack를 받는다.
- event stream 수준의 config apply timeline은 아직 없다.
