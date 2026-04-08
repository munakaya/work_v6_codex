from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    cases = [
        {
            "case_id": "sample_case",
            "expected_accepted": True,
            "expected_reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            "payload": {"bot_id": "bot-1", "strategy_run_id": "run-1"},
        }
    ]
    with tempfile.TemporaryDirectory(dir=ROOT_DIR / ".tmp") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_json = tmp_path / "cases.json"
        output_csv = tmp_path / "cases.csv"
        roundtrip_json = tmp_path / "roundtrip.json"
        input_json.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
        subprocess.run(
            [str(PYTHON_BIN), "tools_for_ai/arbitrage_replay_csv_export.py", str(input_json), str(output_csv)],
            cwd=str(ROOT_DIR),
            check=True,
            text=True,
        )
        subprocess.run(
            [str(PYTHON_BIN), "tools_for_ai/arbitrage_replay_csv_import.py", str(output_csv), str(roundtrip_json)],
            cwd=str(ROOT_DIR),
            check=True,
            text=True,
        )
        payload = json.loads(roundtrip_json.read_text(encoding="utf-8"))
    _assert(len(payload) == 1, "csv roundtrip count mismatch")
    _assert(payload[0]["case_id"] == "sample_case", "csv roundtrip case_id mismatch")
    _assert(
        payload[0]["expected_reason_code"] == "ARBITRAGE_OPPORTUNITY_FOUND",
        "csv roundtrip reason mismatch",
    )
    print("PASS replay csv export/import roundtrip")


if __name__ == "__main__":
    main()
