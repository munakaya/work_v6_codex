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
- public REST observer 요약에는 `reason_code`별 누적 분해가 포함되어야 하며, stale/skew/private health가 서로 다른 code로 구분돼야 한다
- public REST observer는 기본적으로 `stale`을 hard gate로 사용하고, `skew`는 `clock_skew_diagnostic` 집계로만 남긴다. 필요할 때만 `--enforce-clock-skew-gate`로 hard gate를 켠다
- public REST observer가 비대칭 cadence를 사용할 때는 pair별 `max_clock_skew_ms`를 cadence에 맞춰 자동 보정하거나, 요약에 실제 적용된 timing gate를 드러내야 한다
- 거래소별 REST `timestamp` 의미가 완전히 같다고 가정하지 않는다. 같은 호가에도 timestamp가 계속 갱신되는 거래소가 있고, 오더북 변경 시에만 timestamp/id가 갱신되는 거래소도 있으므로 stale 해석은 거래소별 차이를 전제로 본다
- public REST observer 요약에는 거래소별 `attempt_count`, `success_rate`, `error_rate`, `latency_ms(p50/p95/p99)`가 포함되어야 한다
- public REST observer 요약에는 `market_opportunity_count`, `actionable_opportunity_count`, `positive_profit_opportunity_count`, `reservation_blocked_count`, `zero_profit_opportunity_count`를 포함해 "시장 기회", "실제 실행 가능 기회", "0원/예약 실패 진단"을 구분해야 한다
- public REST observer scheduler는 짧은 interval(`0.1s` 등)에서 tick 경계 오차 때문에 실제 cadence가 절반으로 떨어지지 않도록 tolerance를 둔다
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

### 40.5 public REST 안전 프리셋

실사용 기본 프리셋은 아래를 보수적 시작점으로 둔다.

- Upbit: `5 rps`, `burst 5`
- Bithumb: `100 rps`, `burst 100`
- Coinone: `10 rps`, `burst 10`

원칙:

- 기본값은 "실측 한계"가 아니라 "위반 가능성을 낮추는 보수적 값"으로 둔다.
- Coinone은 짧은 burst 측정치가 높더라도 sustained 기준이 불확실하므로 기본값은 `10 rps`를 유지한다.
- 운영 중 다른 봇/프로세스가 같은 공인 IP를 공유하면 실제 여유는 더 줄어든다고 가정한다.
