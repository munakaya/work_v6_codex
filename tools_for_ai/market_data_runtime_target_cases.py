from __future__ import annotations

from trading_platform.market_data_runtime import MarketDataRuntime
from trading_platform.observability import MetricsRegistry
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store


class RecordingConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        self.calls.append((exchange, market))
        return {
            "exchange": exchange,
            "market": market,
            "best_bid": "100",
            "best_ask": "101",
            "bid_volume": "1",
            "ask_volume": "1",
            "bids": [{"price": "100", "quantity": "1"}],
            "asks": [{"price": "101", "quantity": "1"}],
            "depth_level_count": 1,
            "exchange_timestamp": "2026-04-19T00:00:00Z",
            "received_at": "2026-04-19T00:00:00Z",
            "exchange_age_ms": 0,
            "stale": False,
            "source_type": "test",
        }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    connector = RecordingConnector()
    runtime = MarketDataRuntime(
        enabled=True,
        exchange="coinone",
        markets=("KRW-XRP",),
        interval_ms=1000,
        connector=connector,
        metrics=MetricsRegistry(),
        redis_runtime=RedisRuntime(None, "tp", "control-plane"),
        read_store=sample_read_store(),
    )

    info = runtime.info
    groups = {
        item["exchange"]: tuple(item["markets"])
        for item in info.target_groups
    }
    _assert(groups["coinone"] == ("KRW-XRP",), "configured target group mismatch")
    _assert(groups["sample"] == ("KRW-BTC", "KRW-ETH"), "sample exchange targets mismatch")
    _assert(groups["upbit"] == ("KRW-BTC", "KRW-ETH"), "upbit strategy targets mismatch")
    _assert(info.target_count == 5, "target count mismatch")

    runtime._poll_once()
    _assert(
        connector.calls == [
            ("coinone", "KRW-XRP"),
            ("sample", "KRW-BTC"),
            ("sample", "KRW-ETH"),
            ("upbit", "KRW-BTC"),
            ("upbit", "KRW-ETH"),
        ],
        f"unexpected poll order: {connector.calls}",
    )
    print("PASS market data runtime merges configured and running arbitrage targets")
    print("PASS market data runtime polls derived targets without duplicate REST loops")


if __name__ == "__main__":
    main()
