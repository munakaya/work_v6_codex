from __future__ import annotations

from copy import deepcopy
import argparse
import json
from pathlib import Path
from typing import Any

from trading_platform.strategy import evaluate_arbitrage, load_strategy_inputs


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_input(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("event replay input must be a JSON object")
    return payload


def _apply_patch(target: dict[str, object], patch: dict[str, object]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _apply_patch(target[key], value)  # type: ignore[index]
            continue
        target[key] = value


def _evaluate(case_id: str, payload: dict[str, object], event: dict[str, object]) -> dict[str, Any]:
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    expected_accepted = event.get("expected_accepted")
    expected_reason_code = event.get("expected_reason_code")
    accepted_match = (
        None
        if expected_accepted is None
        else bool(expected_accepted) == bool(decision.accepted)
    )
    reason_match = (
        None
        if expected_reason_code is None
        else str(expected_reason_code) == str(decision.reason_code)
    )
    return {
        "case_id": case_id,
        "accepted": bool(decision.accepted),
        "reason_code": str(decision.reason_code),
        "expected_accepted": expected_accepted,
        "expected_reason_code": expected_reason_code,
        "accepted_match": accepted_match,
        "reason_code_match": reason_match,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay arbitrage decisions from event stream input.")
    parser.add_argument("input_path")
    parser.add_argument("--fail-on-mismatch", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.is_absolute():
        input_path = ROOT_DIR / input_path

    replay_input = _load_input(input_path)
    initial_payload = replay_input.get("initial_payload")
    events = replay_input.get("events")
    if not isinstance(initial_payload, dict) or not isinstance(events, list):
        raise ValueError("event replay input requires initial_payload object and events array")

    payload = deepcopy(initial_payload)
    results: list[dict[str, Any]] = []
    for index, raw_event in enumerate(events, start=1):
        if not isinstance(raw_event, dict):
            raise ValueError("event items must be objects")
        event_type = str(raw_event.get("event_type") or "").strip()
        if event_type in {"base_orderbook", "hedge_orderbook", "base_balance", "hedge_balance", "runtime_state", "risk_config"}:
            patch = raw_event.get("patch") or raw_event.get("snapshot")
            if not isinstance(patch, dict):
                raise ValueError(f"{event_type} event requires patch or snapshot object")
            current = payload.get(event_type)
            if not isinstance(current, dict):
                raise ValueError(f"initial payload is missing object for {event_type}")
            _apply_patch(current, patch)
            continue
        if event_type == "evaluate":
            case_id = str(raw_event.get("case_id") or f"event_{index:03d}")
            results.append(_evaluate(case_id, payload, raw_event))
            continue
        raise ValueError(f"unsupported event_type: {event_type}")

    summary = {
        "count": len(results),
        "mismatch_count": sum(
            1
            for item in results
            if item["accepted_match"] is False or item["reason_code_match"] is False
        ),
    }
    print(json.dumps({"input_path": str(input_path), "summary": summary, "items": results}, ensure_ascii=False, indent=2))
    if args.fail_on_mismatch and summary["mismatch_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
