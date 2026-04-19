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
    ExchangeFetchScheduler,
    SimulationBalanceSettings,
    SimulationRiskSettings,
    SimulationStatsTracker,
    derive_pair_timing_gates,
    evaluate_directional_opportunities,
    normalize_exchange_intervals,
    normalize_simulation_pairs,
    risk_with_pair_timing_gates,
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
    observed_at: str | None = None,
) -> dict[str, object]:
    now_text = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
    _assert(forward.clock_skew_exceeded is False, "default skew diagnostic mismatch")
    _assert(
        forward.market_opportunity is True
        and forward.reservation_blocked is False
        and forward.zero_profit_opportunity is False,
        "forward opportunity flags mismatch",
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
        snapshot["reason_code_breakdown"]
        == {
            "ARBITRAGE_OPPORTUNITY_FOUND": 1,
            "EXECUTABLE_PROFIT_NEGATIVE_AFTER_DEPTH": 1,
        },
        "top-level reason breakdown mismatch",
    )
    _assert(
        Decimal(str(snapshot["cumulative_profit_quote"])) > Decimal("0"),
        "cumulative profit mismatch",
    )
    first_item = next(
        item
        for item in snapshot["items"]
        if item["direction"] == "upbit->coinone"
    )
    _assert(
        first_item["reason_code_breakdown"] == {"ARBITRAGE_OPPORTUNITY_FOUND": 1},
        "direction reason breakdown mismatch",
    )
    _assert(
        snapshot["clock_skew_diagnostic"]["exceeded_count"] == 0,
        "clock skew diagnostic top-level mismatch",
    )
    _assert(
        snapshot["market_opportunity_count"] == 1,
        "top-level market opportunity count mismatch",
    )


def _case_skew_diagnostic_only() -> None:
    base_time = "2026-04-19T00:00:00Z"
    hedge_time = "2026-04-19T00:00:02Z"
    forward, _ = evaluate_directional_opportunities(
        market="KRW-BTC",
        canonical_symbol="KRW-BTC",
        first_snapshot=_snapshot(
            exchange="upbit",
            best_bid="100",
            best_ask="101",
            observed_at=base_time,
        ),
        second_snapshot=_snapshot(
            exchange="bithumb",
            best_bid="105",
            best_ask="106",
            observed_at=hedge_time,
        ),
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
            max_clock_skew_ms=100,
            max_orderbook_age_ms=10000,
            max_balance_age_ms=5000,
            max_notional_per_order=Decimal("1000"),
            max_total_notional_per_bot=Decimal("1000"),
            max_spread_bps=Decimal("1000"),
            enforce_clock_skew_gate=False,
        ),
        now=datetime.fromisoformat("2026-04-19T00:00:03+00:00"),
    )
    _assert(forward.accepted is True, "skew diagnostic-only mode should accept")
    _assert(
        forward.clock_skew_ms == 2000 and forward.clock_skew_exceeded is True,
        "skew diagnostic metadata mismatch",
    )
    enforced_forward, _ = evaluate_directional_opportunities(
        market="KRW-BTC",
        canonical_symbol="KRW-BTC",
        first_snapshot=_snapshot(
            exchange="upbit",
            best_bid="100",
            best_ask="101",
            observed_at=base_time,
        ),
        second_snapshot=_snapshot(
            exchange="bithumb",
            best_bid="105",
            best_ask="106",
            observed_at=hedge_time,
        ),
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
            max_clock_skew_ms=100,
            max_orderbook_age_ms=10000,
            max_balance_age_ms=5000,
            max_notional_per_order=Decimal("1000"),
            max_total_notional_per_bot=Decimal("1000"),
            max_spread_bps=Decimal("1000"),
            enforce_clock_skew_gate=True,
        ),
        now=datetime.fromisoformat("2026-04-19T00:00:03+00:00"),
    )
    _assert(
        enforced_forward.reason_code == "QUOTE_PAIR_SKEW_TOO_HIGH",
        "skew enforced mode must still reject",
    )


def _case_reservation_blocked_diagnostic() -> None:
    forward, _ = evaluate_directional_opportunities(
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
            available_base=Decimal("0.1"),
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
    _assert(
        forward.accepted is False
        and forward.reason_code == "RESERVATION_FAILED"
        and forward.market_opportunity is True
        and forward.reservation_blocked is True,
        "reservation blocked diagnostic mismatch",
    )


def _case_exchange_intervals_and_scheduler() -> None:
    intervals = normalize_exchange_intervals(
        exchanges=("upbit", "bithumb", "coinone"),
        overrides=("upbit=3",),
        default_interval_seconds=1.0,
    )
    _assert(intervals["upbit"] == 3.0, "upbit interval override mismatch")
    _assert(intervals["bithumb"] == 1.0, "bithumb interval default mismatch")
    scheduler = ExchangeFetchScheduler(intervals)
    due_initial = scheduler.due_exchanges(
        exchanges=("upbit", "bithumb", "coinone"),
        now_monotonic=0.0,
    )
    _assert(
        due_initial == ("upbit", "bithumb", "coinone"),
        "initial due exchange mismatch",
    )
    for exchange in due_initial:
        scheduler.mark_attempt(exchange=exchange, now_monotonic=0.0)
    due_after_one_second = scheduler.due_exchanges(
        exchanges=("upbit", "bithumb", "coinone"),
        now_monotonic=1.0,
    )
    _assert(
        due_after_one_second == ("bithumb", "coinone"),
        "per-exchange interval scheduling mismatch",
    )
    due_after_three_seconds = scheduler.due_exchanges(
        exchanges=("upbit", "bithumb", "coinone"),
        now_monotonic=3.0,
    )
    _assert(
        due_after_three_seconds == ("upbit", "bithumb", "coinone"),
        "upbit interval should reopen after three seconds",
    )


def _case_pair_timing_gate_alignment() -> None:
    risk = SimulationRiskSettings(
        max_clock_skew_ms=1000,
        max_orderbook_age_ms=1000,
    )
    intervals = normalize_exchange_intervals(
        exchanges=("upbit", "bithumb"),
        overrides=("upbit=3", "bithumb=1"),
        default_interval_seconds=1.0,
    )
    gates = derive_pair_timing_gates(
        risk=risk,
        first_exchange="upbit",
        second_exchange="bithumb",
        exchange_intervals=intervals,
        timing_grace_ms=250,
        align_to_exchange_intervals=True,
    )
    _assert(
        gates == {
            "max_clock_skew_ms": 3250,
            "max_orderbook_age_ms": 3250,
        },
        "pair timing gate alignment mismatch",
    )
    unchanged_risk, unchanged_gates = risk_with_pair_timing_gates(
        risk=risk,
        first_exchange="upbit",
        second_exchange="bithumb",
        exchange_intervals=intervals,
        timing_grace_ms=250,
        align_to_exchange_intervals=False,
    )
    _assert(
        unchanged_gates == {
            "max_clock_skew_ms": 1000,
            "max_orderbook_age_ms": 1000,
        },
        "pair timing gate disable mismatch",
    )
    _assert(
        unchanged_risk.max_clock_skew_ms == 1000
        and unchanged_risk.max_orderbook_age_ms == 1000,
        "pair timing gate disabled risk mismatch",
    )


def main() -> None:
    _case_pair_normalization()
    _case_directional_evaluation()
    _case_stats_tracker()
    _case_skew_diagnostic_only()
    _case_reservation_blocked_diagnostic()
    _case_exchange_intervals_and_scheduler()
    _case_pair_timing_gate_alignment()
    print("PASS arbitrage simulation observer helpers evaluate and aggregate correctly")


if __name__ == "__main__":
    main()
