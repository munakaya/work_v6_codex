from __future__ import annotations

from dataclasses import dataclass
import logging

from .market_data_connector import MarketDataError, PublicMarketDataConnector
from .market_data_freshness import snapshot_sort_datetime
from .public_ws_market_data import PublicWebSocketMarketDataConnector


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeMarketDataSourcePolicy:
    exchange: str
    preferred_source: str
    fallback_source: str | None
    ws_supported: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "preferred_source": self.preferred_source,
            "fallback_source": self.fallback_source,
            "ws_supported": self.ws_supported,
            "policy_name": "ws_first" if self.ws_supported else "rest_only",
        }


class RuntimeMarketDataConnector:
    def __init__(
        self,
        *,
        rest_connector: PublicMarketDataConnector,
        ws_connector: PublicWebSocketMarketDataConnector,
    ) -> None:
        self.rest_connector = rest_connector
        self.ws_connector = ws_connector

    @property
    def supported_ws_exchanges(self) -> tuple[str, ...]:
        supported = getattr(self.ws_connector, "supported_ws_exchanges", ())
        return tuple(str(item).strip().lower() for item in supported if str(item).strip())

    def source_policy(self, *, exchange: str) -> RuntimeMarketDataSourcePolicy:
        normalized_exchange = exchange.strip().lower()
        ws_supported = normalized_exchange in self.supported_ws_exchanges
        return RuntimeMarketDataSourcePolicy(
            exchange=normalized_exchange,
            preferred_source="public_ws" if ws_supported else "rest",
            fallback_source="rest" if ws_supported else None,
            ws_supported=ws_supported,
        )

    def describe_source_policies(
        self, *, exchanges: tuple[str, ...] | list[str] | None = None
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        for exchange in exchanges or self.supported_ws_exchanges:
            normalized_exchange = str(exchange).strip().lower()
            if not normalized_exchange or normalized_exchange in seen:
                continue
            seen.add(normalized_exchange)
            items.append(self.source_policy(exchange=normalized_exchange).as_dict())
        return items

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        normalized_exchange = exchange.strip().lower()
        policy = self.source_policy(exchange=normalized_exchange)
        if policy.ws_supported:
            try:
                snapshot = self.ws_connector.get_orderbook_top(exchange=exchange, market=market)
                return self._annotate_snapshot(snapshot=snapshot, policy=policy, fallback_used=False)
            except MarketDataError as exc:
                LOGGER.warning(
                    "market data websocket fetch failed, using REST fallback: exchange=%s market=%s code=%s message=%s",
                    normalized_exchange,
                    market,
                    exc.code,
                    exc.message,
                    extra={"event_name": "market_data_ws_fallback"},
                )
                snapshot = self.rest_connector.get_orderbook_top(exchange=exchange, market=market)
                return self._annotate_snapshot(
                    snapshot=snapshot,
                    policy=policy,
                    fallback_used=True,
                    fallback_reason=exc.code,
                    fallback_message=exc.message,
                )
        snapshot = self.rest_connector.get_orderbook_top(exchange=exchange, market=market)
        return self._annotate_snapshot(snapshot=snapshot, policy=policy, fallback_used=False)

    def get_cached_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        left = self.rest_connector.get_cached_orderbook_top(exchange=exchange, market=market)
        right = self.ws_connector.get_cached_orderbook_top(exchange=exchange, market=market)
        if left is None:
            return right
        if right is None:
            return left
        left_dt = snapshot_sort_datetime(left)
        right_dt = snapshot_sort_datetime(right)
        if left_dt is None:
            return right
        if right_dt is None:
            return left
        return left if left_dt >= right_dt else right

    def sync_cached_orderbook_top(self, *, snapshot: dict[str, object]) -> None:
        self.rest_connector.sync_cached_orderbook_top(snapshot=snapshot)
        self.ws_connector.sync_cached_orderbook_top(snapshot=snapshot)

    def _annotate_snapshot(
        self,
        *,
        snapshot: dict[str, object],
        policy: RuntimeMarketDataSourcePolicy,
        fallback_used: bool,
        fallback_reason: str | None = None,
        fallback_message: str | None = None,
    ) -> dict[str, object]:
        annotated = dict(snapshot)
        annotated["collector_policy_name"] = "ws_first" if policy.ws_supported else "rest_only"
        annotated["collector_preferred_source"] = policy.preferred_source
        annotated["collector_fallback_source"] = policy.fallback_source
        annotated["collector_fallback_used"] = fallback_used
        if fallback_reason:
            annotated["collector_fallback_reason"] = fallback_reason
        if fallback_message:
            annotated["collector_fallback_message"] = fallback_message
        self.sync_cached_orderbook_top(snapshot=annotated)
        return annotated

    def describe_rate_limits(self) -> dict[str, object]:
        return self.rest_connector.describe_rate_limits()
