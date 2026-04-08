# Arbitrage Event Replay Runner

이 문서는 이벤트 순서로 현재 payload를 갱신하면서 재정거래 판단을 다시 돌리는 최소 replay 도구를 설명한다.
기존 `05_arbitrage_replay_runner.md`가 정적인 입력 payload 회귀라면, 이 문서는 이벤트 순서를 따라 상태를 바꾸는 쪽에 가깝다.


## 입력 형식

- `initial_payload`
- `events`

지원 이벤트:

- `base_orderbook`
- `hedge_orderbook`
- `base_balance`
- `hedge_balance`
- `runtime_state`
- `risk_config`
- `evaluate`


## 목적

- 기록된 이벤트 순서에 따라 판단 결과가 어떻게 바뀌는지 확인
- connector health, balance, orderbook patch가 decision에 미치는 영향 확인
- 전체 전략 event replay 전 단계의 최소 도구


## 한계

- 실제 Redis stream이나 private event raw payload를 직접 재생하지는 않는다.
- 현재는 내부 replay schema를 사용한다.
