# Exchange Adapter Core Design

이 문서는 거래소 어댑터의 공통 책임과 진행 상태, 공식 문서 재검증 메모를 모은다. 구현 시작 전 공통 계층 기준으로 사용한다.


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
