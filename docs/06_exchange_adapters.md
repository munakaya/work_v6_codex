# Exchange Adapter Design

이 문서는 거래소 공통 어댑터 계약과 거래소별 엔드포인트, 인증, 에러 매핑, 테스트 매트릭스를 모은다. 새 거래소 추가 또는 기존 거래소 수정 전에 반드시 확인한다.


## 29. 거래소 설계 진행 상태

질문하신 거래소 관련 항목은 "방향과 범위"는 설계되어 있고, "거래소별 세부 계약"은 아직 초안 수준이다.

### 29.1 현재 설계된 수준

이미 문서에 반영된 것:

- 거래소 어댑터 공통 인터페이스 필요
- REST/WS/public/private 분리 필요
- rate limit과 재시도 정책은 전략이 아니라 어댑터 책임
- 최초 MVP는 2~3개 거래소만 지원

즉, 아키텍처 레벨 설계는 끝난 상태다.

### 29.2 아직 더 구체화가 필요한 것

거래소별로 추가 설계가 필요한 항목:

- Upbit
  - orderbook REST endpoint 계약
  - orderbook WS subscribe payload
  - private auth signature 방식
  - balance 응답 정규화 규칙
  - order status mapping

- Bithumb
  - public orderbook 정규화 규칙
  - private balance/order 응답 매핑
  - 에러 코드 표준화
  - 체결 정보 정규화

- Coinone
  - REST/WS 최신 API 기준 응답 스키마 정리
  - private auth 및 nonce 처리 규칙
  - partial fill / remain qty 정규화
  - rate limit 정책

### 29.3 거래소 설계 상태 판단

- 공통 어댑터 구조: 설계됨
- 거래소별 세부 계약: 미완료
- 에러 코드 표준화: 미완료
- test fixture / mock payload: 미완료

즉, "구조 설계는 완료, 거래소별 상세 명세는 다음 문서 단계"라고 보면 된다.

## 32. 거래소 어댑터 상세 설계

이 섹션은 코인원, 빗썸, 업비트 어댑터를 구현하기 전에 공통 계약과 거래소별 정규화 관점을 정리한 상세 설계다.
구체 API endpoint 문자열이나 인증 파라미터 이름은 구현 직전 공식 문서 기준으로 검증해야 하며, 여기서는 "플랫폼 내부 계약"을 정의한다.

### 32.1 어댑터 공통 책임

모든 거래소 어댑터는 아래 기능을 공통 제공해야 한다.

- public orderbook snapshot 조회
- public orderbook stream 구독
- private balance 조회
- private order 제출
- private order 상태 조회
- private open order 목록 조회
- 거래소 고유 에러를 내부 에러 코드로 정규화
- 거래소 rate limit과 backoff 정책 처리

전략 계층은 어댑터의 내부 인증 방식이나 응답 원문 구조를 몰라야 한다.

### 32.2 공통 인터페이스 초안

```python
class ExchangeAdapter(Protocol):
    name: str

    async def get_orderbook_top(self, market: str) -> OrderBookTop: ...
    async def subscribe_orderbook(self, market: str) -> AsyncIterator[OrderBookTop]: ...

    async def get_balances(self) -> list[BalanceItem]: ...

    async def place_order(self, req: PlaceOrderRequest) -> ExchangeOrderRef: ...
    async def get_order_status(self, exchange_order_id: str, market: str) -> OrderStatusSnapshot: ...
    async def list_open_orders(self, market: str | None = None) -> list[OrderStatusSnapshot]: ...
```

### 32.3 공통 도메인 모델

#### `OrderBookTop`

```json
{
  "exchange": "upbit",
  "market": "XRP-KRW",
  "best_bid": "1023.2",
  "best_ask": "1023.3",
  "bid_volume": "1500.12",
  "ask_volume": "948.33",
  "exchange_timestamp": "2026-04-03T14:12:00Z",
  "received_at": "2026-04-03T14:12:00.120Z",
  "source_type": "ws"
}
```

#### `BalanceItem`

```json
{
  "exchange": "bithumb",
  "asset": "KRW",
  "total": "1200000",
  "available": "1180000",
  "locked": "20000",
  "snapshot_at": "2026-04-03T14:12:04Z"
}
```

#### `PlaceOrderRequest`

```json
{
  "market": "XRP-KRW",
  "side": "buy",
  "order_type": "limit",
  "price": "1020.5",
  "quantity": "120.5",
  "client_order_id": "uuid"
}
```

#### `OrderStatusSnapshot`

```json
{
  "exchange": "coinone",
  "exchange_order_id": "abc123",
  "market": "XRP-KRW",
  "side": "buy",
  "status": "partially_filled",
  "price": "1020.5",
  "quantity": "120.5",
  "filled_quantity": "40.0",
  "remaining_quantity": "80.5",
  "avg_fill_price": "1020.7",
  "updated_at": "2026-04-03T14:12:10Z"
}
```

### 32.4 내부 에러 코드 규약

거래소별 에러는 아래 내부 코드로 정규화한다.

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

각 어댑터는 원본 에러 코드와 메시지를 보존하되, 전략/실행 계층에는 내부 코드만 전달한다.

### 32.5 Rate Limit 정책

어댑터는 최소한 아래 3계층 제한을 관리해야 한다.

- public REST limit
- private REST limit
- websocket reconnect / subscribe burst limit

전략은 요청 속도를 직접 제어하지 않고, 어댑터는 초과 시:

1. local throttle
2. retry with backoff
3. still failing 시 `RATE_LIMITED` 또는 `TEMPORARY_UNAVAILABLE`

로 정규화한다.

### 32.6 Upbit 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 제공
- private balance / order / order status 제공
- websocket 기반 빠른 orderbook 업데이트 주 공급원 역할

#### 구현 시 확인할 항목

- market symbol 매핑
- WS reconnect 정책
- auth header / JWT 방식
- partial fill 상태 표현
- balance asset naming

#### 정규화 시 주의점

- market 형식을 내부 표준으로 통일
- 잔고 응답의 total/available/locked 계산 규칙 명확화
- order status의 terminal state 판정 기준 고정

### 32.7 Bithumb 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 공급
- private balance / order / order status 제공

#### 구현 시 확인할 항목

- public / private 응답 구조 차이
- 체결 정보의 부분 체결 누적 방식
- remaining quantity 계산 기준
- 에러 코드 집합

#### 정규화 시 주의점

- 체결 contract 배열이 있을 경우 내부 fill 모델로 풀어야 함
- order status를 `new / partially_filled / filled / cancelled / rejected`로 안정적으로 매핑

### 32.8 Coinone 상세 설계 관점

#### 역할

- KRW 마켓 기준 top-of-book 공급
- private balance / order / order status 제공

#### 구현 시 확인할 항목

- nonce 또는 request signing 규칙
- remain quantity / filled quantity 필드 의미
- orderbook timestamp 신뢰성
- rate limit 및 maintenance 응답

#### 정규화 시 주의점

- remain 기준으로 filled 계산이 필요한 경우가 있음
- maintenance나 temporary unavailable 상태를 전략 차단 신호로 연결해야 함

### 32.9 거래소별 테스트 요구사항

거래소마다 최소 아래 테스트 픽스처가 필요하다.

- 정상 orderbook REST 응답 샘플
- 정상 orderbook WS 샘플
- 정상 balance 응답 샘플
- 정상 order submit 응답 샘플
- partial fill 응답 샘플
- terminal fill 응답 샘플
- auth 실패 응답 샘플
- rate limit 응답 샘플

### 32.10 거래소 상세 설계 산출물

각 거래소별로 아래 문서 또는 구현 산출물이 있어야 한다.

- endpoint inventory
- auth flow
- request signing spec
- normalized payload mapping table
- error mapping table
- retry / backoff policy
- mock fixture set

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

### 35.2 Upbit Auth Flow

문서상 Upbit는 API Key 기반 인증 가이드를 제공하며, Exchange REST와 private WebSocket 모두 인증이 필요하다.

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

권장 구현 흐름:

1. api key / secret 로드
2. 요청별 nonce/timestamp 생성
3. 문서 기준 signature 생성
4. private REST header 부착
5. private websocket 연결 시 인증 메시지 전송

운영 주의:

- private websocket 안정화 이슈가 changelog에 존재하므로 reconnect/backoff 전략 필요
- 주문 API는 별도 limiter 적용

### 35.4 Coinone Auth Flow

코인원은 private REST와 private websocket 모두 인증이 필요하며, request signing / nonce 관리가 핵심이다.

권장 구현 흐름:

1. access token 또는 api key / secret 로드
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

## 37. 2026-04-04 기준 공식 문서 재검증 메모

이 섹션은 2026년 4월 4일 기준 공식 문서에서 다시 확인한 내용만 요약한 것이다.
정확한 endpoint path, header name, field schema는 구현 직전 한 번 더 공식 문서 기준으로 잠그는 것을 원칙으로 한다.

### 37.1 Upbit 재검증 포인트

- private websocket endpoint는 `wss://api.upbit.com/websocket/v1/private`
- 내 주문 및 체결, 내 자산 구독은 private endpoint와 인증 헤더가 필요
- websocket 요청 제한 정책은 문서상 별도 그룹으로 관리되며, 인증 포함 여부에 따라 계정 단위 또는 IP 단위로 측정
- 공식 문서에는 websocket 메시지 제한이 초당 5회, 분당 100회로 안내되어 있음
- 허용 IP 설정은 운영 전 필수 점검 항목

문서 반영 원칙:

- Upbit adapter는 REST auth와 private WS auth를 동일한 token provider 계층에서 공급
- private WS 연결 재수립 시 토큰 재생성 필수
- rate limiter는 REST/WS를 분리하되, Exchange 계열은 계정 단위 quota를 전제로 설계

### 37.2 Bithumb 재검증 포인트

- 인증 헤더 문서는 버전별 차이가 있음
- `v1.2.0` 문서에서는 `Api-Nonce`를 millisecond timestamp로 설명
- `v2.1.5` 문서에서는 `nonce`를 UUID 문자열로 설명
- 따라서 빗썸 adapter는 "문서 버전 pinning" 없이 구현하면 인증 오류 위험이 큼
- private websocket은 changelog 기준으로 정책 변경과 안정화 공지가 반복되고 있으므로 reconnect/backoff를 필수 capability로 본다

문서 반영 원칙:

- Bithumb adapter는 auth profile을 코드 상수로 고정하고, 어떤 문서 버전에 맞춰 구현했는지 release note에 명시
- websocket 연결 정책은 별도 limiter와 reconnect circuit breaker를 둔다
- error mapping 시 HTTP 상태만 보지 말고 body error code까지 함께 저장한다

### 37.3 Coinone 재검증 포인트

- private websocket endpoint는 `wss://stream.coinone.co.kr/v1/private`
- private websocket은 인증 필요
- 계정당 최대 20개 연결 허용
- 연결 초과 시 `4290` close code, 인증 실패 시 `4280` close code
- 마지막 PING 이후 30분이 지나면 idle 연결로 간주되어 종료
- public/private request signing은 access token, secret key, payload/signature 흐름을 명확히 따름

문서 반영 원칙:

- Coinone adapter는 ping scheduler를 내장
- close code 기반 장애 분류를 반드시 구현
- connection pool 설계 시 계정당 private WS 연결 수를 하드 제한

### 37.4 구현 시 소스 잠금 규칙

- 거래소별 adapter 구현 시작 전 공식 문서 URL과 확인 일자를 ADR 또는 release note에 기록
- changelog subscription 또는 주간 확인 루틴을 운영 절차에 포함
- 문서가 상충할 경우 "현재 배포 버전에서 실제 통과한 contract"를 별도 compatibility note로 남긴다

## 40. 거래소 통합 테스트 매트릭스 초안

한국 거래소는 범용 sandbox가 제한적이거나 기능이 축소될 수 있으므로, 테스트 전략을 계층별로 나눈다.

### 40.1 테스트 계층

- contract test: 공식 문서와 샘플 payload 기준의 request/response schema 검증
- replay test: 저장된 orderbook / trade / order event를 재생
- simulation test: fake connector로 strategy 판단 검증
- live smoke test: 최소 권한 실계정으로 잔고 조회, 주문 가능 정보 조회, 주문 생성/취소 소액 검증

### 40.2 거래소별 필수 검증 항목

공통:

- public REST orderbook 정상 수신
- public WS orderbook reconnect
- private balance 조회
- 주문 생성
- 주문 조회
- 주문 취소
- private WS my order / my asset 수신
- rate limit 초과 시 backoff 동작
- auth 실패 시 non-retry 분류

### 40.3 시나리오 테스트 세트

- stale orderbook 입력 시 거래 차단
- balance snapshot이 오래되면 order intent 생성 차단
- 한 거래소만 부분 체결되면 `unwind_required`
- websocket 단절 시 REST fallback 또는 degraded 전환
- 동일 주문의 REST 조회 결과와 private WS 이벤트가 충돌하면 reconciliation job 수행

### 40.4 배포 전 승인 기준

거래소 adapter는 아래를 만족해야 production candidate가 된다.

- 최소 7일 shadow mode 무중단
- live smoke test 연속 성공
- auth refresh/reconnect 관련 치명 이슈 0건
- error mapping 누락 0건
- rate limit 위반 경고가 허용 기준 이하

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
