# TODO

이 문서는 아직 남아 있는 구현/운영 보강 항목을 짧게 적어두는 메모다.
이번 목록은 `/tmp/1`, `/tmp/2`, `/tmp/3`, `/tmp/4` 검토 결과를 현재 저장소 상태와 대조한 뒤,
실제로 아직 남아 있는 항목만 다시 추렸다.

## 최우선

- [x] 실거래 private REST connector 최소 계약 구현
  Upbit/Bithumb/Coinone의 private balance, place order, order status, open orders를 실제 API로 연결했다.
  남은 과제는 실계정 smoke, cancel flow, execution path 편입처럼 실운영 경로를 닫는 작업이다.

- [x] `private_http` 의존을 임시 경로로 명확히 격하
  `ready`의 `dependencies.private_execution`과 `strategy_runtime`에 `temporary_external_delegate` 메타데이터를 추가해,
  외부 executor 위임이 최종 실행 경로가 아니라 임시 실연결 경로임을 직접 드러내도록 정리했다.

- [x] Redis runtime을 `redis-cli` subprocess 의존에서 교체
  내부 RESP 기반 connection-pool 클라이언트로 치환해 `redis-cli` 없이도 Redis runtime이 동작하도록 바꿨다.
  명령 실패 시에는 무음 no-op 대신 `redis_runtime.state=degraded`로 내려가도록 정리했다.

- [x] 운영 환경에서 write API fail-closed 강제
  `APP_ENV=staging|production`에서는 `TP_ADMIN_TOKEN` 미설정 시 서버가 기동 실패하도록 바꿨다.
  local/dev에서만 write API 무토큰 기동을 허용하고, `ready.write_api_guard`에 요구 여부를 직접 노출한다.

- [x] 설계 진척도 문서 현실화
  `docs/08_progress_and_gaps.md`에서 설계 완성도와 구현/실거래 준비도를 분리했다.
  상위 설계는 높게 보되, `private_http` 임시 경로, WS-first 미완료, pair-level lock 부재, 정식 테스트 부재를 반영해 live readiness 숫자를 낮췄다.

## 실연결 전 보강

- [ ] public WS 기반 collector를 우선 경로로 전환
  전략 런타임의 direct REST 재조회 제거와 cache-only hot path는 이미 반영됐다.
  이제 남은 건 `public WS -> 최신 snapshot cache -> strategy runtime`을 기본 경로로 올리고, REST는 fallback/보정으로 내리는 일이다.

- [ ] market data collector coverage 확장
  실행 중 arbitrage run에서 파생된 `(exchange, market)` poll target 확장은 들어갔다.
  남은 과제는 다거래소/다심볼 전반에서 `MARKET_SNAPSHOT_NOT_FOUND`를 줄이도록 선제 수집 coverage와 target selection을 더 보강하는 것이다.

- [ ] 3거래소 동시 비교용 candidate selection 설계 반영
  지금 구조는 `base_exchange + hedge_exchange` 2거래소 고정 평가다.
  `upbit/bithumb/coinone`처럼 3개 거래소를 동시에 보고, 가장 좋은 `selected_pair` 1개를 고른 뒤 기존 2-leg execution으로 넘기는 계약이 필요하다.

- [ ] pair-level trade lock 추가
  현재는 active intent, recovery trace, open order count 중심으로 중복 진입을 막는다.
  실 executor 연결 전에는 `(market, selected_pair)` 기준의 명시적 락을 넣어 같은 기회에 중복 진입하지 않도록 더 직접 막아야 한다.

- [ ] 실제 잔고 연동으로 runtime balance spec 대체
  현재 전략 입력의 `base_balance`, `hedge_balance`는 runtime payload 중심이다.
  실연결 전에는 거래소 `get_balances()` 결과와 freshness 기준으로 balance snapshot을 구성하고, config/runtime 수동 잔고는 시뮬레이션 전용으로만 남겨야 한다.

## 검증 체계

- [ ] `tools_for_ai` 검증을 정식 테스트 스위트로 승격
  현재 실행형 케이스는 충분히 쌓였지만 `pytest/tests/CI` 체계가 없다.
  우선 핵심 케이스부터 정식 테스트로 승격해서 discoverability, 회귀 추적, 실패 집계를 확보해야 한다.

- [ ] 실호가 기반 VWAP/fee 검증 도구 보강
  현재 pricing은 top-N depth, fee, buffer를 잘 반영하지만 실호가 숫자 대조 도구는 더 보강할 가치가 있다.
  거래소별 실제 orderbook으로 `arbitrage_pricing` 결과를 수동 계산과 비교하는 검증을 계속 강화한다.

- [ ] malformed `private_http` 응답의 서버 레벨 회귀 확대
  direct adapter 검증은 강한 편이다.
  남은 과제는 `evaluate-arbitrage` 등 실제 서버 경로까지 포함한 malformed response 회귀를 더 늘리는 것이다.

- [ ] live/shadow/sim 편차 계측 추가
  다른 저장소들처럼 실행 모드별 판단 편차를 운영 지표로 보이게 해야 한다.
  특히 "선택된 후보 vs 미선택 후보", "shadow profit vs live fill", "REST fallback 사용 빈도"를 같이 집계하는 쪽이 좋다.

## 운영 안정성

- [ ] reconciliation backlog 요약 노출
  trace 단건 조회는 가능하지만, 오래 unresolved인 건수나 반복 mismatch는 요약이 약하다.
  운영 API/메트릭에서 backlog 압축 뷰를 제공해야 한다.

- [ ] inventory skew / rebalance 제안 추가
  현재는 `rebalance_buffer_quote`로 비용만 미리 차감한다.
  거래소 간 KRW/코인 쏠림이 심할 때 운영자에게 알림과 action hint를 주는 레이어가 필요하다.

- [ ] in-flight order/fill 단기 캐시 검토
  실 executor와 private WS를 붙이면 늦게 도착한 fill, duplicate fill, partial fill 재수신을 더 자주 다루게 된다.
  store 검증 외에 짧은 메모리 캐시를 두는 방안을 검토한다.

## 문서 정리

- [ ] `docs/04_operations.md`의 운영 기본값을 구현 현실에 맞게 조정
  현재 문서는 write API 보호를 선택 사항처럼 적고 있다.
  운영 환경에서는 필수, local 에서는 선택이라는 식으로 더 명확히 분리할 필요가 있다.

- [ ] `docs/11_implementation_tasks.md`의 우선순위를 실구현 기준으로 재정렬
  현재 작업판은 설계 시작용 순서의 흔적이 강하다.
  이제는 "private connector", "Redis runtime", "WS-first collector", "pair lock", "정식 테스트 승격" 순으로 더 직접적인 실행 우선순위를 드러내야 한다.

## 메모

- direct REST 재조회 제거와 cached snapshot 우선 로딩은 이미 반영됐다.
- write API bearer token / rate limit guard도 이미 구현 및 실행 검증되어 있다.
- 앞으로의 핵심 공백은 "문서 추가"보다 "실거래 경로 구현 + 운영 fail-closed + WS-first + 테스트 승격"이다.
