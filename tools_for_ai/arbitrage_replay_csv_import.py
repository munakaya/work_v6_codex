from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _parse_expected_accepted(raw: str) -> bool | None:
    lowered = raw.strip().lower()
    if not lowered:
        return None
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise ValueError("expected_accepted must be true/false when present")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import replay CSV back into JSON cases.")
    parser.add_argument("input_csv")
    parser.add_argument("output_json")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    output_path = Path(args.output_json)
    if not input_path.is_absolute():
        input_path = ROOT_DIR / input_path
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    cases: list[dict[str, object]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            cases.append(
                {
                    "case_id": row.get("case_id") or None,
                    "expected_accepted": _parse_expected_accepted(row.get("expected_accepted") or ""),
                    "expected_reason_code": row.get("expected_reason_code") or None,
                    "payload": json.loads(row.get("payload_json") or "{}"),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
