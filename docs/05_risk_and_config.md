# Risk Limits and Config Validation

이 문서는 전략 파라미터, 리스크 한도, 설정 검증 규칙을 모은다. shadow와 live 전환 전 최종 승인 기준으로 사용한다.


## 49. Strategy Parameter Catalog 초안

초기 제품은 현물 차익거래 전략을 기준으로 시작하되, 전략 파라미터를 명시적으로 분리해서 저장한다.
전략 구현 코드는 임의의 dict를 읽지 않고, 검증된 typed config만 받도록 설계한다.

### 49.1 전략 파라미터 분류

권장 분류:

- 시장 데이터 freshness
- 진입 조건
- 주문 생성 정책
- hedge 정책
- unwind 정책
- 리스크 한도
- 운영 모드

### 49.2 공통 파라미터

- `strategy_type`
- `enabled`
- `run_mode`
- `base_exchange`
- `hedge_exchange`
- `canonical_symbol`
- `poll_interval_ms`
- `decision_interval_ms`
- `dry_run`
- `shadow_mode`

설계 규칙:

- `run_mode`와 `dry_run`은 중복 표현이므로 최종 구현에서는 하나의 필드 체계로 정리
- `base_exchange`와 `hedge_exchange`는 동일 거래소 금지
- `canonical_symbol`은 `instrument_metadata`에 존재해야 함

### 49.3 시장 데이터 / freshness 파라미터

- `max_orderbook_age_ms`
- `max_balance_age_ms`
- `max_private_event_age_ms`
- `max_clock_skew_ms`
- `min_orderbook_depth_levels`

권장 초기값 예시:

- `max_orderbook_age_ms`: 1500
- `max_balance_age_ms`: 5000
- `max_private_event_age_ms`: 5000
- `max_clock_skew_ms`: 1000
- `min_orderbook_depth_levels`: 5

검증 규칙:

- 모든 age 값은 0보다 커야 함
- `max_balance_age_ms`는 `max_orderbook_age_ms`보다 작을 수 없음
- `min_orderbook_depth_levels`는 1 이상

### 49.4 진입 조건 파라미터

- `min_expected_profit_bps`
- `min_expected_profit_quote`
- `max_spread_bps`
- `min_available_depth_quote`
- `max_slippage_bps`
- `rebalance_buffer_quote`
- `max_entry_frequency_per_minute`

권장 해석:

- `min_expected_profit_bps`: 수수료와 예상 슬리피지 반영 후 최소 기대 수익률
- `min_expected_profit_quote`: 절대 금액 기준 최소 기대 수익
- `max_spread_bps`: 비정상 스프레드 환경 차단용 상한
- `rebalance_buffer_quote`: 체결 후 재균형 또는 재배치 비용을 보수적으로 미리 차감하는 절대 금액 버퍼

추가 원칙:

- `max_spread_bps` 초과는 profit 부족이 아니라 risk block으로 해석한다.
- 즉, 이 조건은 `RISK_LIMIT_BLOCKED` 쪽에서 fail-closed 한다.

검증 규칙:

- `min_expected_profit_bps`는 음수 금지
- `max_slippage_bps`는 전략 허용 범위 내의 작은 값으로 제한
- `rebalance_buffer_quote`는 음수 금지
- `max_entry_frequency_per_minute`는 1 이상

### 49.5 주문 생성 파라미터

- `order_type_preference`
- `maker_only`
- `order_timeout_ms`
- `reprice_attempt_limit`
- `reprice_interval_ms`
- `cancel_on_signal_loss`

권장 enum:

- `order_type_preference`: `limit`, `market`, `limit_then_market`

검증 규칙:

- `maker_only=true`이면 `order_type_preference=market` 금지
- `reprice_attempt_limit`는 0 이상
- `order_timeout_ms`는 `decision_interval_ms`보다 충분히 커야 함

### 49.6 hedge / unwind 파라미터

- `hedge_required`
- `hedge_timeout_ms`
- `max_leg_latency_ms`
- `unwind_policy`
- `unwind_timeout_ms`
- `max_unwind_slippage_bps`

권장 enum:

- `unwind_policy`: `immediate_market_exit`, `aggressive_limit_exit`, `timeboxed_requote_then_market`, `manual_only`

검증 규칙:

- `hedge_required=true`이면 `max_leg_latency_ms` 필수
- `unwind_timeout_ms`는 `hedge_timeout_ms` 이상 권장
- `manual_only`는 `run_mode=live`에서 고위험 bot의 기본값으로 금지 가능

### 49.7 운영 파라미터

- `alert_cooldown_sec`
- `pause_on_reconciliation_failure`
- `pause_on_auth_failure`
- `pause_on_balance_stale`
- `max_consecutive_failures`

검증 규칙:

- `max_consecutive_failures`는 1 이상
- `alert_cooldown_sec`는 0 이상
- 운영 중단성 옵션은 기본값을 보수적으로 잡는다

### 49.8 파라미터 버전 관리 원칙

- strategy config는 schema version을 가진다
- 의미가 바뀌는 필드 변경은 breaking change로 간주
- deprecated 파라미터는 즉시 제거하지 말고 migration path를 문서화
- config diff는 필드 단위로 저장하고 UI에서 시각화 가능해야 함

## 50. Risk Limit Spec 초안

리스크 한도는 전략 로직 내부 if문으로 흩어지면 안 된다.
별도 정책 객체로 평가하고, 위반 시 주문 생성 이전에 fail-closed 한다.

### 50.1 리스크 한도 분류

- bot 단위
- 거래소 단위
- 심볼 단위
- 전략 run 단위
- 시스템 전역

### 50.2 필수 한도

- `max_notional_per_order`
- `max_notional_per_symbol`
- `max_total_notional_per_bot`
- `max_net_exposure_quote`
- `max_open_orders`
- `max_daily_loss_quote`
- `max_daily_loss_bps`
- `max_reconciliation_backlog`
- `max_unwind_attempts`

### 50.3 bot 단위 한도

- 단일 bot이 동시에 가질 수 있는 총 노출 금액 제한
- bot별 최대 open order 수 제한
- bot별 연속 실패 횟수 상한

권장 예시:

- `max_total_notional_per_bot`
- `max_open_orders`
- `max_consecutive_failures`

### 50.4 거래소 단위 한도

- 특정 거래소 전체 노출 상한
- 특정 거래소 auth 장애 시 신규 주문 전면 차단
- 특정 거래소 rate limit 초과가 누적되면 cooldown

필드 예시:

- `max_notional_per_exchange`
- `cooldown_on_auth_failure_sec`
- `cooldown_on_rate_limit_sec`

### 50.5 심볼 단위 한도

- `BTC/KRW` 같은 특정 심볼 총 노출 제한
- 특정 심볼 변동성 급증 시 진입 차단

필드 예시:

- `max_notional_per_symbol`
- `max_daily_trades_per_symbol`
- `max_short_term_volatility_bps`

### 50.6 손실 한도

손실 한도는 실현 손실과 미실현 노출 둘 다 고려해야 한다.

- `max_daily_loss_quote`
- `max_daily_loss_bps`
- `max_unrealized_loss_quote`
- `max_unrealized_loss_bps`

트리거 규칙:

- 손실 한도 초과 시 해당 bot 신규 진입 차단
- 중대한 초과 시 전체 strategy run `paused`
- 연속 손실과 손실 금액을 함께 본다

### 50.7 운영 안정성 한도

- `max_orderbook_gap_events`
- `max_balance_stale_events`
- `max_private_ws_disconnects_per_hour`
- `max_reconciliation_backlog`

의미:

- 시장 데이터나 운영 상태가 불안정하면 수익 기회가 있어도 거래하지 않는다
- 안정성 한도는 financial limit와 동일한 우선순위로 평가

### 50.8 리스크 평가 순서

1. 시스템 전역 중단 조건
2. 거래소 건강 상태
3. 데이터 freshness
4. 심볼 거래 가능 상태
5. bot 단위 한도
6. 전략별 기대 수익 조건
7. 주문 생성 가능 여부

원칙:

- 앞 단계 실패 시 뒤 단계 평가 생략 가능
- 위반 사유는 모두 decision record에 남긴다

### 50.9 리스크 위반 표준 코드

- `RISK_MAX_NOTIONAL_EXCEEDED`
- `RISK_MAX_NET_EXPOSURE_EXCEEDED`
- `RISK_MAX_OPEN_ORDERS_EXCEEDED`
- `RISK_DAILY_LOSS_EXCEEDED`
- `RISK_DATA_FRESHNESS_FAILED`
- `RISK_CONNECTOR_UNHEALTHY`
- `RISK_RECONCILIATION_BACKLOG_HIGH`
- `RISK_UNWIND_IN_PROGRESS`

## 51. Config Schema / Validation Spec 초안

Control Plane은 사람이 읽기 쉬운 config를 받되, runtime에는 강한 validation을 통과한 결과만 배포한다.

### 51.1 권장 schema 계층

- `global_config`
- `exchange_profiles`
- `risk_profiles`
- `strategy_templates`
- `bot_instances`

의미:

- 전역 정책과 bot 개별 설정을 분리
- 공통 위험 한도는 profile로 재사용
- bot은 template + override 조합으로 생성

### 51.2 예시 구조

```yaml
schema_version: 1
global_config:
  environment: production
  timezone: UTC
exchange_profiles:
  upbit_main:
    exchange: upbit
    account_ref: secret://exchange/upbit/main
risk_profiles:
  conservative_krw:
    max_notional_per_order: "300000"
    max_daily_loss_quote: "50000"
strategy_templates:
  spot_arb_krw_btc:
    strategy_type: spot_arbitrage
    canonical_symbol: BTC/KRW
    min_expected_profit_bps: 12
bot_instances:
  arb_upbit_bithumb_btc_01:
    template: spot_arb_krw_btc
    base_exchange_profile: upbit_main
    hedge_exchange_profile: bithumb_main
    risk_profile: conservative_krw
```

### 51.3 validation 단계

1. schema validation
2. enum / type validation
3. cross-field validation
4. external reference validation
5. dry-run compile

### 51.4 필수 검증 규칙

- `schema_version` 존재
- bot 이름과 식별자는 고유
- exchange profile reference가 실제 존재
- 동일 bot에서 base/hedge 거래소 중복 금지
- symbol이 `instrument_metadata`에 존재
- risk limit가 음수 금지
- live 모드 bot은 필수 운영 옵션 누락 금지

### 51.5 cross-field validation 예시

- `maker_only=true`이면 market-only 정책 금지
- `dry_run=true`이면 live 전용 승인 필드 불필요
- `unwind_policy=manual_only`이면 특정 리스크 프로필에서는 금지 가능
- `max_total_notional_per_bot >= max_notional_per_order`
- `max_daily_loss_quote`가 0이면 live 실행 금지 가능

### 51.6 compile 단계의 의미

config compile 결과는 runtime에서 즉시 사용할 내부 스냅샷이다.

권장 산출물:

- resolved exchange references
- resolved risk profile
- resolved symbol metadata
- normalized decimals
- derived limits
- validation warnings

### 51.7 배포 승인 규칙

- validation error가 하나라도 있으면 배포 금지
- warning만 있는 config는 staging/dry-run만 허용 가능
- production assignment는 승인 이벤트와 audit log를 남긴다

### 51.8 Config Validation 실패 표준 코드

- `CONFIG_SCHEMA_INVALID`
- `CONFIG_REFERENCE_NOT_FOUND`
- `CONFIG_DUPLICATE_BOT_ID`
- `CONFIG_INVALID_EXCHANGE_PAIR`
- `CONFIG_INVALID_RISK_LIMIT`
- `CONFIG_SYMBOL_NOT_SUPPORTED`
- `CONFIG_LIVE_GUARD_FAILED`
