from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


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
    postgres_dsn: str | None
    redis_url: str | None
    redis_key_prefix: str

    @property
    def ready_dependencies_configured(self) -> bool:
        return bool(self.postgres_dsn and self.redis_url)


def load_config() -> AppConfig:
    root_dir = Path(__file__).resolve().parents[2]
    return AppConfig(
        project_root=root_dir,
        service_name=os.getenv("TP_SERVICE_NAME", "control-plane"),
        service_version=os.getenv("TP_SERVICE_VERSION", "0.1.0"),
        host=os.getenv("TP_HOST", "127.0.0.1"),
        port=_env_int("TP_PORT", 8080),
        log_level=os.getenv("TP_LOG_LEVEL", "INFO").upper(),
        log_dir=root_dir / "logs",
        tmp_dir=root_dir / ".tmp",
        migrations_dir=root_dir / "migrations",
        postgres_dsn=os.getenv("TP_POSTGRES_DSN"),
        redis_url=os.getenv("TP_REDIS_URL"),
        redis_key_prefix=os.getenv("TP_REDIS_KEY_PREFIX", "tp"),
    )
