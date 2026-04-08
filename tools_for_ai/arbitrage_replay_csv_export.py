from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export replay JSON cases to CSV.")
    parser.add_argument("input_json")
    parser.add_argument("output_csv")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    output_path = Path(args.output_csv)
    if not input_path.is_absolute():
        input_path = ROOT_DIR / input_path
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = [payload]
    elif isinstance(payload, list):
        cases = payload
    else:
        raise ValueError("replay export input must be an object or array")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "expected_accepted", "expected_reason_code", "payload_json"],
        )
        writer.writeheader()
        for index, case in enumerate(cases, start=1):
            if not isinstance(case, dict):
                raise ValueError("all replay cases must be objects")
            payload_json = case.get("payload") if isinstance(case.get("payload"), dict) else case
            writer.writerow(
                {
                    "case_id": case.get("case_id") or case.get("name") or f"case_{index:03d}",
                    "expected_accepted": case.get("expected_accepted"),
                    "expected_reason_code": case.get("expected_reason_code"),
                    "payload_json": json.dumps(payload_json, ensure_ascii=False, separators=(",", ":")),
                }
            )


if __name__ == "__main__":
    main()
