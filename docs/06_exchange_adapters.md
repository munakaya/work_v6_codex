# Exchange Adapters Overview

이 문서는 거래소 어댑터 설계의 진입점이다. 공통 계약과 거래소별 레퍼런스는 아래 하위 문서로 분리되어 있다.

- `06_exchange_adapter_core.md`: 공통 책임, 설계 진행 상태, 공식 문서 재검증 메모
- `06_exchange_protocol_reference.md`: endpoint inventory, auth flow, error mapping, symbol/fee/precision
- `06_exchange_validation.md`: 통합 테스트 매트릭스

읽는 순서:

1. 공통 인터페이스와 책임을 잡을 때 `06_exchange_adapter_core.md`
2. 거래소별 차이를 구현할 때 `06_exchange_protocol_reference.md`
3. 구현 후 검증 범위를 확인할 때 `06_exchange_validation.md`
