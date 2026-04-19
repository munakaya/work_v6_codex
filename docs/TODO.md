# TODO

이 문서는 아직 남아 있는 구현/운영 보강 항목을 짧게 적어두는 메모다.
이번 목록은 `/home/user/git_work/work_v6_claude`, `/home/user/git_work/work_v4.1`를 다시 보고,
현재 저장소에 바로 도움이 되는 항목만 추렸다.

## 실연결 전 우선

- [ ] 3거래소 동시 비교용 candidate selection 설계 반영
  지금 구조는 `base_exchange + hedge_exchange` 2거래소 고정 평가라서,
  `upbit/bithumb/coinone`처럼 3개 거래소를 동시에 보고 가장 좋은 pair 하나를 고르는 런타임 계약이 필요하다.
  목표는 execution을 3-leg로 바꾸는 게 아니라, "다거래소 후보 평가 -> `selected_pair` 1개 선택 -> 기존 2-leg 주문 제출"로 정리하는 것이다.

- [ ] `/api/v1/ready` 판정을 더 엄격하게 만들기
  지금은 runtime 정보를 보여주기만 하고 실제 ready 판정에는 거의 안 쓴다.
  `market_data_runtime`, `strategy_runtime`, `recovery_runtime`의 `state`, `last_error_message`, `failure_count`를 기준으로 `ok/degraded`를 더 보수적으로 계산할 필요가 있다.

- [ ] 실호가 기반 손익 검증 도구 추가
  `work_v4.1/tools_for_ai/test_profit_pipeline.ts`, `work_v6_claude/tools_for_ai/orderbook_test.ts`처럼 업비트/빗썸/코인원 실제 오더북으로
  현재 `arbitrage_pricing` 결과를 수동 계산과 비교하는 AI 전용 도구가 필요하다.
  특히 `fee`, `depth`, `slippage`, `rebalance_buffer_quote`가 실제 숫자로 어떻게 반영되는지 점검해야 한다.

- [ ] 전략 핫패스에서 REST 중복 조회 제거
  지금은 `market_data_runtime`이 Redis에 snapshot을 sync해도, `strategy_runtime`은 다시 거래소 REST를 직접 조회한다.
  재정거래 봇의 핵심 경로는 `DB -> 재조회`가 아니라 `REST-only + 중복 fetch`가 병목이므로, `collector/cache 재사용`으로 단일화가 필요하다.

- [ ] direct market read endpoint를 cached 우선으로 정리
  `/api/v1/market-data/orderbook-top` 같은 direct fetch 경로가 운영 화면/모니터링에서 자주 쓰이면 같은 공인 IP의 rate budget을 갉아먹는다.
  운영 기본값은 cached read를 우선으로 하고, direct fetch는 디버깅 용도로만 남기는 쪽이 안전하다.

- [ ] public WS 기반 핫패스 전환
  현재 문서 목표는 WS가 빠른 orderbook 공급원인데, 실제 구현은 전략 판단이 REST 재조회에 의존한다.
  `public WS -> 최신 snapshot cache -> strategy runtime`으로 바꾸고 REST는 reconnect/fallback 보정으로 제한해야 한다.

- [ ] 거래 락(`trade lock`)을 현재 구조에 맞게 추가
  `work_v6_claude/packages/server/src/services/trade_lock.ts`처럼
  같은 `market + exchange pair`에 대해 중복 진입을 막는 명시적 락이 필요하다.
  지금은 recovery trace와 active intent로 많이 막고 있지만, 실 executor 연결 후에는 “같은 기회에 두 번 진입”을 더 직접 막는 게 안전하다.
  특히 3거래소 동시 비교로 가면 `selected_pair` 기준 락과 "같은 틱 내 재선택 방지"가 같이 필요하다.

## 운영 안정성 보강

- [ ] reconciliation backlog 요약을 운영 API/메트릭으로 노출
  `work_v6_claude/packages/bot/src/jobs/reconciliation.ts`처럼
  “몇 건이 오래 unresolved인지”, “몇 번 보정했는지”, “계속 mismatch인 trace가 몇 개인지”를 따로 모아 보여줄 필요가 있다.
  지금은 trace 단건 조회는 되지만 backlog 압축 요약은 약하다.

- [ ] inventory skew / rebalance 제안 추가
  `work_v6_claude/packages/bot/src/strategy/rebalancer.ts`처럼
  거래소 간 `KRW`/코인 비율이 한쪽으로 쏠리면 “자동 전송”이 아니라 최소한 `알림 + 제안`은 있어야 한다.
  현재는 `rebalance_buffer_quote`로 비용만 미리 빼고 있어서, 실제 inventory imbalance 운영 대응이 비어 있다.

- [ ] in-flight order/fill 추적 캐시 보강
  `work_v4.1/packages/shared/src/order/order_tracker.ts`, `order_state.ts`처럼
  최근 terminal 주문을 짧게 캐시해서 중복 fill, 늦게 도착한 fill, partial fill 재수신을 더 안정적으로 흡수하는 레이어를 검토할 가치가 있다.
  지금도 store 검증은 강하지만, 실 executor/WS 연결 후에는 짧은 메모리 캐시가 운영상 도움이 될 수 있다.

## 후순위

- [ ] 네트워크/외부 executor 상태를 backoff 포함 모니터로 분리
  `work_v4.1/packages/shared/src/network_monitor.ts`처럼
  private executor health를 단순 probe 한 번이 아니라 연속 실패/backoff 상태까지 가진 작은 monitor로 분리하는 방향을 검토한다.

- [ ] malformed private executor 응답의 서버 레벨 회귀를 더 늘리기
  지금은 `private_http_adapter_cases.py` direct 검증은 강한 편인데,
  `evaluate-arbitrage` HTTP 경로까지 포함한 malformed 응답 회귀는 아직 더 늘릴 수 있다.

## 메모

- `spool`, `status file` 같은 항목은 참고 저장소 구조에는 맞지만 현재 저장소 구조와 바로 같지 않아서 이번 TODO에는 넣지 않았다.
- 실제 거래소별 주문/체결 구현은 여전히 공식 API 버전 pinning 이후에 진행하는 것이 맞다.
