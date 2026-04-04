from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from trading_platform.strategy import (
    classify_submit_failure_transition,
    evaluate_arbitrage,
    load_strategy_inputs,
)


def _base_payload() -> dict[str, object]:
    now = datetime.now(UTC)
    now_text = now.isoformat().replace("+00:00", "Z")
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
            "asks": [
                {"price": "100", "quantity": "1.0"},
                {"price": "101", "quantity": "1.0"},
            ],
            "bids": [{"price": "99", "quantity": "1.0"}],
            "connector_healthy": True,
        },
        "hedge_orderbook": {
            "exchange_name": "bithumb",
            "market": "BTC-KRW",
            "observed_at": now_text,
            "asks": [{"price": "106", "quantity": "1.0"}],
            "bids": [
                {"price": "105", "quantity": "1.0"},
                {"price": "104", "quantity": "1.0"},
            ],
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


def _case_accept() -> dict[str, object]:
    return _base_payload()


def _case_depth_negative() -> dict[str, object]:
    payload = _base_payload()
    payload["base_orderbook"] = {
        **dict(payload["base_orderbook"]),
        "asks": [
            {"price": "100", "quantity": "1.0"},
            {"price": "110", "quantity": "1.0"},
        ],
    }
    payload["hedge_orderbook"] = {
        **dict(payload["hedge_orderbook"]),
        "bids": [{"price": "105", "quantity": "2.0"}],
    }
    return payload


def _case_orderbook_stale() -> dict[str, object]:
    payload = _base_payload()
    stale_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    payload["hedge_orderbook"] = {
        **dict(payload["hedge_orderbook"]),
        "observed_at": stale_at,
    }
    return payload


def _case_skew() -> dict[str, object]:
    payload = _base_payload()
    old_at = (datetime.now(UTC) - timedelta(milliseconds=800)).isoformat().replace("+00:00", "Z")
    payload["hedge_orderbook"] = {
        **dict(payload["hedge_orderbook"]),
        "observed_at": old_at,
    }
    payload["risk_config"] = {
        **dict(payload["risk_config"]),
        "max_orderbook_age_ms": 5000,
        "max_clock_skew_ms": 100,
    }
    return payload


def _case_reservation_failed() -> dict[str, object]:
    payload = _base_payload()
    payload["base_balance"] = {
        **dict(payload["base_balance"]),
        "available_quote": "95",
    }
    return payload


def _case_risk_blocked() -> dict[str, object]:
    payload = _base_payload()
    payload["risk_config"] = {
        **dict(payload["risk_config"]),
        "max_notional_per_order": "50",
        "max_total_notional_per_bot": "50",
    }
    payload["runtime_state"] = {
        **dict(payload["runtime_state"]),
        "remaining_bot_notional": "50",
    }
    return payload


def _case_reentry_cooldown() -> dict[str, object]:
    payload = _base_payload()
    recent = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    payload["runtime_state"] = {
        **dict(payload["runtime_state"]),
        "recent_unwind_at": recent,
    }
    return payload


def _case_hedge_confidence_low() -> dict[str, object]:
    payload = _base_payload()
    payload["runtime_state"] = {
        **dict(payload["runtime_state"]),
        "connector_private_healthy": False,
    }
    return payload


def _case_duplicate_intent() -> dict[str, object]:
    payload = _base_payload()
    payload["runtime_state"] = {
        **dict(payload["runtime_state"]),
        "duplicate_intent_active": True,
    }
    return payload


def _case_balance_stale() -> dict[str, object]:
    payload = _base_payload()
    stale_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    payload["base_balance"] = {
        **dict(payload["base_balance"]),
        "observed_at": stale_at,
        "is_fresh": True,
    }
    return payload


def _case_high_spread_outlier() -> dict[str, object]:
    payload = _base_payload()
    payload["hedge_orderbook"] = {
        **dict(payload["hedge_orderbook"]),
        "bids": [{"price": "120", "quantity": "2.0"}],
    }
    payload["risk_config"] = {
        **dict(payload["risk_config"]),
        "max_spread_bps": "500",
    }
    return payload


def _case_submit_failure_recovery() -> tuple[bool, str]:
    payload = _base_payload()
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    transition = classify_submit_failure_transition(
        decision_accepted=decision.accepted,
        reservation_passed=bool(
            decision.reservation_plan and decision.reservation_plan.reservation_passed
        ),
        submit_failed=True,
        auto_unwind_allowed=False,
    )
    return transition["recovery_required"] is True, str(transition["next_state"])


def _case_rebalance_buffer_reject() -> tuple[bool, str, str]:
    payload = _base_payload()
    payload["risk_config"] = {
        **dict(payload["risk_config"]),
        "slippage_buffer_bps": "10",
        "rebalance_buffer_quote": "8",
    }
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    computed = dict(decision.decision_context.get("computed") or {})
    return (
        decision.accepted is False,
        str(decision.reason_code),
        str(computed.get("rebalance_buffer_quote")),
    )


CASES = [
    ("C1", _case_accept, True, "ARBITRAGE_OPPORTUNITY_FOUND"),
    ("C2", _case_depth_negative, False, "EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH"),
    ("C3", _case_orderbook_stale, False, "ORDERBOOK_STALE"),
    ("C4", _case_skew, False, "QUOTE_PAIR_SKEW_TOO_HIGH"),
    ("C5", _case_reservation_failed, False, "RESERVATION_FAILED"),
    ("C6", _case_risk_blocked, False, "RISK_LIMIT_BLOCKED"),
    ("C7", _case_reentry_cooldown, False, "REENTRY_COOLDOWN_ACTIVE"),
    ("C8", _case_hedge_confidence_low, False, "HEDGE_CONFIDENCE_TOO_LOW"),
    ("C9", _case_duplicate_intent, False, "DUPLICATE_INTENT_BLOCKED"),
    ("C10", _case_balance_stale, False, "BALANCE_STALE"),
    ("C11", _case_high_spread_outlier, False, "RISK_LIMIT_BLOCKED"),
]


def main() -> int:
    failed = 0
    for case_id, factory, expected_accept, expected_reason in CASES:
        payload = deepcopy(factory())
        decision = evaluate_arbitrage(load_strategy_inputs(payload))
        ok = decision.accepted is expected_accept and decision.reason_code == expected_reason
        print(
            f"{case_id} {'PASS' if ok else 'FAIL'} "
            f"accepted={decision.accepted} reason={decision.reason_code}"
        )
        if not ok:
            failed += 1

    c12_ok, c12_state = _case_submit_failure_recovery()
    c12_pass = c12_ok and c12_state == "recovery_required"
    print(
        f"C12 {'PASS' if c12_pass else 'FAIL'} "
        f"recovery_required={c12_ok} next_state={c12_state}"
    )
    if not c12_pass:
        failed += 1

    c13_rejected, c13_reason, c13_rebalance = _case_rebalance_buffer_reject()
    c13_pass = (
        c13_rejected
        and c13_reason == "EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH"
        and c13_rebalance == "8"
    )
    print(
        f"C13 {'PASS' if c13_pass else 'FAIL'} "
        f"rejected={c13_rejected} reason={c13_reason} rebalance_buffer_quote={c13_rebalance}"
    )
    if not c13_pass:
        failed += 1

    return failed


if __name__ == "__main__":
    raise SystemExit(main())
