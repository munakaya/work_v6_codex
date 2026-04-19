# work_v6_codex

이 저장소는 문서 중심으로 설계된 자동매매 플랫폼이며, 현재 구현은 `src/trading_platform/` 아래에 있다. 세부 설계 문서는 [docs/README.md](docs/README.md)에서 시작한다.

## 핵심 개념

이 프로젝트의 차익거래 계산은 아래 두 기준을 쓰지 않는다.

- `mid price`
- `best ask 1개 / best bid 1개`

대신 `상위 N레벨 오더북 depth`를 읽고, 실제 주문 수량이 그 depth를 타고 체결된다고 가정한 뒤 `실행 가능한 순수익(executable profit)`을 계산한다.

쉽게 말하면:

- `mid 기반` 계산: 화면상 가운데 가격이라 실제 체결가와 다를 수 있다.
- `top 1호가 기반` 계산: 1레벨 물량만 보고 계산해서 주문 수량이 조금만 커져도 왜곡될 수 있다.
- `top-N depth 기반 executable profit`: 실제 주문이 여러 호가에 나뉘어 체결된다고 보고 평균 체결가와 비용을 반영한다.

## `Executable Profit` 의미

예를 들어 `1 BTC`를 사야 하는데 매도호가가 아래처럼 있다고 가정한다.

- `100`에 `0.3 BTC`
- `101`에 `0.4 BTC`
- `102`에 `0.3 BTC`

그러면 실제 매수는 한 가격에 끝나지 않는다.

- `0.3 BTC`는 `100`
- `0.4 BTC`는 `101`
- `0.3 BTC`는 `102`

이렇게 나뉘어 체결되고, 그 평균 매수가가 `buy VWAP`다.

반대편 거래소에서도 매도 시 `bids[]`를 위에서부터 먹으며 `sell VWAP`를 계산한다. 그 뒤 아래 비용을 반영한다.

- 매수 수수료
- 매도 수수료
- 매수 슬리피지 버퍼
- 매도 슬리피지 버퍼
- unwind buffer
- rebalance buffer

마지막으로 아래 값을 계산한다.

- `gross_profit_quote`
- `executable_profit_quote`
- `executable_profit_bps`

즉 이 프로젝트에서 보는 이익은

`화면상 가격 차이`가 아니라  
`실제 top-N depth를 따라 체결했을 때 남는 예상 순이익`

이다.

관련 코드는 아래에 있다.

- [arbitrage_pricing.py](src/trading_platform/strategy/arbitrage_pricing.py)
- [arbitrage_reservation.py](src/trading_platform/strategy/arbitrage_reservation.py)
- [arbitrage_runtime_loader.py](src/trading_platform/strategy/arbitrage_runtime_loader.py)
- [arbitrage_simulation.py](src/trading_platform/strategy/arbitrage_simulation.py)
- [market_data_connector.py](src/trading_platform/market_data_connector.py)

## 핵심 알고리즘

아래 순서로 계산한다.

1. 각 거래소 public REST orderbook에서 `상위 N레벨 depth`를 읽는다.
2. 매수 거래소 `asks[]`, 매도 거래소 `bids[]`를 준비한다.
3. 주문 가능 수량 `q`를 계산한다.
   - buy side depth 총수량
   - sell side depth 총수량
   - `available_quote`에서 고정 버퍼와 매수 비용 계수를 반영한 실제 매수 가능 수량
   - `available_base`
   - `max_notional_per_order`
   - `max_total_notional_per_bot`
   - `remaining_bot_notional`
   - 위 후보 중 최소값을 `q`로 잡는다.
4. `q`만큼 매수 side `asks[]`를 소비해서 `buy VWAP`를 계산한다.
5. `q`만큼 매도 side `bids[]`를 소비해서 `sell VWAP`를 계산한다.
6. `gross_profit_quote = sell proceeds - buy cost`를 계산한다.
7. 매수/매도 수수료, 양쪽 슬리피지 버퍼, unwind/rebalance buffer를 차감한다.
8. 최종 `executable_profit_quote`, `executable_profit_bps`를 계산한다.
9. 예약 단계에서 아래가 실제로 가능한지 다시 확인한다.
   - 매수측 quote 잔고가 `매수원금 + 매수수수료 + 매수슬리피지버퍼 + 고정버퍼`를 감당하는지
   - 매도측 base 잔고가 `q`를 감당하는지
10. 최소 이익, 최소 bps, freshness/stale, 리스크 한도를 통과하면 기회로 본다.

## 무엇을 질문해야 하나

이 프로젝트에서 의미 있는 질문은 아래가 아니다.

- `mid가 얼마나 벌어졌나?`
- `best ask/bid 차이가 있나?`

실제로 물어야 하는 질문은 이것이다.

- `내가 실제로 이 수량을 넣으면 depth를 다 먹고도 순이익이 남는가?`

따라서 low-liquidity 알트에서는 `mid`나 `top-of-book` 기준 해석이 쉽게 왜곡될 수 있고, 이 프로젝트는 그 왜곡을 줄이기 위해 `top-N depth 기반 executable profit`으로 계산한다.

## 무엇이 아직 단순화돼 있나

현재 구현은 위 방향으로 계산하지만, 아래는 아직 완전한 실체결 재현이 아니다.

- 거래소 전체 book이 아니라 `상위 N레벨 depth`까지만 사용한다.
- 체결 저장은 레벨별 부분체결 목록이 아니라 `leg별 VWAP 1건`으로 단순화돼 있다.
- `min_profit_quote=0`과 `min_profit_bps=0`이면 `0원 기회`도 accept될 수 있다.

즉 현재 구현은 정확히 말하면 `top-N depth 기반 executable profit 계산기`이며, 거래소 전체 오더북을 끝까지 따라간 완전한 체결 재현기는 아니다.

## 설정 메모

public REST에서 몇 레벨까지 읽을지는 아래 env로 정한다.

- `TP_MARKET_DATA_ORDERBOOK_DEPTH_LEVELS`

기본값은 `5`다.
Coinone은 허용하는 size 값이 제한돼 있어서, 내부적으로 지원 size로 보정해서 호출한다.

## 참고 문서

- [docs/README.md](docs/README.md)
- [docs/00_system_overview.md](docs/00_system_overview.md)
- [docs/05_arbitrage_algorithm_execution_spec.md](docs/05_arbitrage_algorithm_execution_spec.md)
- [docs/04_operations.md](docs/04_operations.md)
