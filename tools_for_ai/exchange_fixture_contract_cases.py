from __future__ import annotations

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT_DIR / "tools_for_ai" / "fixtures" / "exchanges"
REQUIRED_KEYS = (
    "exchange",
    "public_orderbook",
    "order_create",
    "order_status",
    "order_cancel",
    "auth_failed",
    "rate_limited",
    "partial_fill_event",
    "terminal_fill_event",
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    fixture_files = sorted(FIXTURE_DIR.glob("*_contract_fixtures.json"))
    _assert(len(fixture_files) == 3, "expected three exchange fixture files")
    for path in fixture_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _assert(isinstance(payload, dict), f"{path.name} must be a JSON object")
        for key in REQUIRED_KEYS:
            _assert(key in payload, f"{path.name} missing key: {key}")
        exchange = payload["exchange"]
        _assert(path.name.startswith(str(exchange)), f"{path.name} exchange name mismatch")
        for key in REQUIRED_KEYS[1:]:
            _assert(isinstance(payload[key], dict), f"{path.name} {key} must be an object")
    print("PASS exchange fixture contracts include required response categories")


if __name__ == "__main__":
    main()
