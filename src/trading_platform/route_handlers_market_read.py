from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs

from .market_data_connector import MarketDataError
from .request_utils import query_limit, single_query_value


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
        snapshots = self._list_market_snapshots(
            exchange=runtime.exchange or None,
            limit=max(len(runtime.markets), 1),
        )
        return HTTPStatus.OK, self._response(
            data={
                "runtime": runtime.as_dict(),
                "redis_runtime": self.server.redis_runtime.info.as_dict(),
                "rate_limits": self.server.market_data_connector.describe_rate_limits(),
                "snapshots": snapshots,
                "snapshot_count": len(snapshots),
            }
        )

    def _market_snapshots_response(
        self, query: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
        params = parse_qs(query)
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
        snapshots = self.server.redis_runtime.list_market_orderbook_tops(
            exchange=single_query_value(params, "exchange"),
            market=single_query_value(params, "market"),
            limit=query_limit(params),
        )
        if snapshots is None:
            return (
                HTTPStatus.BAD_GATEWAY,
                self._response(
                    error={
                        "code": "REDIS_RUNTIME_READ_FAILED",
                        "message": "failed to read cached market snapshots",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(
            data={"items": snapshots, "count": len(snapshots)}
        )

    def _list_market_snapshots(
        self,
        *,
        exchange: str | None = None,
        market: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        if not self.server.redis_runtime.info.enabled:
            return []
        snapshots = self.server.redis_runtime.list_market_orderbook_tops(
            exchange=exchange,
            market=market,
            limit=limit,
        )
        if snapshots is None:
            return []
        return snapshots
