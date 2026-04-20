# TODO

이 문서는 남은 구현/운영 보강 항목을 실제 진행 순서대로 적어두는 작업판이다.
이미 끝난 일과 앞으로 바로 구현해야 할 일을 섞지 않고, 지금부터 손대야 할 순서가 드러나도록 다시 정리한다.

## 이미 완료된 항목

- [x] 실거래 private REST connector 최소 계약 구현
  Upbit/Bithumb/Coinone의 private balance, place order, order status, open orders를 실제 API로 연결했다.

- [x] `private_http` 의존을 임시 경로로 명확히 격하
  `ready`와 `strategy_runtime`에 `temporary_external_delegate` 메타데이터를 추가했다.

- [x] Redis runtime의 `redis-cli` subprocess 의존 제거
  내부 RESP 기반 connection-pool 클라이언트로 교체했다.

- [x] 운영 환경 write API fail-closed 강제
  `APP_ENV=staging|production`에서는 `TP_ADMIN_TOKEN`이 없으면 서버가 기동 실패하도록 바꿨다.

- [x] 설계 진척도 문서 현실화
  `docs/08_progress_and_gaps.md`에서 설계 완성도와 구현/실거래 준비도를 분리했다.

## 지금부터 진행할 순서

### 1. Coinone public WS timestamp/freshness 문제 수정

- [x] Coinone public WS payload의 `t` / `timestamp` 의미를 재검증했다.
  실제 호가 생성 시각인지, 서버 publish 시각인지, 문서와 실측이 일치하는지 확인해야 한다.

- [x] `sim observer`와 runtime 입력 payload에서 `observed_at` 우선순위를 재설계했다.
  현재는 `exchange_timestamp`를 `received_at`보다 우선 사용해 stale이 과도하게 발생한다.

- [x] Coinone WS 전용 `received_at` fallback 규칙을 넣었다.
  목표는 `ORDERBOOK_STALE` 오탐을 줄이되, 실제 오래된 snapshot을 허용하지 않는 것이다.

- [x] Coinone WS freshness 회귀 케이스를 추가했다.
  `tools_for_ai` 케이스와 이후 정식 테스트에서 5초 gate 경계값을 재현 가능해야 한다.

### 2. public WS-first collector를 런타임 기본 경로로 전환

- [x] 현재 `sim observer`에만 붙은 public WS 수집을 runtime collector로 끌어올렸다.
  목표 경로는 `public WS -> 최신 snapshot cache -> strategy runtime`이다.

- [x] REST poller를 기본 경로에서 fallback/보정 경로로 내렸다.
  bootstrap, reconnect 직후 보정, 진단성 재조회 정도로 역할을 축소한다.

- [x] cache write 계약을 명확히 정리했다.
  `exchange_timestamp`, `received_at`, `exchange_age_ms`, `source_type`가 WS/REST 양쪽에서 일관되게 들어가야 한다.

- [x] WS collector 장애 시 degrade/fallback 상태를 readiness와 로그에 명확히 노출한다.

### 3. Bithumb public WS adapter 추가 또는 미지원 결정 확정

- [x] Bithumb public WS orderbook 계약을 다시 확인한다.
  endpoint, subscribe payload, timestamp 필드, reconnect 규칙을 코드 반영 전에 고정해야 한다.

- [x] Bithumb public WS adapter를 추가한다.
  `sim observer`와 이후 runtime collector 양쪽에서 동일 contract를 쓰도록 맞춘다.

- [ ] 지원을 보류할 경우, 미지원 사유를 코드와 문서에 명시한다.
  현재처럼 애매한 상태로 두지 않고 `unsupported` 또는 `experimental` 중 하나로 고정한다.

### 4. market data collector coverage 확장

- [x] 실행 중 arbitrage run에서 파생되는 `(exchange, market)` target을 collector 기본 수집군에 더 빠르게 반영한다.

- [x] 다거래소/다심볼 조건에서 `MARKET_SNAPSHOT_NOT_FOUND`를 줄이기 위한 선제 수집 정책을 넣는다.

- [x] coverage 부족을 readiness 또는 runtime 진단값으로 노출한다.
  단순 miss가 아니라 “collector가 아직 안 보고 있음”을 구분해 보여줘야 한다.

### 5. 3거래소 동시 비교 candidate selection 반영

- [x] 현재 `base_exchange + hedge_exchange` 2거래소 고정 평가를 일반화한다.

- [x] `upbit/bithumb/coinone` 전체를 동시에 보고, 그 시점 최적의 `selected_pair` 1개를 고르는 selection layer를 추가한다.

- [x] selection 결과와 탈락 후보를 함께 기록한다.
  나중에 `selected_pair` 편향, missed opportunity, live/shadow 차이를 분석할 수 있어야 한다.

### 6. pair-level trade lock 추가

- [ ] `(market, selected_pair)` 기준의 명시적 락을 도입한다.
  active intent, open order count만으로는 중복 진입 방지가 약하다.

- [ ] recovery trace, open order, duplicate intent와 pair lock의 우선순위를 정리한다.
  락 때문에 recovery가 막히거나 recovery 때문에 락이 무의미해지지 않게 해야 한다.

- [ ] 락 획득 실패/해제 실패를 운영 로그와 메트릭으로 남긴다.

### 7. 실제 거래소 잔고 기반 balance snapshot 연동

- [ ] 전략 입력의 `base_balance`, `hedge_balance`를 거래소 `get_balances()` 기반 snapshot으로 바꾼다.

- [ ] 잔고 freshness 기준을 risk gate에 명시적으로 반영한다.
  stale balance를 들고 주문 판단을 하지 않도록 해야 한다.

- [ ] 수동 runtime/config 잔고 주입은 `simulation/shadow 전용`으로만 남기고 live 경로에서는 막는다.

### 8. private execution 최종 경로 정리

- [ ] `private_http`를 계속 임시 외부 위임 경로로 둘지, 내장 execution path로 대체할지 결정한다.

- [ ] 실계정 smoke, cancel flow, reconciliation까지 포함한 end-to-end 경로를 닫는다.

- [ ] malformed `private_http` 응답 회귀를 서버 레벨까지 확대한다.
  direct adapter만이 아니라 `evaluate-arbitrage` 실제 서버 경로에서 fail-closed를 확인해야 한다.

### 9. 검증 체계 승격

- [ ] `tools_for_ai` 핵심 케이스를 정식 `pytest/tests/CI` 체계로 승격한다.
  최소 대상은 market data, private connector, strategy runtime, recovery, write guard다.

- [ ] public WS/REST 비교 회귀 케이스를 자동화한다.
  Coinone stale 재발, Bithumb parser 오류, fallback 전환 같은 케이스를 고정해야 한다.

- [ ] 실호가 기반 VWAP/fee 대조 도구를 유지 보강한다.
  거래소별 실제 orderbook과 pricing 결과가 계속 맞는지 확인할 수 있어야 한다.

- [ ] `pytest` 기본 골격을 먼저 추가한다.
  `pyproject.toml` 또는 동등한 테스트 설정 파일, `tests/` 디렉토리, 공통 fixture/bootstrap, 기본 실행 명령을 먼저 고정해야 한다.

- [ ] `tools_for_ai` 케이스를 "그대로 호출하는 래퍼"가 아니라 pytest 테스트로 재구성한다.
  현재처럼 스크립트 단위 `SystemExit` 검증에 머무르지 말고, assertion/fixture/parametrize 구조로 옮겨 discoverability와 부분 실행성을 확보해야 한다.

- [ ] 최소 CI 경로를 추가한다.
  `market data`, `strategy runtime`, `private connector` 핵심 스모크가 push/PR마다 자동 실행되게 하고, 장시간/실거래 의존 케이스는 별도 job 또는 수동 workflow로 분리한다.

- [ ] 테스트 실행 시 로그 노이즈를 줄이는 기본 정책을 정한다.
  의도된 failure-path 검증 로그와 실제 회귀 로그를 구분할 수 있어야 하며, 기본 test run에서는 warning/error 로그가 과도하게 쏟아지지 않게 해야 한다.

### 9A. 배포/패키징 최소 기준 추가

- [ ] Python 의존성과 실행 진입점을 저장소 안에 명시한다.
  현재는 `setup.sh`와 `.venv` 전제만 있고 패키지 매니페스트가 없다. `pyproject.toml` 또는 동등한 의존성 선언 파일을 추가해 새 머신 재현성을 확보해야 한다.

- [ ] `setup.sh`/`run.sh`와 문서에 "처음부터 실행 가능한 경로"를 맞춘다.
  venv 생성만 하고 수동 설치를 요구하는 현재 흐름은 새 세션/새 머신에서 재현성이 약하다. 설치, 테스트, 서버 기동의 표준 명령을 문서와 스크립트에서 하나로 고정해야 한다.

- [ ] 최소 컨테이너/배포 아티팩트 필요성을 검토하고 결정한다.
  바로 Docker까지 갈지, 우선 로컬/단일 서버 배포만 지원할지 기준을 정하고, 선택한 경로에 맞는 아티팩트를 저장소에 남겨야 한다.

### 9B. freshness/source 기준 일반화

- [ ] `exchange_timestamp` 우선 정책을 거래소별 patch가 아니라 일반 규칙으로 재설계한다.
  현재는 Coinone WS만 `received_at` 예외를 두고 있다. `freshness_observed_at` 선택 기준을 "거래소 시계를 얼마나 신뢰할지" 관점에서 거래소/소스별 정책 테이블로 승격해야 한다.

- [ ] freshness 정책에 skew guard를 추가한다.
  `exchange_timestamp`가 `received_at`보다 과도하게 뒤처지거나 미래로 치우치면 자동으로 `received_at`로 강등하고, 그 사실을 메타데이터와 진단값에 남겨야 한다.

- [ ] freshness 회귀 케이스를 거래소 공통 포맷으로 늘린다.
  Coinone만이 아니라 Upbit/Bithumb/REST/WS 각각에 대해 `timestamp missing`, `timestamp lag`, `future timestamp`, `received_at only` 케이스를 고정해야 한다.

### 9C. 대형 모듈 분해

- [ ] `recovery_runtime.py`를 책임 단위로 분해한다.
  trace 조회, handoff 판정, replay/reconciliation, runtime thread 제어를 한 파일에 두지 말고 모듈로 분리해야 한다.

- [ ] `private_exchange_connector.py`를 거래소/동작 단위로 쪼갠다.
  최소한 `upbit/bithumb/coinone` 별 API contract와 공통 HTTP/error normalization 계층을 분리해, 한 거래소 수정이 전체 파일 review로 번지지 않게 해야 한다.

- [ ] `arbitrage_private_execution_adapter.py`를 상태 해석기와 transport 계층으로 분리한다.
  외부 응답 파싱, fill/order normalization, fail-closed 분류, HTTP 호출을 분리하지 않으면 execution path 내재화 작업이 계속 어려워진다.

### 9D. store bootstrap / fallback 정책 재점검

- [ ] Postgres 미연결 시 `memory_empty`로 조용히 떨어지는 현재 동작을 재검토한다.
  개발 편의성은 있지만, 운영 환경에서 "서버는 떴는데 데이터는 비어 있는" 상태를 만들기 쉽다. 최소한 staging/production에서는 fail-closed 또는 강한 경고로 바꿔야 한다.

- [ ] store bootstrap 결과를 readiness와 운영 로그에서 더 강하게 드러낸다.
  지금도 bootstrap info는 있지만, `memory_empty`가 실제 운영에서 허용되는 상태인지 즉시 판단할 수 있도록 health/ready/boot log 계약을 더 명확히 해야 한다.

### 9E. control plane 기반 재점검

- [ ] `ThreadingHTTPServer` 기반 control plane 유지 여부를 재평가한다.
  현재 구조가 충분한지, 아니면 request lifecycle, shutdown, concurrency 제어가 더 나은 표준 프레임워크로 옮겨야 하는지 기준과 비용을 문서화해야 한다.

- [ ] 현재 HTTP 서버 구조에서 공유 상태 경쟁 범위를 명시한다.
  market data, strategy, recovery runtime과 route handler가 어떤 락/불변 조건에 기대고 있는지 정리하지 않으면 이후 기능 추가 때 race를 다시 만들기 쉽다.

### 9F. pricing/reservation 일관성 검증

- [ ] `arbitrage_pricing.py`와 `arbitrage_reservation.py` 사이 버퍼 차감 일관성을 검증한다.
  unwind/rebalance/slippage buffer가 sizing 단계와 reservation 단계에서 이중 차감되는지 확인하고, 실제 reject 케이스를 회귀 테스트로 고정해야 한다.

- [ ] Decimal hot path 성능을 실측한다.
  현재 철학은 정확도 우선이지만, top-N depth pricing과 다거래소 selection 경로에서 허용 가능한 latency인지 벤치마크와 운영 로그 기준으로 확인해야 한다.

### 10. 운영 지표와 backlog 요약 추가

- [ ] live/shadow/sim 편차 지표를 추가한다.
  `selected_pair vs 미선택 후보`, `shadow profit vs live fill`, `REST fallback 사용 빈도`를 같이 기록한다.

- [ ] reconciliation backlog 압축 뷰를 추가한다.
  오래 unresolved인 trace, 반복 mismatch, submit timeout 재시도 누적을 한 번에 봐야 한다.

- [ ] inventory skew / rebalance 제안 레이어를 추가한다.
  거래소 간 KRW/코인 쏠림을 운영자가 바로 볼 수 있어야 한다.

- [ ] in-flight order/fill 단기 캐시 필요성을 검토한다.
  늦게 도착한 fill, duplicate fill, partial fill 재수신을 다룰 최소 메모리 계층이 필요한지 판단한다.

## 문서 후속 정리

- [ ] `docs/04_operations.md`의 운영 기본값을 구현 현실에 맞게 조정한다.
  운영 환경에서 write API 보호가 필수라는 점과 `private_http`의 임시 성격을 더 명확히 적어야 한다.

- [ ] `docs/11_implementation_tasks.md` 우선순위를 현재 구현 순서와 맞춘다.
  문서도 `Coinone WS freshness -> WS-first collector -> Bithumb WS -> pair lock -> 실잔고 -> execution path -> 정식 테스트` 순서가 드러나야 한다.

## 메모

- direct REST 재조회 제거와 cached snapshot 우선 로딩은 이미 반영됐다.
- write API bearer token / rate limit guard도 이미 구현 및 실행 검증되어 있다.
- 지금 가장 먼저 닫아야 할 공백은 `Coinone WS freshness`와 `WS-first collector`다.
- 그 다음 축은 `Bithumb WS`, `pair-level lock`, `실제 잔고 snapshot`, `private execution 최종 경로`, `정식 테스트 승격`이다.
