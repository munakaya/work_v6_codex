from __future__ import annotations

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.observer_request_stats import RequestStatsTracker


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    tracker = RequestStatsTracker()
    tracker.record_success(exchange="upbit", latency_ms=10)
    tracker.record_success(exchange="upbit", latency_ms=30)
    tracker.record_error(exchange="upbit", code="UPSTREAM_RATE_LIMITED", latency_ms=50)
    tracker.record_success(exchange="coinone", latency_ms=20)
    snapshot = tracker.snapshot()

    total = snapshot["total"]
    by_exchange = snapshot["by_exchange"]

    _assert(total["attempt_count"] == 4, "total attempt count mismatch")
    _assert(total["success_count"] == 3, "total success count mismatch")
    _assert(total["error_count"] == 1, "total error count mismatch")
    _assert(total["success_rate"] == 0.75, "total success rate mismatch")
    _assert(total["error_rate"] == 0.25, "total error rate mismatch")
    _assert(total["latency_ms"]["p50"] == 25.0, "total p50 mismatch")
    _assert(total["latency_ms"]["p95"] == 47.0, "total p95 mismatch")
    _assert(total["latency_ms"]["over_100ms"] == 0, "total over_100ms mismatch")
    _assert(
        total["error_code_breakdown"] == {"UPSTREAM_RATE_LIMITED": 1},
        "total error breakdown mismatch",
    )

    upbit = by_exchange["upbit"]
    _assert(upbit["attempt_count"] == 3, "upbit attempt count mismatch")
    _assert(upbit["success_count"] == 2, "upbit success count mismatch")
    _assert(upbit["error_count"] == 1, "upbit error count mismatch")
    _assert(upbit["latency_ms"]["max"] == 50.0, "upbit latency max mismatch")
    _assert(
        upbit["success_latency_ms"]["p50"] == 20.0,
        "upbit success latency p50 mismatch",
    )
    _assert(
        upbit["error_latency_ms"]["p50"] == 50.0,
        "upbit error latency p50 mismatch",
    )

    coinone = by_exchange["coinone"]
    _assert(coinone["attempt_count"] == 1, "coinone attempt count mismatch")
    _assert(coinone["error_count"] == 0, "coinone error count mismatch")
    _assert(
        coinone["success_latency_ms"]["avg"] == 20.0,
        "coinone success latency avg mismatch",
    )
    print("PASS observer request stats tracker aggregates latency and error ratios")


if __name__ == "__main__":
    main()
