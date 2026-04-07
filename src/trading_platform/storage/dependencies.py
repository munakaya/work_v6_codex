from __future__ import annotations

from dataclasses import dataclass
import shutil
import socket
import subprocess
from typing import Final
from urllib.parse import urlparse
from urllib import error, request

from ..config import AppConfig
from ..strategy.exchange_key_loader import inspect_exchange_trading_credentials_from_config


DEFAULT_POSTGRES_PORT: Final[int] = 5432
DEFAULT_REDIS_PORT: Final[int] = 6379
TCP_TIMEOUT_SECONDS: Final[float] = 0.5
HTTP_TIMEOUT_SECONDS: Final[float] = 1.0


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


def exchange_trading_key_statuses(config: AppConfig) -> dict[str, object]:
    exchanges = ("upbit", "bithumb", "coinone")
    items = [
        inspect_exchange_trading_credentials_from_config(config, exchange).as_dict()
        for exchange in exchanges
    ]
    ready_count = sum(1 for item in items if bool(item.get("ready")))
    configured_count = sum(1 for item in items if bool(item.get("configured")))
    overall_state = (
        "ready"
        if ready_count == len(items)
        else "partial"
        if ready_count > 0
        else "missing"
    )
    return {
        "items": items,
        "count": len(items),
        "configured_count": configured_count,
        "ready_count": ready_count,
        "overall_state": overall_state,
    }


def postgres_status(dsn: str | None) -> DependencyStatus:
    return _status_from_url(dsn, DEFAULT_POSTGRES_PORT)


def redis_status(url: str | None) -> DependencyStatus:
    return _status_from_url(url, DEFAULT_REDIS_PORT)


def private_execution_status(
    *,
    execution_enabled: bool,
    execution_mode: str,
    submit_url: str | None,
    health_url: str | None,
    token: str | None = None,
    timeout_ms: int = 3000,
) -> DependencyStatus:
    if not execution_enabled or execution_mode.strip().lower() != "private_http":
        return DependencyStatus(
            configured=False,
            reachable=False,
            state="not_required",
        )
    if not submit_url:
        return DependencyStatus(
            configured=False,
            reachable=False,
            state="submit_url_missing",
        )
    if not health_url:
        parsed_submit = urlparse(submit_url)
        return DependencyStatus(
            configured=False,
            reachable=False,
            state="health_url_missing",
            host=parsed_submit.hostname,
            port=parsed_submit.port or _default_port(parsed_submit.scheme),
        )
    parsed = urlparse(health_url)
    host = parsed.hostname
    port = parsed.port or _default_port(parsed.scheme)
    if not parsed.scheme or not host:
        return DependencyStatus(
            configured=True,
            reachable=False,
            state="invalid_config",
            host=host,
            port=port,
        )
    timeout_seconds = max(timeout_ms, 250) / 1000.0
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(health_url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=min(timeout_seconds, HTTP_TIMEOUT_SECONDS * 5)) as response:
            status_code = getattr(response, "status", 200)
    except error.HTTPError as exc:
        return DependencyStatus(
            configured=True,
            reachable=False,
            state=f"http_{exc.code}",
            host=host,
            port=port,
        )
    except (error.URLError, TimeoutError, OSError):
        return DependencyStatus(
            configured=True,
            reachable=False,
            state="unreachable",
            host=host,
            port=port,
        )
    state = "reachable" if 200 <= int(status_code) < 400 else f"http_{int(status_code)}"
    return DependencyStatus(
        configured=True,
        reachable=200 <= int(status_code) < 400,
        state=state,
        host=host,
        port=port,
    )


def _status_from_url(raw_url: str | None, default_port: int) -> DependencyStatus:
    if not raw_url:
        return DependencyStatus(configured=False, reachable=False, state="not_configured")

    parsed = urlparse(raw_url)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        if parsed.scheme.startswith("postgres") and parsed.path and parsed.path != "/":
            reachable = _postgres_local_socket_reachable(parsed.path.lstrip("/"))
            return DependencyStatus(
                configured=True,
                reachable=reachable,
                state="reachable_local_socket" if reachable else "unreachable_local_socket",
                host="local_socket",
                port=None,
            )
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


def _default_port(scheme: str | None) -> int | None:
    normalized = (scheme or "").strip().lower()
    if normalized == "https":
        return 443
    if normalized == "http":
        return 80
    return None


def _postgres_local_socket_reachable(database_name: str) -> bool:
    pg_isready = shutil.which("pg_isready")
    if pg_isready is None:
        return False
    try:
        subprocess.run(
            [pg_isready, "-q", "-d", database_name],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
