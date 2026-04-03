from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import shutil

from ..config import AppConfig
from .postgres_driver import PostgresDriverAdapter, PsqlCliAdapter
from .postgres_mutable_store import PostgresMutableStore
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
    cli_name = _detect_postgres_cli()
    if config.use_sample_read_model:
        return StoreBootstrapResult(
            store=sample_read_store(),
            info=StoreBootstrapInfo(
                backend_name="memory_sample",
                supports_mutation=True,
                mode="sample",
                driver_name=driver_name or cli_name,
                driver_available=bool(driver_name or cli_name),
                reason="TP_USE_SAMPLE_READ_MODEL enabled",
            ),
        )

    if config.postgres_dsn:
        postgres_backend = _postgres_backend_result(
            config.postgres_dsn,
            driver_name,
            cli_name,
            enable_mutation=config.enable_postgres_mutation,
        )
        if postgres_backend is not None:
            return postgres_backend

    return StoreBootstrapResult(
        store=empty_read_store(),
        info=StoreBootstrapInfo(
            backend_name="memory_empty",
            supports_mutation=False,
            mode="empty",
            driver_name=driver_name or cli_name,
            driver_available=bool(driver_name or cli_name),
            reason=_fallback_reason(config.postgres_dsn, driver_name, cli_name),
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


def _detect_postgres_cli() -> str | None:
    if shutil.which("psql") is None:
        return None
    return "psql"


def _postgres_backend_result(
    dsn: str,
    driver_name: str | None,
    cli_name: str | None,
    *,
    enable_mutation: bool,
) -> StoreBootstrapResult | None:
    if driver_name is not None:
        adapter = PostgresDriverAdapter(dsn, driver_name)
        ok, reason = adapter.probe()
        if ok:
            store = PostgresMutableStore(adapter) if enable_mutation else PostgresReadStore(adapter)
            return StoreBootstrapResult(
                store=store,
                info=StoreBootstrapInfo(
                    backend_name=store.backend_name,
                    supports_mutation=store.supports_mutation,
                    mode="postgres",
                    driver_name=driver_name,
                    driver_available=True,
                    reason=(
                        "PostgreSQL mutable repository enabled"
                        if enable_mutation
                        else "PostgreSQL read repository enabled"
                    ),
                ),
            )
        return StoreBootstrapResult(
            store=empty_read_store(),
            info=StoreBootstrapInfo(
                backend_name="memory_empty",
                supports_mutation=False,
                mode="empty",
                driver_name=driver_name,
                driver_available=True,
                reason=f"PostgreSQL driver probe failed: {reason}",
            ),
        )

    if cli_name is not None:
        adapter = PsqlCliAdapter(dsn, cli_name)
        ok, reason = adapter.probe()
        if ok:
            store = PostgresMutableStore(adapter) if enable_mutation else PostgresReadStore(adapter)
            return StoreBootstrapResult(
                store=store,
                info=StoreBootstrapInfo(
                    backend_name=store.backend_name,
                    supports_mutation=store.supports_mutation,
                    mode="postgres",
                    driver_name="psql",
                    driver_available=True,
                    reason=(
                        "PostgreSQL mutable repository enabled via psql"
                        if enable_mutation
                        else "PostgreSQL read repository enabled via psql"
                    ),
                ),
            )
        return StoreBootstrapResult(
            store=empty_read_store(),
            info=StoreBootstrapInfo(
                backend_name="memory_empty",
                supports_mutation=False,
                mode="empty",
                driver_name="psql",
                driver_available=True,
                reason=f"PostgreSQL CLI probe failed: {reason}",
            ),
        )

    return None


def _fallback_reason(
    postgres_dsn: str | None, driver_name: str | None, cli_name: str | None
) -> str:
    if not postgres_dsn:
        return "TP_POSTGRES_DSN not configured; using empty in-memory store"
    if driver_name is None and cli_name is None:
        return "PostgreSQL driver/cli unavailable; using empty in-memory store"
    return "PostgreSQL read repository unavailable; using empty in-memory store"
