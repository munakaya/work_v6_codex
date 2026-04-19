from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from statistics import median
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.config import load_config
from trading_platform.logging_setup import configure_logging
from trading_platform.market_data_connector import PublicMarketDataConnector
from trading_platform.rate_limit import ExponentialBackoffPolicy, RateLimitPolicy


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
        description="Probe Coinone depth gaps versus project top-of-book parsing.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["APT", "ALGO", "AVAX"],
    )
    parser.add_argument("--quote-currency", default="KRW")
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--deep-ask-gap-pct", type=float, default=5.0)
    parser.add_argument("--best-ask-spike-pct", type=float, default=5.0)
    parser.add_argument("--best-ask-normal-pct", type=float, default=1.0)
    return parser.parse_args()


def _probe_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S%f")[:-3]
    output_dir = ROOT_DIR / ".tmp" / "coinone_depth_probe"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{timestamp}.jsonl"


def _json_request(url: str) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "work_v6_codex-depth-probe/0.1",
        },
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_coinone_depth(*, quote_currency: str, symbol: str, size: int = 16) -> dict[str, object]:
    url = "https://api.coinone.co.kr/public/v2/orderbook/%s/%s?%s" % (
        quote_currency,
        symbol,
        urlencode({"size": size}),
    )
    payload = _json_request(url)
    if not isinstance(payload, dict):
        raise ValueError("coinone depth payload shape is invalid")
    return payload


def _float_text(value: object) -> float:
    return float(str(value))


def _ladder_prices(entries: object, *, limit: int = 3) -> list[float]:
    if not isinstance(entries, list):
        return []
    prices: list[float] = []
    for item in entries[:limit]:
        if not isinstance(item, dict):
            continue
        try:
            prices.append(_float_text(item["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return prices


def _pct_delta(*, value: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return (value / baseline - 1.0) * 100.0


@dataclass
class SymbolStats:
    samples: int = 0
    errors: int = 0
    best_ask_spike_count: int = 0
    deep_ask_gap_only_count: int = 0
    max_best_ask_dev_pct: float = 0.0
    max_deep_ask_dev_pct: float = 0.0
    max_bid_dev_pct_abs: float = 0.0
    longest_same_ladder_run: int = 0
    _current_same_ladder_run: int = 0
    _last_ladder_key: tuple[float, ...] | None = None
    examples: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.examples is None:
            self.examples = []

    def record(self, event: dict[str, object]) -> None:
        self.samples += 1
        best_ask_dev_pct = float(event["coinone_best_ask_dev_pct"])
        deepest_dev_pct = float(event["coinone_deepest_gap_dev_pct"])
        bid_dev_pct = abs(float(event["coinone_best_bid_dev_pct"]))
        ladder_key = tuple(float(value) for value in event["coinone_top_asks"])
        if ladder_key == self._last_ladder_key:
            self._current_same_ladder_run += 1
        else:
            self._current_same_ladder_run = 1
            self._last_ladder_key = ladder_key
        self.longest_same_ladder_run = max(
            self.longest_same_ladder_run,
            self._current_same_ladder_run,
        )
        self.max_best_ask_dev_pct = max(self.max_best_ask_dev_pct, abs(best_ask_dev_pct))
        self.max_deep_ask_dev_pct = max(self.max_deep_ask_dev_pct, deepest_dev_pct)
        self.max_bid_dev_pct_abs = max(self.max_bid_dev_pct_abs, bid_dev_pct)
        classification = str(event["classification"])
        if classification == "best_ask_spike":
            self.best_ask_spike_count += 1
        if classification == "deep_ask_gap_only":
            self.deep_ask_gap_only_count += 1
        if classification != "normal" and len(self.examples or []) < 5:
            self.examples.append(event)

    def as_dict(self) -> dict[str, object]:
        return {
            "samples": self.samples,
            "errors": self.errors,
            "best_ask_spike_count": self.best_ask_spike_count,
            "deep_ask_gap_only_count": self.deep_ask_gap_only_count,
            "max_best_ask_dev_pct": round(self.max_best_ask_dev_pct, 3),
            "max_deep_ask_dev_pct": round(self.max_deep_ask_dev_pct, 3),
            "max_bid_dev_pct_abs": round(self.max_bid_dev_pct_abs, 3),
            "longest_same_ladder_run": self.longest_same_ladder_run,
            "examples": self.examples,
        }


def main() -> None:
    config = load_config()
    log_path = configure_logging(config)
    args = _parse_args()
    connector = _build_connector()
    output_path = _probe_output_path()
    stats_by_symbol = {
        symbol.upper(): SymbolStats()
        for symbol in args.symbols
    }
    error_codes: Counter[str] = Counter()
    started_at = time.monotonic()
    next_tick_at = started_at

    LOGGER.info(
        "starting coinone depth gap probe symbols=%s interval=%s duration=%s output=%s log=%s",
        ",".join(sorted(stats_by_symbol.keys())),
        args.interval_seconds,
        args.duration_seconds,
        output_path,
        log_path,
        extra={"event_name": "coinone_depth_probe_started"},
    )

    with output_path.open("a", encoding="utf-8") as handle:
        while (time.monotonic() - started_at) < max(args.duration_seconds, 1):
            tick_started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            for symbol, stats in stats_by_symbol.items():
                market = f"{args.quote_currency.upper()}-{symbol}"
                try:
                    upbit = connector.get_orderbook_top(exchange="upbit", market=market)
                    bithumb = connector.get_orderbook_top(exchange="bithumb", market=market)
                    coinone = connector.get_orderbook_top(exchange="coinone", market=market)
                    coinone_depth = _fetch_coinone_depth(
                        quote_currency=args.quote_currency.upper(),
                        symbol=symbol,
                        size=16,
                    )
                except Exception as exc:
                    stats.errors += 1
                    error_codes[type(exc).__name__] += 1
                    LOGGER.warning(
                        "depth probe fetch failed symbol=%s error=%s",
                        symbol,
                        exc,
                        extra={"event_name": "coinone_depth_probe_fetch_failed"},
                    )
                    continue

                normal_bid = median(
                    [
                        _float_text(upbit["best_bid"]),
                        _float_text(bithumb["best_bid"]),
                    ]
                )
                normal_ask = median(
                    [
                        _float_text(upbit["best_ask"]),
                        _float_text(bithumb["best_ask"]),
                    ]
                )
                top_bids = _ladder_prices(coinone_depth.get("bids"))
                top_asks = _ladder_prices(coinone_depth.get("asks"))
                coinone_best_bid = _float_text(coinone["best_bid"])
                coinone_best_ask = _float_text(coinone["best_ask"])
                best_ask_dev_pct = _pct_delta(
                    value=coinone_best_ask,
                    baseline=normal_ask,
                )
                bid_dev_pct = _pct_delta(
                    value=coinone_best_bid,
                    baseline=normal_bid,
                )
                deeper_devs = [
                    _pct_delta(value=ask_price, baseline=normal_ask)
                    for ask_price in top_asks[1:]
                ]
                deepest_gap_dev_pct = max(deeper_devs) if deeper_devs else 0.0
                classification = "normal"
                if abs(best_ask_dev_pct) >= args.best_ask_spike_pct:
                    classification = "best_ask_spike"
                elif (
                    abs(best_ask_dev_pct) <= args.best_ask_normal_pct
                    and deepest_gap_dev_pct >= args.deep_ask_gap_pct
                ):
                    classification = "deep_ask_gap_only"
                event = {
                    "observed_at": tick_started_at,
                    "symbol": symbol,
                    "market": market,
                    "classification": classification,
                    "normal_bid": normal_bid,
                    "normal_ask": normal_ask,
                    "upbit_best_bid": _float_text(upbit["best_bid"]),
                    "upbit_best_ask": _float_text(upbit["best_ask"]),
                    "bithumb_best_bid": _float_text(bithumb["best_bid"]),
                    "bithumb_best_ask": _float_text(bithumb["best_ask"]),
                    "coinone_best_bid": coinone_best_bid,
                    "coinone_best_ask": coinone_best_ask,
                    "coinone_best_bid_dev_pct": round(bid_dev_pct, 3),
                    "coinone_best_ask_dev_pct": round(best_ask_dev_pct, 3),
                    "coinone_deepest_gap_dev_pct": round(deepest_gap_dev_pct, 3),
                    "coinone_top_bids": top_bids,
                    "coinone_top_asks": top_asks,
                    "coinone_timestamp_ms": coinone_depth.get("timestamp"),
                    "coinone_orderbook_id": coinone_depth.get("id"),
                }
                stats.record(event)
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")

            next_tick_at += max(args.interval_seconds, 0.1)
            time.sleep(max(0.0, next_tick_at - time.monotonic()))

    summary = {
        "symbols": {
            symbol: stats.as_dict()
            for symbol, stats in sorted(stats_by_symbol.items())
        },
        "error_code_breakdown": {
            code: count for code, count in sorted(error_codes.items())
        },
        "output_path": str(output_path),
        "log_path": str(log_path),
    }
    LOGGER.info(
        "coinone depth gap probe finished %s",
        json.dumps(summary, ensure_ascii=True),
        extra={"event_name": "coinone_depth_probe_finished"},
    )
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
