from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from trading_platform.strategy import evaluate_arbitrage, load_strategy_inputs


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_cases(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        cases: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("all replay cases must be json objects")
            cases.append(item)
        return cases
    raise ValueError("replay input must be an object or array")


def _payload_from_case(case: dict[str, object]) -> dict[str, object]:
    nested = case.get("payload")
    if isinstance(nested, dict):
        return nested
    return case


def _case_name(index: int, case: dict[str, object]) -> str:
    for key in ("case_id", "name", "id"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"case_{index:03d}"


def _evaluate_case(index: int, case: dict[str, object]) -> dict[str, Any]:
    payload = _payload_from_case(case)
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    expected_accepted = case.get("expected_accepted")
    expected_reason_code = case.get("expected_reason_code")
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
    computed = dict(decision.decision_context.get("computed") or {})
    return {
        "case_id": _case_name(index, case),
        "accepted": bool(decision.accepted),
        "reason_code": str(decision.reason_code),
        "expected_accepted": expected_accepted,
        "expected_reason_code": expected_reason_code,
        "accepted_match": accepted_match,
        "reason_code_match": reason_match,
        "target_qty": str(decision.candidate_size.target_qty)
        if decision.candidate_size is not None
        else None,
        "expected_profit_quote": str(computed.get("executable_profit_quote"))
        if computed.get("executable_profit_quote") is not None
        else None,
    }


def _summary(items: list[dict[str, Any]]) -> dict[str, object]:
    accepted_count = sum(1 for item in items if item["accepted"] is True)
    reject_count = len(items) - accepted_count
    reason_counts: dict[str, int] = {}
    mismatch_count = 0
    for item in items:
        reason_code = str(item["reason_code"])
        reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
        if item["accepted_match"] is False or item["reason_code_match"] is False:
            mismatch_count += 1
    return {
        "count": len(items),
        "accepted_count": accepted_count,
        "rejected_count": reject_count,
        "mismatch_count": mismatch_count,
        "reason_code_counts": reason_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay arbitrage decision payloads and print a summary."
    )
    parser.add_argument("input_path", help="JSON file containing one payload or an array")
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="exit non-zero if expected_accepted or expected_reason_code mismatches",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.is_absolute():
        input_path = ROOT_DIR / input_path

    cases = _load_cases(input_path)
    results = [_evaluate_case(index, case) for index, case in enumerate(cases, start=1)]
    payload = {
        "input_path": str(input_path),
        "summary": _summary(results),
        "items": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.fail_on_mismatch:
        has_mismatch = any(
            item["accepted_match"] is False or item["reason_code_match"] is False
            for item in results
        )
        if has_mismatch:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
