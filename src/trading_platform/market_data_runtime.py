from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import threading
from typing import Sequence

from .market_data_connector import MarketDataError, PublicMarketDataConnector
from .observability import MetricsRegistry
from .redis_runtime import RedisRuntime
from .storage.store_protocol import ControlPlaneStoreProtocol


LOGGER = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketDataRuntimeInfo:
    enabled: bool
    exchange: str
    markets: list[str]
    target_count: int
    target_groups: list[dict[str, object]]
    interval_ms: int
    running: bool
    state: str
    last_success_at: str | None
    last_error_at: str | None
    last_error_message: str | None
    success_count: int
    failure_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "exchange": self.exchange,
            "markets": self.markets,
            "target_count": self.target_count,
            "target_groups": self.target_groups,
            "interval_ms": self.interval_ms,
            "running": self.running,
            "state": self.state,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error_message": self.last_error_message,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


class MarketDataRuntime:
    def __init__(
        self,
        *,
        enabled: bool,
        exchange: str,
        markets: Sequence[str],
        interval_ms: int,
        connector: PublicMarketDataConnector,
        metrics: MetricsRegistry,
        redis_runtime: RedisRuntime,
        read_store: ControlPlaneStoreProtocol | None = None,
    ) -> None:
        self.enabled = enabled
        self.exchange = exchange.strip().lower()
        self.markets = tuple(m.strip().upper() for m in markets if m.strip())
        self.interval_ms = max(interval_ms, 250)
        self.connector = connector
        self.metrics = metrics
        self.redis_runtime = redis_runtime
        self.read_store = read_store
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._last_error_message: str | None = None
        self._success_count = 0
        self._failure_count = 0

    @property
    def info(self) -> MarketDataRuntimeInfo:
        target_groups = self._target_groups()
        target_count = sum(len(markets) for _, markets in target_groups)
        with self._lock:
            return MarketDataRuntimeInfo(
                enabled=self.enabled,
                exchange=self.exchange,
                markets=list(self.markets),
                target_count=target_count,
                target_groups=[
                    {"exchange": exchange, "markets": list(markets)}
                    for exchange, markets in target_groups
                ],
                interval_ms=self.interval_ms,
                running=self._running,
                state=self._state_name(),
                last_success_at=self._last_success_at,
                last_error_at=self._last_error_at,
                last_error_message=self._last_error_message,
                success_count=self._success_count,
                failure_count=self._failure_count,
            )

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="market-data-poller",
            daemon=True,
        )
        with self._lock:
            self._running = True
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(self.interval_ms / 1000, 1.0) + 1.0)
        with self._lock:
            self._running = False
        self._thread = None

    def _state_name(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._running:
            return "running"
        if not self._target_groups():
            return "invalid_config"
        if self._failure_count > 0 and self._success_count == 0:
            return "degraded"
        return "idle"

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._poll_once()
                if self._stop_event.wait(self.interval_ms / 1000):
                    break
        finally:
            with self._lock:
                self._running = False

    def refresh(
        self,
        *,
        exchange: str,
        markets: Sequence[str],
        trace_id: str | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        normalized_exchange = exchange.strip().lower()
        normalized_markets = [market.strip().upper() for market in markets if market.strip()]
        snapshots: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        for market in normalized_markets:
            if self._stop_event.is_set():
                break
            try:
                snapshot = self.connector.get_orderbook_top(
                    exchange=normalized_exchange,
                    market=market,
                )
            except MarketDataError as exc:
                self._record_failure(exchange=normalized_exchange, market=market, exc=exc)
                errors.append(
                    {
                        "market": market,
                        "code": exc.code,
                        "message": exc.message,
                        "status": exc.status.value,
                    }
                )
                continue
            self._record_snapshot(snapshot, trace_id=trace_id)
            snapshots.append(snapshot)
        return snapshots, errors

    def _target_groups(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        grouped: dict[str, set[str]] = {}
        if self.exchange and self.markets:
            grouped.setdefault(self.exchange, set()).update(self.markets)
        if self.read_store is not None:
            for exchange, market in self._strategy_targets():
                grouped.setdefault(exchange, set()).add(market)
        return tuple(
            (exchange, tuple(sorted(markets)))
            for exchange, markets in sorted(grouped.items())
            if exchange and markets
        )

    def _strategy_targets(self) -> tuple[tuple[str, str], ...]:
        if self.read_store is None:
            return ()
        targets: set[tuple[str, str]] = set()
        config_cache: dict[tuple[str, int], dict[str, object] | None] = {}
        runs = self.read_store.list_strategy_runs(status="running")
        for run in runs:
            if str(run.get("strategy_name") or "").strip().lower() != "arbitrage":
                continue
            bot_id = str(run.get("bot_id") or "").strip()
            if not bot_id:
                continue
            bot_detail = self.read_store.get_bot_detail(bot_id)
            if not isinstance(bot_detail, dict):
                continue
            assigned = bot_detail.get("assigned_config_version")
            if not isinstance(assigned, dict):
                continue
            config_scope = str(assigned.get("config_scope") or "").strip()
            version_raw = assigned.get("version_no")
            if not config_scope or version_raw is None:
                continue
            try:
                version_no = int(version_raw)
            except (TypeError, ValueError):
                continue
            cache_key = (config_scope, version_no)
            if cache_key not in config_cache:
                config_cache[cache_key] = next(
                    (
                        item
                        for item in self.read_store.list_config_versions(config_scope)
                        if int(item.get("version_no") or -1) == version_no
                    ),
                    None,
                )
            version = config_cache[cache_key]
            if not isinstance(version, dict):
                continue
            config_json = version.get("config_json")
            if not isinstance(config_json, dict):
                continue
            runtime_spec = config_json.get("arbitrage_runtime")
            if not isinstance(runtime_spec, dict):
                continue
            market = str(runtime_spec.get("market") or "").strip().upper()
            if not market:
                continue
            for exchange_key in ("base_exchange", "hedge_exchange"):
                exchange = str(runtime_spec.get(exchange_key) or "").strip().lower()
                if exchange:
                    targets.add((exchange, market))
        return tuple(sorted(targets))

    def _poll_once(self) -> None:
        for exchange, markets in self._target_groups():
            if self._stop_event.is_set():
                break
            self.refresh(exchange=exchange, markets=markets)

    def _record_snapshot(
        self, snapshot: dict[str, object], *, trace_id: str | None = None
    ) -> None:
        self.metrics.observe_orderbook_snapshot(
            exchange=str(snapshot["exchange"]),
            market=str(snapshot["market"]),
            age_ms=int(snapshot["exchange_age_ms"]),
            stale=bool(snapshot["stale"]),
        )
        self.redis_runtime.sync_market_orderbook_top(
            exchange=str(snapshot["exchange"]),
            market=str(snapshot["market"]),
            payload=snapshot,
            trace_id=trace_id,
        )
        with self._lock:
            self._success_count += 1
            self._last_success_at = _iso_now()
            self._last_error_message = None

    def _record_failure(
        self, *, exchange: str, market: str, exc: MarketDataError
    ) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_error_at = _iso_now()
            self._last_error_message = exc.message
        LOGGER.warning(
            "market data poll failed: exchange=%s market=%s code=%s message=%s",
            exchange,
            market,
            exc.code,
            exc.message,
            extra={
                "event_name": "market_data_poll_failed",
            },
        )
