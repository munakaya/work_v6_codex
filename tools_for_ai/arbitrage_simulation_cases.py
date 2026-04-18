from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.strategy.arbitrage_simulation import (
    SimulationBalanceSettings,
    SimulationRiskSettings,
    SimulationStatsTracker,
    evaluate_directional_opportunities,
    normalize_simulation_pairs,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _snapshot(
    *,
    exchange: str,
    best_bid: str,
    best_ask: str,
    bid_volume: str = "1.5",
    ask_volume: str = "1.5",
) -> dict[str, object]:
    now_text = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "exchange": exchange,
        "market": "KRW-BTC",
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_volume": bid_volume,
        "ask_volume": ask_volume,
        "exchange_timestamp": now_text,
        "received_at": now_text,
        "exchange_age_ms": 0,
        "stale": False,
        "source_type": "rest",
    }


def _case_pair_normalization() -> None:
    pairs = normalize_simulation_pairs(["upbit:bithumb", "upbit:bithumb", "bithumb:coinone"])
    _assert(
        pairs == (("upbit", "bithumb"), ("bithumb", "coinone")),
        "pair normalization mismatch",
    )
    try:
        normalize_simulation_pairs(["upbit"])
    except ValueError:
        return
    raise SystemExit("invalid pair format must raise ValueError")


def _case_directional_evaluation() -> None:
    forward, reverse = evaluate_directional_opportunities(
        market="KRW-BTC",
        canonical_symbol="KRW-BTC",
        first_snapshot=_snapshot(exchange="upbit", best_bid="100", best_ask="101"),
        second_snapshot=_snapshot(exchange="bithumb", best_bid="105", best_ask="106"),
        first_exchange="upbit",
        second_exchange="bithumb",
        base_asset="BTC",
        quote_asset="KRW",
        balances=SimulationBalanceSettings(
            available_quote=Decimal("500"),
            available_base=Decimal("2"),
        ),
        risk=SimulationRiskSettings(
            min_profit_quote=Decimal("1"),
            min_profit_bps=Decimal("1"),
            max_clock_skew_ms=1000,
            max_orderbook_age_ms=5000,
            max_balance_age_ms=5000,
            max_notional_per_order=Decimal("1000"),
            max_total_notional_per_bot=Decimal("1000"),
            max_spread_bps=Decimal("1000"),
        ),
    )
    _assert(forward.accepted is True, "forward direction should be accepted")
    _assert(
        forward.reason_code == "ARBITRAGE_OPPORTUNITY_FOUND",
        "forward reason code mismatch",
    )
    _assert(reverse.accepted is False, "reverse direction should be rejected")
    _assert(
        reverse.reason_code == "EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH",
        "reverse rejection mismatch",
    )
    _assert(
        forward.executable_profit_quote is not None
        and forward.executable_profit_quote > Decimal("0"),
        "forward profit should be positive",
    )


def _case_stats_tracker() -> None:
    tracker = SimulationStatsTracker()
    forward, reverse = evaluate_directional_opportunities(
        market="KRW-BTC",
        canonical_symbol="KRW-BTC",
        first_snapshot=_snapshot(exchange="upbit", best_bid="100", best_ask="101"),
        second_snapshot=_snapshot(exchange="coinone", best_bid="104", best_ask="105"),
        first_exchange="upbit",
        second_exchange="coinone",
        base_asset="BTC",
        quote_asset="KRW",
        balances=SimulationBalanceSettings(
            available_quote=Decimal("500"),
            available_base=Decimal("2"),
        ),
        risk=SimulationRiskSettings(
            min_profit_quote=Decimal("1"),
            min_profit_bps=Decimal("1"),
            max_clock_skew_ms=1000,
            max_orderbook_age_ms=5000,
            max_balance_age_ms=5000,
            max_notional_per_order=Decimal("1000"),
            max_total_notional_per_bot=Decimal("1000"),
            max_spread_bps=Decimal("1000"),
        ),
    )
    tracker.record(forward)
    tracker.record(reverse)
    snapshot = tracker.snapshot()
    _assert(snapshot["direction_count"] == 2, "direction count mismatch")
    _assert(snapshot["observed_count"] == 2, "observed count mismatch")
    _assert(snapshot["accepted_count"] == 1, "accepted count mismatch")
    _assert(snapshot["rejected_count"] == 1, "rejected count mismatch")
    _assert(
        Decimal(str(snapshot["cumulative_profit_quote"])) > Decimal("0"),
        "cumulative profit mismatch",
    )


def main() -> None:
    _case_pair_normalization()
    _case_directional_evaluation()
    _case_stats_tracker()
    print("PASS arbitrage simulation observer helpers evaluate and aggregate correctly")


if __name__ == "__main__":
    main()
