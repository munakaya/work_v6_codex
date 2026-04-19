# work_v6_codex

이 저장소는 문서 중심으로 설계된 자동매매 플랫폼이며, 현재 구현은 `src/trading_platform/` 아래에 있다. 세부 설계 문서는 [docs/README.md](docs/README.md)에서 시작한다.

## 핵심 개념

이 프로젝트의 차익거래 계산은 `mid price`를 쓰지 않는다.
또한 `best ask 1개`, `best bid 1개`만 보고 수익을 계산하지도 않는다.

대신 실제 주문 수량이 오더북 depth를 타고 내려가며 체결된다고 가정하고,
그 체결 평균가를 기준으로 수익을 계산한다.

쉽게 말하면:

- `mid 기반` 계산: 화면상 가운데 가격이라서 실제 체결가와 다를 수 있다.
- `top 1호가 기반` 계산: 1레벨 물량만 보고 계산해서 큰 주문이면 틀릴 수 있다.
- `VWAP 기반 executable profit`: 실제 수량을 각 레벨에 나눠 체결했을 때의 평균 매수가/매도가로 계산한다.

## 실제 체결 가능한 VWAP 기반 executable profit 의미

예를 들어 `1 BTC`를 사야 하는데,
매도호가가 아래처럼 있다고 가정한다.

- `100`에 `0.3 BTC`
- `101`에 `0.4 BTC`
- `102`에 `0.3 BTC`

그러면 실제 매수는:

- `0.3 BTC`는 `100`
- `0.4 BTC`는 `101`
- `0.3 BTC`는 `102`

로 나뉘어 체결된다.
이때 평균 매수가가 `buy VWAP`다.

반대편 거래소에서도 매도 시 `bids`를 위에서부터 먹으며 `sell VWAP`를 계산한다.
그 뒤 아래를 반영한다.

- 매수 총액
- 매도 총액
- 거래소 수수료
- 슬리피지 버퍼
- unwind buffer
- rebalance buffer

마지막으로 아래 값을 계산한다.

- `gross_profit_quote`
- `executable_profit_quote`
- `executable_profit_bps`

즉,

`executable profit = 실제 depth 체결 기준 예상 순이익`

이다.

관련 코드는 아래에 있다.

- [arbitrage_pricing.py](src/trading_platform/strategy/arbitrage_pricing.py)
- [arbitrage_runtime_loader.py](src/trading_platform/strategy/arbitrage_runtime_loader.py)
- [arbitrage_simulation.py](src/trading_platform/strategy/arbitrage_simulation.py)
- [market_data_connector.py](src/trading_platform/market_data_connector.py)

## 현재 핵심 알고리즘

현재 핵심 흐름은 아래 순서다.

1. 각 거래소 public REST orderbook에서 상위 depth를 읽는다.
2. 매수 거래소 `asks[]`, 매도 거래소 `bids[]`를 준비한다.
3. 주문 가능 수량 `q`를 계산한다.
   - buy side depth
   - sell side depth
   - available quote
   - available base
   - risk cap
   - max notional
4. `q`만큼 매수 side `asks[]`를 소비해서 `buy VWAP`를 계산한다.
5. `q`만큼 매도 side `bids[]`를 소비해서 `sell VWAP`를 계산한다.
6. `gross_profit_quote = sell proceeds - buy cost`를 계산한다.
7. 수수료, 슬리피지 버퍼, unwind/rebalance buffer를 차감한다.
8. 최종 `executable_profit_quote`, `executable_profit_bps`를 계산한다.
9. 최소 이익, 최소 bps, freshness, stale, 리스크 한도를 통과하면 기회로 본다.

## 중요한 판단 기준

이 프로젝트에서 의미 있는 질문은 아래다.

- `mid가 얼마나 벌어졌나?`
- `best ask/bid 차이가 있나?`

가 아니라,

- `내가 실제로 이 수량을 넣으면 depth를 다 먹고도 순이익이 남는가?`

이다.

따라서 low-liquidity 알트에서는 `mid`나 `top-of-book` 기준 해석이 쉽게 왜곡될 수 있고,
이 프로젝트는 그 왜곡을 줄이기 위해 executable VWAP 기준으로 계산한다.

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
