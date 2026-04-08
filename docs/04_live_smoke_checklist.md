# Exchange Live Smoke Checklist

이 문서는 private 거래소 연동을 실제로 붙이기 직전과 직후에 확인할 최소 smoke 절차를 적는다.
현재 저장소는 private connector가 아직 placeholder 단계이므로, 이 문서는 구현 전 승인 기준과 구현 후 실행 순서를 고정하는 용도다.


## 공통 전제

- 실계정은 최소 권한으로 준비한다.
- 허용 IP가 필요한 거래소는 운영 IP를 먼저 등록한다.
- 소액 주문만 사용한다.
- smoke 중 생성한 주문과 체결은 모두 추적 가능해야 한다.
- `timeline`, `balance`, `recovery` 표면에서 같은 사건이 보이는지 같이 확인한다.


## 공통 체크

1. trading key가 `/dev/shm/keys/{exchange}_trading.json` 또는 fallback 경로에 배치됨
2. `/api/v1/runtime/private-connectors`
3. `/api/v1/runtime/private-ws`
4. balance 조회
5. 주문 가능 정보 조회
6. 소액 주문 제출
7. 주문 상태 조회
8. 취소 가능 주문이면 취소
9. private WS 주문 이벤트 수신 확인
10. recovery/timeline 표면 반영 확인


## Upbit

사전 확인:

- key 권한 그룹 확인
- 허용 IP 설정 확인
- private WS 재연결 시 토큰 재생성이 되는지 확인 필요

smoke 순서:

1. 인증 성공
2. balance 조회 성공
3. 주문 가능 마켓 정보 조회 성공
4. 소액 주문 제출
5. 주문 단건 조회
6. 필요 시 취소
7. private WS에서 내 주문/체결 이벤트 수신 확인


## Bithumb

사전 확인:

- auth profile이 어떤 문서 버전에 맞춰 구현됐는지 release note에 고정
- 주문 API limiter와 일반 private limiter 분리 여부 확인

smoke 순서:

1. 인증 성공
2. balance 조회 성공
3. 주문 가능 정보 조회 성공
4. 소액 주문 제출
5. 주문 단건 조회
6. 필요 시 취소
7. private WS 주문 이벤트 수신 확인


## Coinone

사전 확인:

- nonce 재사용 방지 확인
- private WS close code 분류 확인
- 연결 수 제한과 idle timeout 기준 확인

smoke 순서:

1. 인증 성공
2. balance 조회 성공
3. 주문 가능 정보 조회 성공
4. 소액 주문 제출
5. 주문 단건 조회
6. 필요 시 취소
7. private WS `MYORDER` 또는 `MYASSET` 이벤트 수신 확인


## 실패 처리 원칙

- auth 실패는 retry보다 문서/권한/profile 재확인이 먼저다.
- rate limit은 즉시 backoff 동작이 보여야 한다.
- 주문 제출과 private WS 이벤트가 어긋나면 reconciliation 경로를 연다.
- residual exposure가 남으면 live gate를 닫지 않는다.


## 승인 기준

- 거래소별 인증 성공
- 소액 주문 제출/조회/취소 성공
- private WS 이벤트 확인
- recovery/timeline surface 반영 확인
- critical alert 없이 종료
