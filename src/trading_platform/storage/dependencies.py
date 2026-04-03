from __future__ import annotations

from dataclasses import dataclass
import socket
from typing import Final
from urllib.parse import urlparse


DEFAULT_POSTGRES_PORT: Final[int] = 5432
DEFAULT_REDIS_PORT: Final[int] = 6379
TCP_TIMEOUT_SECONDS: Final[float] = 0.5


@dataclass(frozen=True)
class DependencyStatus:
    configured: bool
    reachable: bool
    state: str
    host: str | None = None
    port: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "state": self.state,
            "host": self.host,
            "port": self.port,
        }


def postgres_status(dsn: str | None) -> DependencyStatus:
    return _status_from_url(dsn, DEFAULT_POSTGRES_PORT)


def redis_status(url: str | None) -> DependencyStatus:
    return _status_from_url(url, DEFAULT_REDIS_PORT)


def _status_from_url(raw_url: str | None, default_port: int) -> DependencyStatus:
    if not raw_url:
        return DependencyStatus(configured=False, reachable=False, state="not_configured")

    parsed = urlparse(raw_url)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        return DependencyStatus(
            configured=True,
            reachable=False,
            state="invalid_config",
            host=None,
            port=port,
        )

    reachable = _tcp_reachable(host, port)
    return DependencyStatus(
        configured=True,
        reachable=reachable,
        state="reachable" if reachable else "unreachable",
        host=host,
        port=port,
    )


def _tcp_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False
