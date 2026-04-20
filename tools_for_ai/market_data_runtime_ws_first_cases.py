from __future__ import annotations

from http import HTTPStatus

from trading_platform.market_data_connector import MarketDataError
from trading_platform.market_data_runtime import MarketDataRuntime
from trading_platform.observability import MetricsRegistry
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.runtime_market_data_connector import RuntimeMarketDataConnector
from trading_platform.storage.store_factory import sample_read_store


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _snapshot(*, exchange: str, market: str, source_type: str) -> dict[str, object]:
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
        "exchange_timestamp": "2026-04-20T00:00:00Z",
        "received_at": "2026-04-20T00:00:00Z",
        "exchange_age_ms": 0,
        "stale": False,
        "source_type": source_type,
        "freshness_observed_at": "2026-04-20T00:00:00Z",
        "freshness_observed_at_source": "received_at" if source_type == "public_ws" else "exchange_timestamp",
    }


class RecordingRestConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.cached: dict[tuple[str, str], dict[str, object]] = {}

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        self.calls.append((exchange, market))
        snapshot = _snapshot(exchange=exchange, market=market, source_type="rest")
        self.sync_cached_orderbook_top(snapshot=snapshot)
        return snapshot

    def get_cached_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        return self.cached.get((exchange, market))

    def sync_cached_orderbook_top(self, *, snapshot: dict[str, object]) -> None:
        key = (str(snapshot["exchange"]), str(snapshot["market"]))
        self.cached[key] = dict(snapshot)

    def describe_rate_limits(self) -> dict[str, object]:
        return {"items": []}


class RecordingWsConnector(RecordingRestConnector):
    @property
    def supported_ws_exchanges(self) -> tuple[str, ...]:
        return ("upbit", "coinone")

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        self.calls.append((exchange, market))
        if exchange == "coinone":
            raise MarketDataError(
                status=HTTPStatus.BAD_GATEWAY,
                code="WS_TIMEOUT",
                message="coinone websocket timed out",
            )
        snapshot = _snapshot(exchange=exchange, market=market, source_type="public_ws")
        self.sync_cached_orderbook_top(snapshot=snapshot)
        return snapshot


def main() -> None:
    rest_connector = RecordingRestConnector()
    ws_connector = RecordingWsConnector()
    runtime = MarketDataRuntime(
        enabled=True,
        exchange="coinone",
        markets=("KRW-XRP",),
        interval_ms=1000,
        connector=RuntimeMarketDataConnector(
            rest_connector=rest_connector,
            ws_connector=ws_connector,
        ),
        metrics=MetricsRegistry(),
        redis_runtime=RedisRuntime(None, "tp", "control-plane"),
        read_store=sample_read_store(),
    )

    runtime._poll_once()
    info = runtime.info
    policies = {item["exchange"]: item for item in info.source_policies}
    statuses = {item["exchange"]: item for item in info.source_statuses}

    _assert(policies["upbit"]["preferred_source"] == "public_ws", "upbit policy mismatch")
    _assert(policies["coinone"]["preferred_source"] == "public_ws", "coinone policy mismatch")
    _assert(policies["sample"]["preferred_source"] == "rest", "sample policy mismatch")

    _assert(statuses["upbit"]["last_source"] == "public_ws", "upbit should use websocket")
    _assert(statuses["coinone"]["last_source"] == "rest", "coinone should fall back to rest")
    _assert(statuses["coinone"]["fallback_active"] is True, "coinone fallback should be active")
    _assert(statuses["coinone"]["fallback_count"] == 1, "coinone fallback count mismatch")
    _assert(statuses["coinone"]["last_fallback_reason"] == "WS_TIMEOUT", "coinone fallback reason mismatch")
    _assert(statuses["sample"]["state"] == "rest_only", "sample should remain rest only")
    _assert(info.fallback_active is True, "runtime fallback flag mismatch")
    _assert(info.state == "fallback_active", f"runtime state mismatch: {info.state}")

    _assert(("coinone", "KRW-XRP") in ws_connector.calls, "coinone ws call missing")
    _assert(("coinone", "KRW-XRP") in rest_connector.calls, "coinone rest fallback call missing")
    _assert(("upbit", "KRW-BTC") in ws_connector.calls, "upbit ws call missing")
    _assert(("sample", "KRW-BTC") in rest_connector.calls, "sample rest call missing")

    print("PASS market data runtime uses websocket first for supported exchanges")
    print("PASS market data runtime falls back to rest and exposes fallback diagnostics")
    print("PASS market data runtime keeps unsupported exchanges on rest-only policy")


if __name__ == "__main__":
    main()
