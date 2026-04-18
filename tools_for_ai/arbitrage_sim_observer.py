from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from pathlib import Path
import sys
import time


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.config import load_config
from trading_platform.logging_setup import configure_logging
from trading_platform.market_data_connector import MarketDataError, PublicMarketDataConnector
from trading_platform.rate_limit import ExponentialBackoffPolicy, RateLimitPolicy
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


LOGGER = logging.getLogger(__name__)


def _build_connector() -> PublicMarketDataConnector:
    config = load_config()
    return PublicMarketDataConnector(
        timeout_ms=config.market_data_timeout_ms,
        stale_threshold_ms=config.market_data_stale_threshold_ms,
        retry_count=config.market_data_retry_count,
        retry_backoff=ExponentialBackoffPolicy(
            initial_delay_ms=config.market_data_retry_backoff_initial_ms,
            max_delay_ms=config.market_data_retry_backoff_max_ms,
        ),
        rate_limit_policies={
            "upbit": RateLimitPolicy(
                name="upbit_public_rest",
                rate_per_sec=config.upbit_public_rest_rate_limit_per_sec,
                burst=config.upbit_public_rest_burst,
            ),
            "bithumb": RateLimitPolicy(
                name="bithumb_public_rest",
                rate_per_sec=config.bithumb_public_rest_rate_limit_per_sec,
                burst=config.bithumb_public_rest_burst,
            ),
            "coinone": RateLimitPolicy(
                name="coinone_public_rest",
                rate_per_sec=config.coinone_public_rest_rate_limit_per_sec,
                burst=config.coinone_public_rest_burst,
            ),
        },
        upbit_base_url=config.upbit_quotation_base_url,
        bithumb_base_url=config.bithumb_public_base_url,
        coinone_base_url=config.coinone_public_base_url,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observe real public orderbooks and simulate arbitrage frequency/profit.",
    )
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--canonical-symbol", default="KRW-BTC")
    parser.add_argument("--base-asset", default="BTC")
    parser.add_argument("--quote-asset", default="KRW")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=["upbit:bithumb", "upbit:coinone", "bithumb:coinone"],
        help="Exchange pairs in buy/sell comparison groups. Each pair is evaluated in both directions.",
    )
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--duration-seconds", type=int, default=0)
    parser.add_argument("--summary-every", type=int, default=10)
    parser.add_argument(
        "--exchange-intervals",
        nargs="*",
        default=[],
        help="Optional per-exchange fetch cadence overrides. Example: upbit=3 bithumb=1 coinone=1",
    )
    parser.add_argument("--timing-grace-ms", type=int, default=250)
    parser.add_argument(
        "--disable-interval-gate-alignment",
        action="store_true",
        help="Disable pair timing gate alignment based on per-exchange fetch cadence.",
    )
    parser.add_argument("--quote-balance", type=Decimal, default=Decimal("200000000"))
    parser.add_argument("--base-balance", type=Decimal, default=Decimal("3"))
    parser.add_argument("--min-profit-quote", type=Decimal, default=Decimal("0"))
    parser.add_argument("--min-profit-bps", type=Decimal, default=Decimal("0"))
    parser.add_argument("--max-clock-skew-ms", type=int, default=1000)
    parser.add_argument("--max-orderbook-age-ms", type=int, default=5000)
    parser.add_argument("--max-balance-age-ms", type=int, default=60000)
    parser.add_argument(
        "--max-notional-per-order",
        type=Decimal,
        default=Decimal("1000000000"),
    )
    parser.add_argument(
        "--max-total-notional-per-bot",
        type=Decimal,
        default=Decimal("1000000000"),
    )
    parser.add_argument("--max-spread-bps", type=Decimal, default=Decimal("100000"))
    parser.add_argument("--min-orderbook-depth-levels", type=int, default=1)
    parser.add_argument(
        "--min-available-depth-quote",
        type=Decimal,
        default=Decimal("0"),
    )
    parser.add_argument("--slippage-buffer-bps", type=Decimal, default=Decimal("0"))
    parser.add_argument("--unwind-buffer-quote", type=Decimal, default=Decimal("0"))
    parser.add_argument("--rebalance-buffer-quote", type=Decimal, default=Decimal("0"))
    parser.add_argument("--taker-fee-bps-buy", type=Decimal, default=Decimal("0"))
    parser.add_argument("--taker-fee-bps-sell", type=Decimal, default=Decimal("0"))
    parser.add_argument("--reentry-cooldown-seconds", type=int, default=0)
    return parser.parse_args()


def _snapshot_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S%f")[:-3]
    output_dir = ROOT_DIR / ".tmp" / "arbitrage_sim"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{timestamp}.jsonl"


def _risk_settings(args: argparse.Namespace) -> SimulationRiskSettings:
    return SimulationRiskSettings(
        min_profit_quote=args.min_profit_quote,
        min_profit_bps=args.min_profit_bps,
        max_clock_skew_ms=args.max_clock_skew_ms,
        max_orderbook_age_ms=args.max_orderbook_age_ms,
        max_balance_age_ms=args.max_balance_age_ms,
        max_notional_per_order=args.max_notional_per_order,
        max_total_notional_per_bot=args.max_total_notional_per_bot,
        max_spread_bps=args.max_spread_bps,
        min_orderbook_depth_levels=args.min_orderbook_depth_levels,
        min_available_depth_quote=args.min_available_depth_quote,
        slippage_buffer_bps=args.slippage_buffer_bps,
        unwind_buffer_quote=args.unwind_buffer_quote,
        rebalance_buffer_quote=args.rebalance_buffer_quote,
        taker_fee_bps_buy=args.taker_fee_bps_buy,
        taker_fee_bps_sell=args.taker_fee_bps_sell,
        reentry_cooldown_seconds=args.reentry_cooldown_seconds,
    )


def _balance_settings(args: argparse.Namespace) -> SimulationBalanceSettings:
    return SimulationBalanceSettings(
        available_quote=args.quote_balance,
        available_base=args.base_balance,
    )


def _collect_tick_summary(
    *,
    tracker: SimulationStatsTracker,
    refresh_count_by_exchange: Counter[str],
    fetch_error_by_exchange: Counter[str],
    fetch_error_by_code: Counter[str],
    pair_skip_by_reason: Counter[str],
    exchange_intervals: dict[str, float],
    pair_timing_gates: dict[str, dict[str, int]],
    interval_gate_alignment_enabled: bool,
    timing_grace_ms: int,
) -> dict[str, object]:
    summary = tracker.snapshot()
    summary["configured_exchange_intervals"] = {
        exchange: interval for exchange, interval in sorted(exchange_intervals.items())
    }
    summary["interval_gate_alignment_enabled"] = interval_gate_alignment_enabled
    summary["timing_grace_ms"] = timing_grace_ms
    summary["effective_pair_timing_gates"] = {
        pair: gates for pair, gates in sorted(pair_timing_gates.items())
    }
    summary["refresh_count_by_exchange"] = {
        exchange: count for exchange, count in sorted(refresh_count_by_exchange.items())
    }
    summary["fetch_error_by_exchange"] = {
        exchange: count for exchange, count in sorted(fetch_error_by_exchange.items())
    }
    summary["fetch_error_by_code"] = {
        code: count for code, count in sorted(fetch_error_by_code.items())
    }
    summary["pair_skip_by_reason"] = {
        reason: count for reason, count in sorted(pair_skip_by_reason.items())
    }
    return summary


def main() -> None:
    config = load_config()
    log_path = configure_logging(config)
    args = _parse_args()
    interval_seconds = max(args.interval_seconds, 1.0)
    pairs = normalize_simulation_pairs(args.pairs)
    exchanges = sorted({exchange for pair in pairs for exchange in pair})
    exchange_intervals = normalize_exchange_intervals(
        exchanges=exchanges,
        overrides=args.exchange_intervals,
        default_interval_seconds=interval_seconds,
    )
    risk = _risk_settings(args)
    balances = _balance_settings(args)
    connector = _build_connector()
    tracker = SimulationStatsTracker()
    scheduler = ExchangeFetchScheduler(exchange_intervals)
    latest_snapshots: dict[str, dict[str, object]] = {}
    refresh_count_by_exchange: Counter[str] = Counter()
    fetch_error_by_exchange: Counter[str] = Counter()
    fetch_error_by_code: Counter[str] = Counter()
    pair_skip_by_reason: Counter[str] = Counter()
    interval_gate_alignment_enabled = not args.disable_interval_gate_alignment
    pair_timing_gates = {
        f"{first_exchange}:{second_exchange}": derive_pair_timing_gates(
            risk=risk,
            first_exchange=first_exchange,
            second_exchange=second_exchange,
            exchange_intervals=exchange_intervals,
            timing_grace_ms=args.timing_grace_ms,
            align_to_exchange_intervals=interval_gate_alignment_enabled,
        )
        for first_exchange, second_exchange in pairs
    }
    output_path = _snapshot_path()

    LOGGER.info(
        "starting arbitrage sim observer market=%s pairs=%s interval_seconds=%s exchange_intervals=%s output=%s log=%s",
        args.market,
        ",".join(f"{left}:{right}" for left, right in pairs),
        interval_seconds,
        exchange_intervals,
        output_path,
        log_path,
        extra={"event_name": "arbitrage_sim_observer_started"},
    )

    iterations = 0
    started_at = time.monotonic()
    next_tick_at = started_at
    while True:
        if args.iterations > 0 and iterations >= args.iterations:
            break
        if args.duration_seconds > 0 and (time.monotonic() - started_at) >= args.duration_seconds:
            break

        current_time = datetime.now(UTC)
        due_exchanges = scheduler.due_exchanges(
            exchanges=exchanges,
            now_monotonic=time.monotonic(),
        )
        refreshed_exchanges: set[str] = set()
        fetch_errors: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=max(len(due_exchanges), 1)) as executor:
            futures = {
                executor.submit(
                    connector.get_orderbook_top,
                    exchange=exchange,
                    market=args.market,
                ): exchange
                for exchange in due_exchanges
            }
            for future in as_completed(futures):
                exchange = futures[future]
                scheduler.mark_attempt(
                    exchange=exchange,
                    now_monotonic=time.monotonic(),
                )
                try:
                    latest_snapshots[exchange] = future.result()
                except MarketDataError as exc:
                    fetch_errors.append(
                        {
                            "exchange": exchange,
                            "code": exc.code,
                            "message": exc.message,
                        }
                    )
                    fetch_error_by_exchange[exchange] += 1
                    fetch_error_by_code[exc.code] += 1
                    continue
                refreshed_exchanges.add(exchange)
                refresh_count_by_exchange[exchange] += 1

        if fetch_errors and not refreshed_exchanges:
            LOGGER.warning(
                "simulation tick fully skipped due to market data errors: %s",
                fetch_errors,
                extra={"event_name": "arbitrage_sim_tick_skipped"},
            )
            iterations += 1
            next_tick_at += interval_seconds
            time.sleep(max(0.0, next_tick_at - time.monotonic()))
            continue

        with output_path.open("a", encoding="utf-8") as handle:
            for first_exchange, second_exchange in pairs:
                if first_exchange not in latest_snapshots or second_exchange not in latest_snapshots:
                    pair_skip_by_reason["missing_snapshot"] += 1
                    continue
                if (
                    first_exchange not in refreshed_exchanges
                    or second_exchange not in refreshed_exchanges
                ):
                    pair_skip_by_reason["awaiting_refresh"] += 1
                    continue
                pair_risk, _ = risk_with_pair_timing_gates(
                    risk=risk,
                    first_exchange=first_exchange,
                    second_exchange=second_exchange,
                    exchange_intervals=exchange_intervals,
                    timing_grace_ms=args.timing_grace_ms,
                    align_to_exchange_intervals=interval_gate_alignment_enabled,
                )
                forward, reverse = evaluate_directional_opportunities(
                    market=args.market,
                    canonical_symbol=args.canonical_symbol,
                    first_snapshot=latest_snapshots[first_exchange],
                    second_snapshot=latest_snapshots[second_exchange],
                    first_exchange=first_exchange,
                    second_exchange=second_exchange,
                    base_asset=args.base_asset,
                    quote_asset=args.quote_asset,
                    balances=balances,
                    risk=pair_risk,
                    now=current_time,
                )
                for observation in (forward, reverse):
                    tracker.record(observation)
                    handle.write(
                        json.dumps(observation.as_dict(), ensure_ascii=True) + "\n"
                    )
                    if observation.accepted:
                        LOGGER.info(
                            "sim opportunity accepted direction=%s market=%s profit_quote=%s profit_bps=%s",
                            observation.direction_key,
                            observation.market,
                            observation.executable_profit_quote,
                            observation.executable_profit_bps,
                            extra={"event_name": "arbitrage_sim_opportunity"},
                        )

        iterations += 1
        if args.summary_every > 0 and iterations % args.summary_every == 0:
            summary = _collect_tick_summary(
                tracker=tracker,
                refresh_count_by_exchange=refresh_count_by_exchange,
                fetch_error_by_exchange=fetch_error_by_exchange,
                fetch_error_by_code=fetch_error_by_code,
                pair_skip_by_reason=pair_skip_by_reason,
                exchange_intervals=exchange_intervals,
                pair_timing_gates=pair_timing_gates,
                interval_gate_alignment_enabled=interval_gate_alignment_enabled,
                timing_grace_ms=args.timing_grace_ms,
            )
            LOGGER.info(
                "simulation summary %s",
                json.dumps(summary, ensure_ascii=True),
                extra={"event_name": "arbitrage_sim_summary"},
            )
        next_tick_at += interval_seconds
        time.sleep(max(0.0, next_tick_at - time.monotonic()))

    summary = _collect_tick_summary(
        tracker=tracker,
        refresh_count_by_exchange=refresh_count_by_exchange,
        fetch_error_by_exchange=fetch_error_by_exchange,
        fetch_error_by_code=fetch_error_by_code,
        pair_skip_by_reason=pair_skip_by_reason,
        exchange_intervals=exchange_intervals,
        pair_timing_gates=pair_timing_gates,
        interval_gate_alignment_enabled=interval_gate_alignment_enabled,
        timing_grace_ms=args.timing_grace_ms,
    )
    LOGGER.info(
        "simulation observer finished %s",
        json.dumps(summary, ensure_ascii=True),
        extra={"event_name": "arbitrage_sim_observer_finished"},
    )
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
