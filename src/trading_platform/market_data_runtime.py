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
    source_policies: list[dict[str, object]]
    source_statuses: list[dict[str, object]]
    target_coverage: list[dict[str, object]]
    coverage_state: str
    missing_snapshot_count: int
    fallback_active: bool
    fallback_count: int

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
            "source_policies": self.source_policies,
            "source_statuses": self.source_statuses,
            "target_coverage": self.target_coverage,
            "coverage_state": self.coverage_state,
            "missing_snapshot_count": self.missing_snapshot_count,
            "fallback_active": self.fallback_active,
            "fallback_count": self.fallback_count,
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
        self._last_source_by_exchange: dict[str, str] = {}
        self._fallback_count_by_exchange: dict[str, int] = {}
        self._last_fallback_at_by_exchange: dict[str, str] = {}
        self._last_fallback_reason_by_exchange: dict[str, str] = {}

    @property
    def info(self) -> MarketDataRuntimeInfo:
        target_groups = self._target_groups()
        target_count = sum(len(markets) for _, markets in target_groups)
        source_policies = self._source_policy_items(target_groups)
        source_statuses = self._source_status_items(source_policies)
        target_coverage = self._target_coverage_items(target_groups)
        missing_snapshot_count = sum(
            len(tuple(item.get("missing_markets") or ())) for item in target_coverage
        )
        coverage_state = self._coverage_state_name(
            target_count=target_count,
            missing_snapshot_count=missing_snapshot_count,
        )
        fallback_active = any(bool(item.get("fallback_active")) for item in source_statuses)
        fallback_count = sum(int(item.get("fallback_count") or 0) for item in source_statuses)
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
                state=self._state_name(fallback_active=fallback_active),
                last_success_at=self._last_success_at,
                last_error_at=self._last_error_at,
                last_error_message=self._last_error_message,
                success_count=self._success_count,
                failure_count=self._failure_count,
                source_policies=source_policies,
                source_statuses=source_statuses,
                target_coverage=target_coverage,
                coverage_state=coverage_state,
                missing_snapshot_count=missing_snapshot_count,
                fallback_active=fallback_active,
                fallback_count=fallback_count,
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

    def _state_name(self, *, fallback_active: bool = False) -> str:
        if not self.enabled:
            return "disabled"
        if fallback_active and self._running:
            return "running_with_fallback"
        if fallback_active:
            return "fallback_active"
        if self._running:
            return "running"
        if not self._target_groups():
            return "invalid_config"
        if self._failure_count > 0 and self._success_count == 0:
            return "degraded"
        return "idle"

    def _coverage_state_name(
        self, *, target_count: int, missing_snapshot_count: int
    ) -> str:
        if target_count <= 0:
            return "no_targets"
        if missing_snapshot_count <= 0:
            return "covered"
        if missing_snapshot_count >= target_count:
            return "missing"
        return "partial"

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

    def _source_policy_items(
        self,
        target_groups: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> list[dict[str, object]]:
        exchanges = sorted({exchange for exchange, _markets in target_groups})
        policy_reader = getattr(self.connector, "source_policy", None)
        items: list[dict[str, object]] = []
        for exchange in exchanges:
            if callable(policy_reader):
                policy = policy_reader(exchange=exchange)
                if hasattr(policy, "as_dict"):
                    items.append(policy.as_dict())
                    continue
                if isinstance(policy, dict):
                    items.append(dict(policy))
                    continue
            items.append(
                {
                    "exchange": exchange,
                    "preferred_source": "rest",
                    "fallback_source": None,
                    "ws_supported": False,
                    "support_level": "unsupported",
                    "policy_name": "rest_only",
                }
            )
        return items

    def _source_status_items(
        self, source_policies: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        with self._lock:
            last_source_by_exchange = dict(self._last_source_by_exchange)
            fallback_count_by_exchange = dict(self._fallback_count_by_exchange)
            last_fallback_at_by_exchange = dict(self._last_fallback_at_by_exchange)
            last_fallback_reason_by_exchange = dict(self._last_fallback_reason_by_exchange)
        for policy in source_policies:
            exchange = str(policy.get("exchange") or "").strip().lower()
            preferred_source = str(policy.get("preferred_source") or "rest")
            fallback_source = policy.get("fallback_source")
            last_source = last_source_by_exchange.get(exchange)
            fallback_active = bool(fallback_source) and bool(last_source) and last_source != preferred_source
            state = "idle"
            if fallback_active:
                state = "fallback_active"
            elif preferred_source == "rest" and not bool(policy.get("ws_supported")):
                state = "rest_only"
            elif last_source:
                state = "healthy" if preferred_source == last_source else "rest_only"
            items.append(
                {
                    "exchange": exchange,
                    "policy_name": policy.get("policy_name"),
                    "preferred_source": preferred_source,
                    "fallback_source": fallback_source,
                    "last_source": last_source,
                    "fallback_active": fallback_active,
                    "fallback_count": fallback_count_by_exchange.get(exchange, 0),
                    "last_fallback_at": last_fallback_at_by_exchange.get(exchange),
                    "last_fallback_reason": last_fallback_reason_by_exchange.get(exchange),
                    "ws_supported": bool(policy.get("ws_supported")),
                    "support_level": str(policy.get("support_level") or "unsupported"),
                    "state": state,
                }
            )
        return items

    def _target_coverage_items(
        self, target_groups: tuple[tuple[str, tuple[str, ...]], ...]
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for exchange, markets in target_groups:
            missing_markets: list[str] = []
            cached_market_count = 0
            for market in markets:
                snapshot = self._cached_snapshot(exchange=exchange, market=market)
                if isinstance(snapshot, dict):
                    cached_market_count += 1
                    continue
                missing_markets.append(market)
            state = "covered"
            if missing_markets and cached_market_count:
                state = "partial"
            elif missing_markets:
                state = "missing"
            items.append(
                {
                    "exchange": exchange,
                    "target_market_count": len(markets),
                    "cached_market_count": cached_market_count,
                    "missing_markets": missing_markets,
                    "state": state,
                }
            )
        return items

    def _cached_snapshot(self, *, exchange: str, market: str) -> dict[str, object] | None:
        cached_reader = getattr(self.connector, "get_cached_orderbook_top", None)
        if callable(cached_reader):
            cached = cached_reader(exchange=exchange, market=market)
            if isinstance(cached, dict):
                return cached
        if self.redis_runtime.info.enabled:
            payload = self.redis_runtime.get_market_orderbook_top(exchange=exchange, market=market)
            if isinstance(payload, dict):
                return payload
        return None

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
        exchange = str(snapshot["exchange"]).strip().lower()
        actual_source = str(snapshot.get("source_type") or "").strip().lower() or None
        fallback_used = bool(snapshot.get("collector_fallback_used"))
        fallback_reason = str(snapshot.get("collector_fallback_reason") or "").strip()
        with self._lock:
            self._success_count += 1
            self._last_success_at = _iso_now()
            self._last_error_message = None
            if actual_source is not None:
                self._last_source_by_exchange[exchange] = actual_source
            if fallback_used:
                self._fallback_count_by_exchange[exchange] = (
                    self._fallback_count_by_exchange.get(exchange, 0) + 1
                )
                self._last_fallback_at_by_exchange[exchange] = self._last_success_at or _iso_now()
                if fallback_reason:
                    self._last_fallback_reason_by_exchange[exchange] = fallback_reason

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
