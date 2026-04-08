# Exchange Protocol Reference

이 문서는 거래소별 endpoint, 인증, 에러 매핑, symbol/fee/precision 규약을 모은다. 거래소별 차이를 구현할 때 참고하는 레퍼런스다.


## 34. 거래소별 Endpoint Inventory 초안

이 섹션은 코인원, 빗썸, 업비트의 구현 대상 endpoint 범주를 정리한 초안이다.
정확한 URI, 메서드, 요청/응답 필드명은 구현 직전 공식 문서로 재검증해야 하며, 여기서는 플랫폼 구현 범위를 고정하는 목적이 더 크다.

### 34.1 Upbit

공식 문서 기준으로 Upbit는 Quotation REST, Exchange REST, WebSocket 문서 구조가 비교적 명확하다.
구현 대상은 다음이다.

#### Public REST

- 주문 가능 마켓/페어 조회
- 호가(orderbook) 조회
- 현재가/체결가 보조 조회

#### Public WebSocket

- orderbook stream
- trade/ticker는 초기 MVP에서는 선택

#### Private REST

- balance 조회
- 주문 생성
- 주문 단건 조회
- 미체결 주문 조회
- 주문 취소

#### Private WebSocket

- 내 주문 / 체결 이벤트
- 내 자산 변동 이벤트

#### 참고 문서 범주

- Upbit 인증 가이드
- Quotation API Reference
- WebSocket orderbook reference
- 주문/잔고 Exchange API Reference

### 34.2 Bithumb

빗썸은 최근 문서 버전과 changelog 갱신이 활발하고, Public/Private, REST/WebSocket 버전 차이가 섞여 있으므로 구현 전 최종 버전을 잠가야 한다.

#### Public REST

- 호가(orderbook) 조회
- 시세 보조 조회

#### Public WebSocket

- orderbook stream
- 필요 시 ticker / trade stream

#### Private REST

- balance 조회
- 주문 생성
- 주문 단건 조회
- 미체결 주문 조회
- 주문 취소

#### Private WebSocket

- 내 주문/체결 이벤트
- 내 자산 변동 이벤트

#### 추가 주의

- 주문 관련 별도 rate limit이 존재하므로 주문 API는 일반 private API와 다른 limiter를 둬야 함
- 신규 주문 유형(TWAP 등) 확장 가능성이 있어 `order_type` 내부 enum은 유연하게 설계

### 34.3 Coinone

코인원은 v2.1 계열 private API와 public/private websocket 문서를 기준으로 구현하는 것이 적절하다.
구버전/폐기 예정 API가 섞여 있으므로 v2.1 기준을 고정해야 한다.

#### Public REST

- orderbook snapshot 조회
- 마켓 정보 조회

#### Public WebSocket

- orderbook stream

#### Private REST

- balance 조회
- 주문 생성
- 주문 정보 조회
- 미체결/체결 주문 조회
- 주문 취소

#### Private WebSocket

- MYORDER
- MYASSET

#### 추가 주의

- deprecated 문서와 권장 문서가 혼재하므로 endpoint inventory 확정 시 폐기 API를 명시적으로 배제
- private websocket 인증 실패와 connection limit을 운영 alert 기준에 포함

### 34.4 공통 구현 우선순위

세 거래소 모두 초기 MVP에서 반드시 구현해야 하는 공통 기능:

1. public orderbook REST
2. public orderbook WS
3. private balance
4. private place order
5. private order status

이 다섯 가지가 완성돼야 전략 엔진 MVP가 성립한다.

## 35. 거래소별 Auth Flow 초안

이 섹션은 플랫폼 내부 관점의 인증 흐름 초안이다.
정확한 header 이름, payload field, signature algorithm 파라미터는 구현 직전 공식 문서로 재검증한다.

### 35.1 공통 원칙

- 거래소 secret은 DB에 평문 저장 금지
- worker는 secret source 또는 secure local secret만 사용
- access key / secret key / nonce / timestamp 생성 책임은 adapter 내부에 둔다
- 전략 계층은 인증 세부를 몰라야 한다

### 35.1.1 로컬 trading key 파일 규약

- worker의 로컬 파일 조회 순서는 아래 2단계로 고정한다.
  1. `/dev/shm/keys/{exchange}_trading.json`
  2. `~/.key/{exchange}.json`
- `/dev/shm/keys`는 RAM 디스크 기준 경로로 본다.
- bot 부팅 시 `fetch-keys.sh`가 `/dev/shm/keys`를 채운다고 가정한다.
- 파일명 예시는 `upbit_trading.json`, `bithumb_trading.json`, `coinone_trading.json` 이다.
- 내부 표준 필드명은 모든 거래소에서 `access_key`, `secret_key`로 통일한다.
- 키 파일이 아직 없을 수 있으므로, 파일 없음은 정상적인 미배포 상태로 처리해야 한다.
- 기존 로컬 개발 파일 호환을 위해 loader는 빗썸 `api_key`, 코인원 `access_token` 같은 legacy access key 필드를 읽은 뒤 내부적으로 `access_key`로 정규화할 수 있다.

### 35.2 Upbit Auth Flow

문서상 Upbit는 API Key 기반 인증 가이드를 제공하며, Exchange REST와 private WebSocket 모두 인증이 필요하다.

현재 코드에는 `src/trading_platform/strategy/exchange_auth.py`에 Upbit JWT helper가 추가되어 있다.
이 helper는 repeated query order를 유지한 query string과 `query_hash` 생성 계약을 고정하는 용도다.

권장 구현 흐름:

1. worker가 secure store에서 access key / secret key 로드
2. request payload 기준 서명용 claim 구성
3. JWT 생성
4. REST는 Authorization header 부착
5. private websocket 연결 시 인증 payload 또는 token 부착

운영 주의:

- API key 권한 그룹 분리
- 허용 IP 설정 필요
- private websocket은 reconnect 시 인증 재수행

### 35.3 Bithumb Auth Flow

빗썸은 private API와 private websocket이 분리되어 있고, 버전 변화가 있으므로 auth flow 구현 전 최종 문서 버전을 잠가야 한다.

현재 코드에는 `src/trading_platform/strategy/exchange_auth.py`에 Bithumb JWT helper가 추가되어 있다.
다만 Bithumb는 문서 버전별 auth field 차이가 있으므로, 이 helper는 `access_key`, `nonce`, `timestamp`, `query_hash` 계약을 검증하는 최소 공통 골격으로만 본다.

권장 구현 흐름:

1. worker가 local/secure source에서 `access_key` / `secret_key` 로드
2. 요청별 nonce/timestamp 생성
3. 문서 기준 signature 생성
4. private REST header 부착
5. private websocket 연결 시 인증 메시지 전송

운영 주의:

- private websocket 안정화 이슈가 changelog에 존재하므로 reconnect/backoff 전략 필요
- 주문 API는 별도 limiter 적용

### 35.4 Coinone Auth Flow

코인원은 private REST와 private websocket 모두 인증이 필요하며, request signing / nonce 관리가 핵심이다.

현재 코드에는 `src/trading_platform/strategy/exchange_auth.py`에 Coinone payload/signature helper가 추가되어 있다.
이 helper는 `access_token`, `nonce`, payload base64, `X-COINONE-SIGNATURE` 계산을 공통화하는 용도다.

권장 구현 흐름:

1. worker가 local/secure source에서 `access_key` / `secret_key` 로드
2. nonce/timestamp 생성
3. 문서 기준 payload encode + sign
4. REST 요청 header/body 부착
5. private websocket 연결 시 인증 요청 송신

운영 주의:

- connection limit과 auth failure close code를 alert 조건에 반영
- nonce 재사용 방지

## 36. 거래소별 Error Mapping 초안

전략과 실행 계층은 거래소 고유 에러 문자열에 직접 의존하면 안 된다.
모든 거래소 에러는 아래 내부 코드 체계로 매핑한다.

### 36.1 내부 표준 코드

- `AUTH_FAILED`
- `RATE_LIMITED`
- `INSUFFICIENT_BALANCE`
- `ORDER_REJECTED`
- `ORDER_NOT_FOUND`
- `NETWORK_ERROR`
- `SERVER_ERROR`
- `INVALID_SYMBOL`
- `INVALID_REQUEST`
- `TEMPORARY_UNAVAILABLE`
- `WS_AUTH_FAILED`
- `WS_CONNECTION_LIMIT`
- `WS_STREAM_ERROR`

### 36.2 Upbit 매핑 초안

- 인증 실패/권한 부족 → `AUTH_FAILED`
- 요청 수 제한 → `RATE_LIMITED`
- 주문 가능 금액/수량 부족 → `INSUFFICIENT_BALANCE`
- 잘못된 마켓/파라미터 → `INVALID_SYMBOL` 또는 `INVALID_REQUEST`
- websocket private 인증 실패 → `WS_AUTH_FAILED`

### 36.3 Bithumb 매핑 초안

- private 인증 실패 → `AUTH_FAILED`
- private / order API 요청 수 제한 → `RATE_LIMITED`
- 주문 정책 불일치 / 허용되지 않은 주문 유형 → `ORDER_REJECTED`
- 잘못된 가격/수량 포맷 → `INVALID_REQUEST`
- private websocket 연결 이상 → `WS_STREAM_ERROR`

### 36.4 Coinone 매핑 초안

- auth 또는 signature 불일치 → `AUTH_FAILED`
- nonce/요청 형식 오류 → `INVALID_REQUEST`
- insufficient balance → `INSUFFICIENT_BALANCE`
- deprecated endpoint 사용 또는 지원 불가 → `INVALID_REQUEST` 또는 `TEMPORARY_UNAVAILABLE`
- private websocket auth close → `WS_AUTH_FAILED`
- connection limit 초과 close → `WS_CONNECTION_LIMIT`

### 36.5 에러 매핑 구현 규칙

- raw error payload는 주문/알림/로그 context에 보존
- 내부 계층에는 표준 코드만 전달
- `retryable` 여부를 에러 객체에 함께 포함

예시:

```json
{
  "exchange": "coinone",
  "internal_code": "RATE_LIMITED",
  "retryable": true,
  "raw_code": "TODO(verify)",
  "raw_message": "Too many requests"
}
```

## 43. 거래소별 Symbol / Fee / Precision 규약 초안

전략 계층은 거래소 고유 표기법과 가격/수량 규칙을 직접 다루지 않는다.
모든 거래소 adapter는 아래 내부 표준 모델로 정규화한다.

### 43.1 내부 표준 심볼 모델

권장 표준:

- `instrument_type`: `spot`
- `base_asset`: 예: `BTC`
- `quote_asset`: 예: `KRW`
- `canonical_symbol`: 예: `BTC/KRW`
- `exchange_symbol`: 거래소별 원본 표기

매핑 예시:

- Upbit: `KRW-BTC` -> `BTC/KRW`
- Bithumb: `KRW-BTC` -> `BTC/KRW`
- Coinone: `quote_currency=KRW`, `target_currency=BTC` -> `BTC/KRW`

정규화 원칙:

- 내부 저장과 전략 입력은 항상 `canonical_symbol` 사용
- 외부 요청 직전 adapter가 `exchange_symbol` 또는 path/body field로 변환
- symbol dictionary는 수동 하드코딩보다 거래소 metadata API 또는 관리 테이블로 유지

### 43.2 거래소별 심볼 표현 규약

#### Upbit

- 공식 문서 기준 market 코드는 `KRW-BTC` 형식
- quote asset이 앞, base asset이 뒤
- websocket도 동일 market code 사용

#### Bithumb

- 최신 private/public 문서 예시 기준 market ID는 `KRW-BTC` 형식
- V2.1.x 기준 market field를 사용하므로 Upbit와 비슷한 표기 계층을 둘 수 있음
- 다만 버전별 응답 필드 차이는 남아 있을 수 있으므로 metadata fetcher에서 version pinning 필요

#### Coinone

- market string 한 개가 아니라 `quote_currency`, `target_currency`의 쌍으로 표현되는 경우가 많음
- 내부적으로는 `BTC/KRW`로 정규화하고, adapter outbound 단계에서 두 필드로 분리
- private/public REST와 WS 모두 이 쌍 기반 모델을 기본으로 둔다

### 43.3 Precision 규약

정밀도는 세 층으로 나눈다.

- `price_tick_size`
- `qty_step_size`
- `min_notional`

추가 필드:

- `price_precision`
- `qty_precision`
- `min_qty`
- `max_qty`

규칙:

- 주문 생성 전 `price`는 `price_tick_size`에 맞춰 normalize
- `qty`는 `qty_step_size`에 맞춰 floor normalize
- normalize 이후 `price * qty >= min_notional` 검증
- normalize 결과가 원본 intent와 크게 다르면 주문 차단 후 decision record에 사유 기록

### 43.4 Upbit Precision 메모

- KRW 마켓 호가 단위와 최소 주문 가능 금액 정책은 공식 문서에서 별도 표로 관리됨
- 가격 구간에 따라 tick size가 달라지는 구간형 정책이므로 정적 소수점 자리수만으로 처리하면 안 된다
- KRW/BTC/USDT 마켓별 정책이 다를 수 있으므로 market class별 policy resolver 필요

설계 원칙:

- Upbit adapter는 `tick_policy_resolver(exchange, market_type, price)` 함수를 별도 모듈로 둔다
- 정책 변경일이 공지되는 경우 effective date를 포함한 버전화 필요

### 43.5 Bithumb Precision 메모

- 빗썸도 마켓별 최소 주문 수량/금액, 허용 가격 단위가 있을 수 있으므로 주문 전 metadata source로 검증 필요
- 공식 문서 또는 서비스 정보 API가 충분하지 않으면 운영 테이블로 보정할 수 있어야 한다

설계 원칙:

- Bithumb precision은 초기에는 운영 관리 테이블을 허용
- 다만 최종 source of truth는 공식 문서 또는 안정적인 metadata endpoint로 전환

### 43.6 Coinone Precision 메모

- Coinone public orderbook/주문 API는 문자열 기반 숫자 필드를 많이 사용
- 소수점 처리 시 float 사용 금지
- `Decimal` 기반 normalize가 필수

설계 원칙:

- Coinone adapter는 모든 수치 필드를 문자열로 파싱 후 `Decimal` 변환
- `quote_currency`, `target_currency`별 min/max 및 precision 정책은 symbol metadata에 귀속

### 43.7 수수료 모델 규약

전략 손익 계산에는 최소 세 종류 수수료가 필요하다.

- `maker_fee_rate`
- `taker_fee_rate`
- `withdraw_fee`

추가 고려:

- 프로모션/회원등급/이벤트 수수료
- 주문별 실제 체결 수수료
- quote asset 기준 수수료인지 base asset 기준 수수료인지 여부

정규화 원칙:

- 전략의 예상 손익은 `configured_fee_rate`
- 사후 손익과 reconciliation은 `executed_fee`
- 거래소 응답에 fee_rate와 fee amount가 모두 있으면 amount를 우선 신뢰

### 43.8 수수료 Source of Truth

권장 우선순위:

1. 주문/체결 응답의 실제 수수료 값
2. 계정/거래소 API가 제공하는 사용자 적용 수수료율
3. 운영자가 관리하는 config 기본값

금지 규칙:

- 문서에 적힌 일반 수수료율만으로 실제 PnL을 확정하지 않는다
- 거래소 프로모션 수수료를 코드 상수로 박아두지 않는다

### 43.9 Symbol Metadata 저장 제안

추가 테이블 제안:

- `instrument_metadata`
  - `id`
  - `exchange`
  - `exchange_symbol`
  - `canonical_symbol`
  - `base_asset`
  - `quote_asset`
  - `price_tick_policy_json`
  - `qty_step_size`
  - `min_qty`
  - `min_notional`
  - `maker_fee_rate`
  - `taker_fee_rate`
  - `active`
  - `last_verified_at`
