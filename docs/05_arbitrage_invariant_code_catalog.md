# Arbitrage Invariant Code Catalog

이 문서는 재정거래 런타임 불변조건에 대응하는 `invariant_code` 이름을 고정한다.
목적은 observability, incident taxonomy, alert, 테스트가 서로 다른 이름을 쓰지 않게 만드는 것이다.


## 핵심 원칙

- 한 불변조건에는 대표 `invariant_code` 하나만 둔다.
- 이름은 조건 자체를 짧게 설명해야 한다.
- reject `reason_code`와 같은 이름을 재사용하지 않는다.


## 코드 규칙

형식:

- `ARB_INV_<UPPER_SNAKE_CASE>`

예:

- `ARB_INV_ACTIVE_ENTRY_UNIQUENESS`
- `ARB_INV_ACCEPT_WITHOUT_RESERVATION`


## 코드 목록

### P0

| 불변조건 | invariant_code |
|---|---|
| active entry uniqueness | `ARB_INV_ACTIVE_ENTRY_UNIQUENESS` |
| accept without reservation | `ARB_INV_ACCEPT_WITHOUT_RESERVATION` |
| intent/order market consistency | `ARB_INV_INTENT_ORDER_MARKET_MISMATCH` |
| fill quantity upper bound | `ARB_INV_FILL_QTY_EXCEEDED` |
| residual exposure visibility | `ARB_INV_RESIDUAL_EXPOSURE_UNKNOWN` |

### P1

| 불변조건 | invariant_code |
|---|---|
| lifecycle / order terminal consistency | `ARB_INV_CLOSED_WITH_ACTIVE_EXECUTION` |
| reject / side-effect consistency | `ARB_INV_REJECT_WITH_SIDE_EFFECT` |
| hedge balance claim consistency | `ARB_INV_HEDGE_BALANCE_CLAIM_FALSE` |
| reason code / lifecycle consistency | `ARB_INV_REASON_LIFECYCLE_CONFLICT` |

### P2

| 불변조건 | invariant_code |
|---|---|
| config immutability during active entry | `ARB_INV_CONFIG_CHANGED_DURING_ACTIVE_ENTRY` |
| metric/accounting consistency | `ARB_INV_METRIC_ACCOUNTING_CONFLICT` |


## 사용 규칙

- decision reject는 `reason_code`를 쓴다.
- 런타임 모순은 `invariant_code`를 쓴다.
- 운영 대응 묶음은 `incident_code`를 쓴다.

예:

- 판단 단계 duplicate intent 차단:
  - `reason_code=DUPLICATE_INTENT_BLOCKED`
- 이미 런타임 진입 후 active entry uniqueness 위반:
  - `invariant_code=ARB_INV_ACTIVE_ENTRY_UNIQUENESS`
- 그 결과 운영 incident 생성:
  - `incident_code=ARB-401 ACTIVE_ENTRY_CONFLICT`


## 구현 체크리스트

- 새 불변조건을 추가하면 이 문서에 먼저 코드명을 넣는다.
- observability와 incident taxonomy는 이 문서 이름을 그대로 쓴다.
- 비슷한 이름을 여러 개 만들지 않는다.
