from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    service_name: str
    service_version: str
    host: str
    port: int
    log_level: str
    log_dir: Path
    tmp_dir: Path
    migrations_dir: Path
    alert_hook_path: Path | None
    postgres_dsn: str | None
    redis_url: str | None
    redis_key_prefix: str
    market_data_timeout_ms: int
    market_data_stale_threshold_ms: int
    upbit_quotation_base_url: str
    market_data_poll_enabled: bool
    market_data_poll_exchange: str
    market_data_poll_markets: tuple[str, ...]
    market_data_poll_interval_ms: int
    strategy_runtime_enabled: bool
    strategy_runtime_interval_ms: int
    strategy_runtime_persist_intent: bool
    strategy_runtime_execution_enabled: bool
    strategy_runtime_execution_mode: str
    strategy_private_execution_url: str | None
    strategy_private_execution_health_url: str | None
    strategy_private_execution_token: str | None
    strategy_private_execution_timeout_ms: int
    strategy_runtime_auto_unwind_on_failure: bool
    recovery_runtime_enabled: bool
    recovery_runtime_interval_ms: int
    recovery_runtime_handoff_after_seconds: int
    recovery_runtime_submit_timeout_seconds: int
    recovery_runtime_reconciliation_mismatch_handoff_count: int
    use_sample_read_model: bool
    enable_postgres_mutation: bool

    @property
    def ready_dependencies_configured(self) -> bool:
        return bool(self.postgres_dsn and self.redis_url)


def load_config() -> AppConfig:
    root_dir = Path(__file__).resolve().parents[2]
    alert_hook_raw = os.getenv("TP_ALERT_HOOK_PATH")
    return AppConfig(
        project_root=root_dir,
        service_name=os.getenv("TP_SERVICE_NAME", "control-plane"),
        service_version=os.getenv("TP_SERVICE_VERSION", "0.1.0"),
        host=os.getenv("TP_HOST", "127.0.0.1"),
        port=_env_int("TP_PORT", 38765),
        log_level=os.getenv("TP_LOG_LEVEL", "INFO").upper(),
        log_dir=root_dir / "logs",
        tmp_dir=root_dir / ".tmp",
        migrations_dir=root_dir / "migrations",
        alert_hook_path=Path(alert_hook_raw) if alert_hook_raw else None,
        postgres_dsn=os.getenv("TP_POSTGRES_DSN"),
        redis_url=os.getenv("TP_REDIS_URL"),
        redis_key_prefix=os.getenv("TP_REDIS_KEY_PREFIX", "tp"),
        market_data_timeout_ms=_env_int("TP_MARKET_DATA_TIMEOUT_MS", 3000),
        market_data_stale_threshold_ms=_env_int("TP_MARKET_DATA_STALE_THRESHOLD_MS", 3000),
        upbit_quotation_base_url=os.getenv(
            "TP_UPBIT_QUOTATION_BASE_URL", "https://api.upbit.com"
        ),
        market_data_poll_enabled=_env_bool("TP_MARKET_DATA_POLL_ENABLED", False),
        market_data_poll_exchange=os.getenv("TP_MARKET_DATA_POLL_EXCHANGE", "upbit"),
        market_data_poll_markets=_env_csv("TP_MARKET_DATA_POLL_MARKETS"),
        market_data_poll_interval_ms=_env_int("TP_MARKET_DATA_POLL_INTERVAL_MS", 1000),
        strategy_runtime_enabled=_env_bool("TP_STRATEGY_RUNTIME_ENABLED", False),
        strategy_runtime_interval_ms=_env_int("TP_STRATEGY_RUNTIME_INTERVAL_MS", 3000),
        strategy_runtime_persist_intent=_env_bool(
            "TP_STRATEGY_RUNTIME_PERSIST_INTENT", False
        ),
        strategy_runtime_execution_enabled=_env_bool(
            "TP_STRATEGY_RUNTIME_EXECUTION_ENABLED", False
        ),
        strategy_runtime_execution_mode=os.getenv(
            "TP_STRATEGY_RUNTIME_EXECUTION_MODE", "simulate_success"
        ).strip()
        or "simulate_success",
        strategy_private_execution_url=os.getenv("TP_STRATEGY_PRIVATE_EXECUTION_URL"),
        strategy_private_execution_health_url=os.getenv(
            "TP_STRATEGY_PRIVATE_EXECUTION_HEALTH_URL"
        ),
        strategy_private_execution_token=os.getenv("TP_STRATEGY_PRIVATE_EXECUTION_TOKEN"),
        strategy_private_execution_timeout_ms=_env_int(
            "TP_STRATEGY_PRIVATE_EXECUTION_TIMEOUT_MS", 3000
        ),
        strategy_runtime_auto_unwind_on_failure=_env_bool(
            "TP_STRATEGY_RUNTIME_AUTO_UNWIND_ON_FAILURE", False
        ),
        recovery_runtime_enabled=_env_bool("TP_RECOVERY_RUNTIME_ENABLED", False),
        recovery_runtime_interval_ms=_env_int("TP_RECOVERY_RUNTIME_INTERVAL_MS", 3000),
        recovery_runtime_handoff_after_seconds=_env_int(
            "TP_RECOVERY_RUNTIME_HANDOFF_AFTER_SECONDS", 30
        ),
        recovery_runtime_submit_timeout_seconds=_env_int(
            "TP_RECOVERY_RUNTIME_SUBMIT_TIMEOUT_SECONDS", 15
        ),
        recovery_runtime_reconciliation_mismatch_handoff_count=_env_int(
            "TP_RECOVERY_RUNTIME_RECONCILIATION_MISMATCH_HANDOFF_COUNT", 2
        ),
        use_sample_read_model=_env_bool("TP_USE_SAMPLE_READ_MODEL", True),
        enable_postgres_mutation=_env_bool("TP_ENABLE_POSTGRES_MUTATION", False),
    )
