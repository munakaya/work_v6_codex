from __future__ import annotations

from copy import deepcopy

from trading_platform.market_data_freshness import choose_freshness_observed_at
from trading_platform.strategy import evaluate_arbitrage, load_strategy_inputs


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _base_payload() -> dict[str, object]:
    now_text = "2026-04-20T10:00:05.400000Z"
    return {
        "bot_id": "bot-arb-coinone-001",
        "strategy_run_id": "run-arb-coinone-001",
        "canonical_symbol": "BTC-KRW",
        "market": "BTC-KRW",
        "base_exchange": "upbit",
        "hedge_exchange": "coinone",
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
            "exchange_name": "coinone",
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
            "exchange_name": "coinone",
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
            "max_clock_skew_ms": 1000,
            "max_orderbook_age_ms": 5000,
            "max_balance_age_ms": 5000,
            "max_notional_per_order": "500",
            "max_total_notional_per_bot": "500",
            "max_spread_bps": "1000",
            "slippage_buffer_bps": "0",
            "unwind_buffer_quote": "0",
            "taker_fee_bps_buy": "0",
            "taker_fee_bps_sell": "0",
            "reentry_cooldown_seconds": 0,
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


def _hedge_snapshot(*, exchange_timestamp: str, received_at: str, stale: bool) -> dict[str, object]:
    snapshot = {
        "exchange": "coinone",
        "market": "BTC-KRW",
        "best_bid": "105",
        "best_ask": "106",
        "bid_volume": "1.0",
        "ask_volume": "1.0",
        "bids": [{"price": "105", "quantity": "1.0"}],
        "asks": [{"price": "106", "quantity": "1.0"}],
        "exchange_timestamp": exchange_timestamp,
        "received_at": received_at,
        "exchange_age_ms": 4900 if not stale else 10044,
        "stale": stale,
        "source_type": "public_ws",
    }
    observed_at, observed_at_source = choose_freshness_observed_at(snapshot)
    return {
        "exchange_name": "coinone",
        "market": "BTC-KRW",
        "observed_at": observed_at,
        "observed_at_source": observed_at_source,
        "asks": [{"price": "106", "quantity": "1.0"}],
        "bids": [{"price": "105", "quantity": "1.0"}],
        "connector_healthy": True,
    }


def _case_boundary_fallback() -> None:
    payload = _base_payload()
    payload["hedge_orderbook"] = _hedge_snapshot(
        exchange_timestamp="2026-04-20T10:00:00.200000Z",
        received_at="2026-04-20T10:00:05.100000Z",
        stale=False,
    )
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    _assert(decision.accepted is True, f"coinone boundary fallback should stay actionable: {decision}")
    _assert(
        payload["hedge_orderbook"]["observed_at_source"] == "received_at",
        f"coinone boundary should use received_at freshness: {payload['hedge_orderbook']}",
    )


def _case_true_stale_snapshot() -> None:
    payload = deepcopy(_base_payload())
    payload["hedge_orderbook"] = _hedge_snapshot(
        exchange_timestamp="2026-04-20T10:00:00.000000Z",
        received_at="2026-04-20T09:59:59.000000Z",
        stale=True,
    )
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    _assert(decision.accepted is False, f"stale snapshot must be rejected: {decision}")
    _assert(decision.reason_code == "ORDERBOOK_STALE", f"stale reason mismatch: {decision}")
    _assert(
        payload["hedge_orderbook"]["observed_at_source"] == "received_at",
        f"coinone freshness should still be anchored to received_at: {payload['hedge_orderbook']}",
    )


def main() -> None:
    _case_boundary_fallback()
    _case_true_stale_snapshot()
    print("PASS Coinone public WS freshness uses received_at near the 5s boundary")
    print("PASS Coinone public WS freshness still rejects truly stale snapshots")


if __name__ == "__main__":
    main()
