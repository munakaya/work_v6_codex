# Arbitrage Replay Runner

이 문서는 저장된 재정거래 입력 payload를 다시 평가하는 최소 replay 도구를 설명한다.
현재 구현은 event stream 전체를 재생하지는 않고, `evaluate_arbitrage()`에 들어가는 정규화 payload를 다시 돌려 회귀를 확인하는 단계다.


## 목적

- 전략 판단 회귀를 빠르게 확인
- accepted / rejected / reason_code 변화를 비교
- 구현 변경 후 동일 입력에서 판단이 달라졌는지 체크


## 입력 형식

파일은 아래 둘 중 하나를 받는다.

1. 단일 payload object
2. payload array

권장 확장 필드:

- `case_id`
- `expected_accepted`
- `expected_reason_code`
- `payload`

`payload`가 없으면 object 전체를 전략 입력으로 본다.


## 실행

```bash
PYTHONPATH=src ./.venv/bin/python tools_for_ai/arbitrage_replay_runner.py path/to/replay.json
```

기대값까지 같이 검증하려면:

```bash
PYTHONPATH=src ./.venv/bin/python tools_for_ai/arbitrage_replay_runner.py path/to/replay.json --fail-on-mismatch
```


## 출력

출력은 JSON이다.

- `summary.count`
- `summary.accepted_count`
- `summary.rejected_count`
- `summary.mismatch_count`
- `summary.reason_code_counts`
- `items[].accepted`
- `items[].reason_code`
- `items[].accepted_match`
- `items[].reason_code_match`


## 한계

- 현재는 기록된 market/private event stream 자체를 재생하지 않는다.
- CSV import/export는 아직 없다.
- 실제 private adapter side effect는 포함하지 않는다.


## 용도

- 전략 코드 수정 후 빠른 회귀 확인
- shadow/live gate 이전 판단 reason 변화 점검
- 향후 event-level replay runner를 만들기 전 최소 안전장치
