# Strategy and Risk Overview

이 문서는 전략 관련 설계의 진입점이다. 실제 규칙과 상세 설계는 아래 하위 문서로 분리되어 있다.

- `05_strategy_records.md`: Strategy Decision Record format과 Strategy ADR
- `05_arbitrage_algorithm_review.md`: 재정거래 핵심 알고리즘 비판적 재설계
- `05_arbitrage_algorithm_execution_spec.md`: 재정거래 알고리즘 구현 순서와 함수 분해
- `05_arbitrage_algorithm_validation_cases.md`: accept/reject 기준 테스트 케이스
- `05_trade_recovery.md`: reconciliation, unwind, hedge 실패 대응
- `05_risk_and_config.md`: parameter catalog, risk limit, config validation

읽는 순서:

1. 전략 방향과 기록 규칙이 필요하면 `05_strategy_records.md`
2. 재정거래 진입 알고리즘을 비판적으로 다시 보고 싶으면 `05_arbitrage_algorithm_review.md`
3. 실제 구현 단위와 함수 분해가 필요하면 `05_arbitrage_algorithm_execution_spec.md`
4. accept/reject 테스트 케이스가 필요하면 `05_arbitrage_algorithm_validation_cases.md`
5. 실주문 이후 정합성과 복구 로직이 필요하면 `05_trade_recovery.md`
6. live 승인 기준과 설정 안전장치가 필요하면 `05_risk_and_config.md`
