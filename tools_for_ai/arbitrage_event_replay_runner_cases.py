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


def _initial_payload() -> dict[str, object]:
    now_text = "2026-04-08T12:00:00Z"
    return {
        "bot_id": "bot-arb-001",
        "strategy_run_id": "run-arb-001",
        "canonical_symbol": "BTC-KRW",
        "market": "BTC-KRW",
        "base_exchange": "upbit",
        "hedge_exchange": "bithumb",
        "base_orderbook": {
            "exchange_name": "upbit",
            "market": "BTC-KRW",
            "observed_at": now_text,
            "asks": [{"price": "100", "quantity": "1.0"}],
            "bids": [{"price": "99", "quantity": "1.0"}],
            "connector_healthy": True,
        },
        "hedge_orderbook": {
            "exchange_name": "bithumb",
            "market": "BTC-KRW",
            "observed_at": now_text,
            "asks": [{"price": "106", "quantity": "1.0"}],
            "bids": [{"price": "105", "quantity": "1.0"}],
            "connector_healthy": True,
        },
        "base_balance": {
            "exchange_name": "upbit",
            "base_asset": "BTC",
            "quote_asset": "KRW",
            "available_base": "0",
            "available_quote": "500",
            "observed_at": now_text,
            "is_fresh": True,
        },
        "hedge_balance": {
            "exchange_name": "bithumb",
            "base_asset": "BTC",
            "quote_asset": "KRW",
            "available_base": "2",
            "available_quote": "0",
            "observed_at": now_text,
            "is_fresh": True,
        },
        "risk_config": {
            "min_profit_quote": "1",
            "min_profit_bps": "1",
            "max_clock_skew_ms": 500,
            "max_orderbook_age_ms": 5000,
            "max_balance_age_ms": 5000,
            "max_notional_per_order": "500",
            "max_total_notional_per_bot": "500",
            "max_spread_bps": "1000",
            "slippage_buffer_bps": "0",
            "unwind_buffer_quote": "0",
            "taker_fee_bps_buy": "0",
            "taker_fee_bps_sell": "0",
            "reentry_cooldown_seconds": 30,
        },
        "runtime_state": {
            "now": now_text,
            "open_order_count": 0,
            "open_order_cap": 5,
            "unwind_in_progress": False,
            "connector_private_healthy": True,
            "duplicate_intent_active": False,
            "recent_unwind_at": None,
            "remaining_bot_notional": "500",
        },
    }


def main() -> None:
    replay_input = {
        "initial_payload": _initial_payload(),
        "events": [
            {
                "event_type": "evaluate",
                "case_id": "initial_accept",
                "expected_accepted": True,
                "expected_reason_code": "ARBITRAGE_OPPORTUNITY_FOUND",
            },
            {
                "event_type": "runtime_state",
                "patch": {"connector_private_healthy": False},
            },
            {
                "event_type": "evaluate",
                "case_id": "connector_down",
                "expected_accepted": False,
                "expected_reason_code": "HEDGE_CONFIDENCE_TOO_LOW",
            },
        ],
    }
    with tempfile.TemporaryDirectory(dir=ROOT_DIR / ".tmp") as tmp_dir:
        input_path = Path(tmp_dir) / "event_replay.json"
        input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = subprocess.run(
            [
                str(PYTHON_BIN),
                "tools_for_ai/arbitrage_event_replay_runner.py",
                str(input_path),
                "--fail-on-mismatch",
            ],
            cwd=str(ROOT_DIR),
            env={"PYTHONPATH": str(ROOT_DIR / "src")},
            check=True,
            capture_output=True,
            text=True,
        )
    payload = json.loads(completed.stdout)
    _assert(payload["summary"]["count"] == 2, "event replay count mismatch")
    _assert(payload["summary"]["mismatch_count"] == 0, "event replay mismatch count mismatch")
    print("PASS arbitrage event replay runner replays event sequence decisions")


if __name__ == "__main__":
    main()
