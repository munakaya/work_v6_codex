from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from uuid import uuid4

from trading_platform.market_data_runtime import MarketDataRuntime
from trading_platform.observability import MetricsRegistry
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.route_handlers_market_read import ControlPlaneMarketReadRouteMixin
from trading_platform.request_utils import response_payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class MissingCacheConnector:
    def get_cached_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        return None


@dataclass(frozen=True)
class _FakeRedisInfo:
    enabled: bool = True


class _FakeRedisRuntime:
    def __init__(self) -> None:
        self.info = _FakeRedisInfo(enabled=True)

    def get_market_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        return None

    def list_market_orderbook_tops(
        self,
        *,
        exchange: str | None = None,
        market: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        return []


class _DummyHandler(ControlPlaneMarketReadRouteMixin):
    def __init__(self, server) -> None:
        self.server = server

    def _response(
        self,
        data: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return response_payload(
            request_id_factory=lambda: str(uuid4()),
            data=data,
            error=error,
        )


class _DummyServer:
    def __init__(self, runtime: MarketDataRuntime) -> None:
        self.market_data_runtime = runtime
        self.redis_runtime = _FakeRedisRuntime()


def _runtime(*, enabled: bool, exchange: str, markets: tuple[str, ...]) -> MarketDataRuntime:
    return MarketDataRuntime(
        enabled=enabled,
        exchange=exchange,
        markets=markets,
        interval_ms=1000,
        connector=MissingCacheConnector(),
        metrics=MetricsRegistry(),
        redis_runtime=RedisRuntime(None, "tp", "control-plane"),
        read_store=None,
    )


def _cached_error_code(runtime: MarketDataRuntime, *, exchange: str, market: str) -> str:
    handler = _DummyHandler(_DummyServer(runtime))
    status, payload = handler._cached_market_orderbook_top_response(
        f"exchange={exchange}&market={market}"
    )
    _assert(status == HTTPStatus.NOT_FOUND, f"cached response status mismatch: {status} payload={payload}")
    error_payload = payload.get("error") or {}
    return str(error_payload.get("code") or "")


def _case_runtime_info_coverage() -> None:
    runtime = _runtime(enabled=True, exchange="bithumb", markets=("KRW-BTC",))
    info = runtime.info
    _assert(info.coverage_state == "missing", f"coverage state mismatch: {info.coverage_state}")
    _assert(info.missing_snapshot_count == 1, f"missing snapshot count mismatch: {info.missing_snapshot_count}")
    _assert(
        info.target_coverage
        == [
            {
                "exchange": "bithumb",
                "target_market_count": 1,
                "cached_market_count": 0,
                "missing_markets": ["KRW-BTC"],
                "state": "missing",
            }
        ],
        f"target coverage mismatch: {info.target_coverage}",
    )


def _case_cached_snapshot_error_codes() -> None:
    disabled_runtime = _runtime(enabled=False, exchange="coinone", markets=("KRW-XRP",))
    pending_runtime = _runtime(enabled=True, exchange="unknown", markets=("KRW-XRP",))

    _assert(
        _cached_error_code(disabled_runtime, exchange="coinone", market="KRW-XRP")
        == "MARKET_SNAPSHOT_COLLECTOR_DISABLED",
        "collector disabled code mismatch",
    )
    _assert(
        _cached_error_code(pending_runtime, exchange="unknown", market="KRW-XRP")
        == "MARKET_SNAPSHOT_PENDING",
        "pending code mismatch",
    )
    _assert(
        _cached_error_code(disabled_runtime, exchange="bithumb", market="KRW-XRP")
        == "MARKET_SNAPSHOT_NOT_TARGETED",
        "not targeted code mismatch",
    )


def main() -> None:
    _case_runtime_info_coverage()
    _case_cached_snapshot_error_codes()
    print("PASS market data runtime exposes target coverage diagnostics")
    print("PASS cached market snapshot API distinguishes collector-disabled targets")
    print("PASS cached market snapshot API distinguishes pending and not-targeted markets")


if __name__ == "__main__":
    main()
