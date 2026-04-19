from __future__ import annotations

from datetime import UTC, datetime

from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy.arbitrage_runtime_loader import load_arbitrage_runtime_payload


class _RedisInfo:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled


class FakeRedisRuntime:
    def __init__(self, *, enabled: bool = True) -> None:
        self.info = _RedisInfo(enabled=enabled)
        self.snapshots: dict[tuple[str, str], dict[str, object]] = {}

    def get_market_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        snapshot = self.snapshots.get((exchange.strip().lower(), market.strip().upper()))
        if snapshot is None:
            return None
        return dict(snapshot)


class CachedOnlyConnector:
    def __init__(self) -> None:
        self.direct_fetch_count = 0
        self.cached_fetch_count = 0
        self.snapshots: dict[tuple[str, str], dict[str, object]] = {}

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        self.direct_fetch_count += 1
        raise AssertionError("direct REST fetch must not be used by runtime loader")

    def get_cached_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        self.cached_fetch_count += 1
        snapshot = self.snapshots.get((exchange.strip().lower(), market.strip().upper()))
        if snapshot is None:
            return None
        return dict(snapshot)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _running_run() -> tuple[object, dict[str, object], dict[str, object]]:
    store = sample_read_store()
    run = next(item for item in store.list_strategy_runs(status="running") if str(item.get("strategy_name") or "") == "arbitrage")
    bot_detail = store.get_bot_detail(str(run["bot_id"]))
    _assert(bot_detail is not None, "bot detail missing")
    assigned = bot_detail.get("assigned_config_version")
    _assert(isinstance(assigned, dict), "assigned config missing")
    version_no = int(assigned["version_no"])
    config_scope = str(assigned["config_scope"])
    version = next(item for item in store.list_config_versions(config_scope) if int(item.get("version_no") or -1) == version_no)
    runtime_spec = dict(version["config_json"]["arbitrage_runtime"])
    return store, run, runtime_spec


def _snapshot(*, exchange: str, market: str, received_at: str | None = None) -> dict[str, object]:
    now = received_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "exchange": exchange,
        "market": market,
        "best_bid": "101574000",
        "best_ask": "101598000",
        "bid_volume": "0.3",
        "ask_volume": "0.4",
        "bids": [{"price": "101574000", "quantity": "0.3"}],
        "asks": [{"price": "101598000", "quantity": "0.4"}],
        "depth_level_count": 1,
        "exchange_timestamp": now,
        "received_at": now,
        "exchange_age_ms": 0,
        "stale": False,
        "source_type": "cached",
    }


def main() -> None:
    store, run, runtime_spec = _running_run()
    market = str(runtime_spec["market"])
    base_exchange = str(runtime_spec["base_exchange"])
    hedge_exchange = str(runtime_spec["hedge_exchange"])

    connector = CachedOnlyConnector()
    connector.snapshots[(base_exchange, market)] = _snapshot(exchange=base_exchange, market=market)
    connector.snapshots[(hedge_exchange, market)] = _snapshot(exchange=hedge_exchange, market=market)

    result = load_arbitrage_runtime_payload(
        store=store,
        connector=connector,
        run=run,
        redis_runtime=None,
    )
    _assert(result.payload is not None, "runtime loader should accept cached snapshots")
    _assert(connector.direct_fetch_count == 0, "direct fetch must not be called when cache exists")
    _assert(connector.cached_fetch_count == 2, "runtime loader should read two cached snapshots")
    _assert(result.payload["base_orderbook"]["market"] == market, "base snapshot market mismatch")
    _assert(result.payload["hedge_orderbook"]["market"] == market, "hedge snapshot market mismatch")

    fresher_redis = FakeRedisRuntime(enabled=True)
    stale_received_at = "2026-04-19T11:00:00Z"
    fresh_received_at = "2026-04-19T11:00:05Z"
    connector.snapshots[(base_exchange, market)] = _snapshot(
        exchange=base_exchange,
        market=market,
        received_at=stale_received_at,
    )
    fresher_redis.snapshots[(base_exchange, market)] = _snapshot(
        exchange=base_exchange,
        market=market,
        received_at=fresh_received_at,
    )
    fresher_redis.snapshots[(hedge_exchange, market)] = _snapshot(
        exchange=hedge_exchange,
        market=market,
        received_at=fresh_received_at,
    )
    fresher = load_arbitrage_runtime_payload(
        store=store,
        connector=connector,
        run=run,
        redis_runtime=fresher_redis,
    )
    _assert(fresher.payload is not None, "redis fallback should provide fresher snapshot")
    _assert(
        fresher.payload["base_orderbook"]["observed_at"] == fresh_received_at,
        "runtime loader should prefer fresher redis snapshot over stale connector cache",
    )

    empty_connector = CachedOnlyConnector()
    missing = load_arbitrage_runtime_payload(
        store=store,
        connector=empty_connector,
        run=run,
        redis_runtime=None,
    )
    _assert(missing.payload is None, "missing cache should skip evaluation")
    _assert(missing.skip_reason == "MARKET_SNAPSHOT_NOT_FOUND", "missing cache skip reason mismatch")
    _assert(empty_connector.direct_fetch_count == 0, "missing cache must not trigger direct fetch")

    print("PASS runtime loader uses cached orderbook snapshots without direct REST fetch")
    print("PASS runtime loader prefers fresher redis snapshot over stale connector cache")
    print("PASS runtime loader fails closed when cached snapshots are missing")


if __name__ == "__main__":
    main()
