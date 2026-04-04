from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs

from .market_data_connector import MarketDataError
from .request_utils import single_query_value


class ControlPlaneMarketReadRouteMixin:
    def _market_orderbook_top_response(
        self, query: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
        params = parse_qs(query)
        exchange = single_query_value(params, "exchange")
        market = single_query_value(params, "market")
        try:
            snapshot = self.server.market_data_connector.get_orderbook_top(
                exchange=exchange or "",
                market=market or "",
            )
        except MarketDataError as exc:
            return (
                exc.status,
                self._response(error={"code": exc.code, "message": exc.message}),
            )
        self.server.metrics.observe_orderbook_snapshot(
            exchange=str(snapshot["exchange"]),
            market=str(snapshot["market"]),
            age_ms=int(snapshot["exchange_age_ms"]),
            stale=bool(snapshot["stale"]),
        )
        self._sync_market_orderbook_top(snapshot)
        return HTTPStatus.OK, self._response(data=snapshot)

    def _cached_market_orderbook_top_response(
        self, query: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
        params = parse_qs(query)
        exchange = (single_query_value(params, "exchange") or "").strip().lower()
        market = (single_query_value(params, "market") or "").strip().upper()
        if not exchange:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={"code": "INVALID_REQUEST", "message": "exchange is required"}
                ),
            )
        if not market:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={"code": "INVALID_REQUEST", "message": "market is required"}
                ),
            )
        if not self.server.redis_runtime.info.enabled:
            return (
                HTTPStatus.SERVICE_UNAVAILABLE,
                self._response(
                    error={
                        "code": "REDIS_RUNTIME_UNAVAILABLE",
                        "message": "redis runtime is not enabled",
                    }
                ),
            )
        payload = self.server.redis_runtime.get_market_orderbook_top(
            exchange=exchange,
            market=market,
        )
        if payload is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "MARKET_SNAPSHOT_NOT_FOUND",
                        "message": "cached market snapshot not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=payload)

    def _market_runtime_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        runtime = self.server.market_data_runtime.info
        snapshots: list[dict[str, object]] = []
        if self.server.redis_runtime.info.enabled and runtime.exchange:
            for market in runtime.markets:
                snapshot = self.server.redis_runtime.get_market_orderbook_top(
                    exchange=runtime.exchange,
                    market=market,
                )
                if snapshot is not None:
                    snapshots.append(snapshot)
        return HTTPStatus.OK, self._response(
            data={
                "runtime": runtime.as_dict(),
                "redis_runtime": self.server.redis_runtime.info.as_dict(),
                "snapshots": snapshots,
                "snapshot_count": len(snapshots),
            }
        )
