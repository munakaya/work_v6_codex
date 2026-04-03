from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec

from ..config import AppConfig
from .postgres_driver import PostgresDriverAdapter
from .postgres_read_store import PostgresReadStore
from .read_store import MemoryReadStore, _sample_time
from .sample_data import build_sample_state
from .store_protocol import ControlPlaneStoreProtocol


@dataclass(frozen=True)
class StoreBootstrapInfo:
    backend_name: str
    supports_mutation: bool
    mode: str
    driver_name: str | None = None
    driver_available: bool = False
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "backend_name": self.backend_name,
            "supports_mutation": self.supports_mutation,
            "mode": self.mode,
            "driver_name": self.driver_name,
            "driver_available": self.driver_available,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StoreBootstrapResult:
    store: ControlPlaneStoreProtocol
    info: StoreBootstrapInfo


def build_read_store_bundle(config: AppConfig) -> StoreBootstrapResult:
    driver_name = _detect_postgres_driver()
    if config.use_sample_read_model:
        return StoreBootstrapResult(
            store=sample_read_store(),
            info=StoreBootstrapInfo(
                backend_name="memory_sample",
                supports_mutation=True,
                mode="sample",
                driver_name=driver_name,
                driver_available=driver_name is not None,
                reason="TP_USE_SAMPLE_READ_MODEL enabled",
            ),
        )

    if config.postgres_dsn and driver_name is not None:
        return StoreBootstrapResult(
            store=PostgresReadStore(
                PostgresDriverAdapter(config.postgres_dsn, driver_name)
            ),
            info=StoreBootstrapInfo(
                backend_name="postgres_readonly",
                supports_mutation=False,
                mode="postgres",
                driver_name=driver_name,
                driver_available=True,
                reason="PostgreSQL read repository enabled",
            ),
        )

    return StoreBootstrapResult(
        store=empty_read_store(),
        info=StoreBootstrapInfo(
            backend_name="memory_empty",
            supports_mutation=False,
            mode="empty",
            driver_name=driver_name,
            driver_available=driver_name is not None,
            reason=_fallback_reason(config.postgres_dsn, driver_name),
        ),
    )


def build_read_store(config: AppConfig) -> ControlPlaneStoreProtocol:
    return build_read_store_bundle(config).store


def empty_read_store() -> MemoryReadStore:
    return MemoryReadStore(
        bots=[],
        bot_details={},
        strategy_runs={},
        order_intents={},
        orders={},
        fills=[],
        heartbeats={},
        alerts=[],
        config_versions={},
        backend_name="memory_empty",
        supports_mutation=False,
    )


def sample_read_store() -> MemoryReadStore:
    state = build_sample_state(_sample_time)
    return MemoryReadStore(
        bots=state["bots"],
        bot_details=state["bot_details"],
        strategy_runs=state["strategy_runs"],
        order_intents=state["order_intents"],
        orders=state["orders"],
        fills=state["fills"],
        heartbeats=state["heartbeats"],
        alerts=state["alerts"],
        config_versions=state["config_versions"],
        backend_name="memory_sample",
    )


def _detect_postgres_driver() -> str | None:
    for module_name in ("psycopg", "psycopg2"):
        if find_spec(module_name) is not None:
            return module_name
    return None


def _fallback_reason(postgres_dsn: str | None, driver_name: str | None) -> str:
    if not postgres_dsn:
        return "TP_POSTGRES_DSN not configured; using empty in-memory store"
    if driver_name is None:
        return "PostgreSQL driver unavailable; using empty in-memory store"
    return "PostgreSQL read repository unavailable; using empty in-memory store"
