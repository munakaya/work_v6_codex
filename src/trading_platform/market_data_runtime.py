from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import threading
from typing import Sequence

from .market_data_connector import MarketDataError, PublicMarketDataConnector
from .observability import MetricsRegistry
from .redis_runtime import RedisRuntime


LOGGER = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketDataRuntimeInfo:
    enabled: bool
    exchange: str
    markets: list[str]
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
    ) -> None:
        self.enabled = enabled
        self.exchange = exchange.strip().lower()
        self.markets = tuple(m.strip().upper() for m in markets if m.strip())
        self.interval_ms = max(interval_ms, 250)
        self.connector = connector
        self.metrics = metrics
        self.redis_runtime = redis_runtime
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
        with self._lock:
            return MarketDataRuntimeInfo(
                enabled=self.enabled,
                exchange=self.exchange,
                markets=list(self.markets),
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
        if not self.enabled or not self.markets or self._thread is not None:
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
        if not self.markets:
            return "invalid_config"
        if self._running:
            return "running"
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

    def _poll_once(self) -> None:
        for market in self.markets:
            if self._stop_event.is_set():
                break
            try:
                snapshot = self.connector.get_orderbook_top(
                    exchange=self.exchange,
                    market=market,
                )
            except MarketDataError as exc:
                self._record_failure(market, exc)
                continue
            self._record_snapshot(snapshot)

    def _record_snapshot(self, snapshot: dict[str, object]) -> None:
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
        )
        with self._lock:
            self._success_count += 1
            self._last_success_at = _iso_now()
            self._last_error_message = None

    def _record_failure(self, market: str, exc: MarketDataError) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_error_at = _iso_now()
            self._last_error_message = exc.message
        LOGGER.warning(
            "market data poll failed: exchange=%s market=%s code=%s message=%s",
            self.exchange,
            market,
            exc.code,
            exc.message,
            extra={
                "event_name": "market_data_poll_failed",
            },
        )
