# Exchange Validation Matrix

이 문서는 거래소 통합 테스트 매트릭스를 모은다. 거래소 어댑터 변경 후 어떤 검증을 통과해야 하는지 판단하는 기준이다.


## 40. 거래소 통합 테스트 매트릭스 초안

한국 거래소는 범용 sandbox가 제한적이거나 기능이 축소될 수 있으므로, 테스트 전략을 계층별로 나눈다.

### 40.1 테스트 계층

- auth unit test: 거래소별 서명/query_hash/payload/header 생성 규칙 검증
- contract test: 공식 문서와 샘플 payload 기준의 request/response schema 검증
- replay test: 저장된 orderbook / trade / order event를 재생
- simulation test: fake connector로 strategy 판단 검증
- live smoke test: 최소 권한 실계정으로 잔고 조회, 주문 가능 정보 조회, 주문 생성/취소 소액 검증

현재 저장소에는 `tools_for_ai/fixtures/exchanges/*_contract_fixtures.json`에 내부 contract fixture 자산이 추가되어 있다.
이 fixture는 공식 live capture가 아니라 adapter 구현 전에 request/response category를 고정하는 최소 mock 자산이다.

### 40.2 거래소별 필수 검증 항목

공통:

- 거래소 auth helper 서명 규칙 검증
- public REST orderbook 정상 수신
- public REST observer는 거래소별 fetch cadence를 따로 줄 수 있어야 한다. 예: `upbit=3s`, `bithumb=1s`, `coinone=1s`
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
- 한 거래소 public REST가 `RATE_LIMITED`여도 나머지 거래소 쌍 관찰은 계속 가능해야 한다
- websocket 단절 시 REST fallback 또는 degraded 전환
- 동일 주문의 REST 조회 결과와 private WS 이벤트가 충돌하면 reconciliation job 수행

### 40.4 배포 전 승인 기준

거래소 adapter는 아래를 만족해야 production candidate가 된다.

- 최소 7일 shadow mode 무중단
- live smoke test 연속 성공
- auth refresh/reconnect 관련 치명 이슈 0건
- error mapping 누락 0건
- rate limit 위반 경고가 허용 기준 이하
