from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..config import AppConfig


SUPPORTED_EXCHANGES = frozenset({"upbit", "bithumb", "coinone"})
LEGACY_ACCESS_KEY_FIELDS = {
    "upbit": (),
    "bithumb": ("api_key",),
    "coinone": ("access_token", "api_key"),
}


@dataclass(frozen=True)
class ExchangeTradingCredentials:
    exchange: str
    access_key: str
    secret_key: str
    source_path: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "exchange": self.exchange,
            "access_key": self.access_key,
            "secret_key": self.secret_key,
            "source_path": str(self.source_path),
        }


@dataclass(frozen=True)
class ExchangeTradingCredentialsStatus:
    exchange: str
    configured: bool
    ready: bool
    state: str
    source_path: Path | None
    primary_path: Path
    fallback_path: Path
    access_key_field: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "configured": self.configured,
            "ready": self.ready,
            "state": self.state,
            "source_path": None if self.source_path is None else str(self.source_path),
            "primary_path": str(self.primary_path),
            "fallback_path": str(self.fallback_path),
            "access_key_field": self.access_key_field,
        }


def load_exchange_trading_credentials(
    exchange: str,
    *,
    primary_dir: Path,
    fallback_dir: Path,
) -> ExchangeTradingCredentials | None:
    status = inspect_exchange_trading_credentials(
        exchange,
        primary_dir=primary_dir,
        fallback_dir=fallback_dir,
    )
    if not status.configured:
        return None
    if not status.ready or status.source_path is None:
        raise ValueError(
            f"trading credential file is not ready: exchange={status.exchange} state={status.state}"
        )
    if status.source_path is None:
        return None
    payload = _read_json_object(status.source_path)
    access_key = _resolve_access_key(payload, status.exchange)
    secret_key = _require_non_empty_string(
        payload,
        "secret_key",
        path=status.source_path,
        exchange=status.exchange,
    )
    return ExchangeTradingCredentials(
        exchange=status.exchange,
        access_key=access_key,
        secret_key=secret_key,
        source_path=status.source_path,
    )


def inspect_exchange_trading_credentials(
    exchange: str,
    *,
    primary_dir: Path,
    fallback_dir: Path,
) -> ExchangeTradingCredentialsStatus:
    normalized_exchange = _normalize_exchange(exchange)
    primary_path, fallback_path = _candidate_paths(
        exchange=normalized_exchange,
        primary_dir=primary_dir,
        fallback_dir=fallback_dir,
    )
    for path, state_prefix in (
        (primary_path, "primary"),
        (fallback_path, "fallback"),
    ):
        if not path.is_file():
            continue
        try:
            payload = _read_json_object(path)
        except ValueError as exc:
            return ExchangeTradingCredentialsStatus(
                exchange=normalized_exchange,
                configured=True,
                ready=False,
                state=f"{state_prefix}_invalid:{exc}",
                source_path=path,
                primary_path=primary_path,
                fallback_path=fallback_path,
            )
        access_key_field = _resolve_access_key_field(payload, normalized_exchange)
        if access_key_field is None:
            return ExchangeTradingCredentialsStatus(
                exchange=normalized_exchange,
                configured=True,
                ready=False,
                state=f"{state_prefix}_missing_access_key",
                source_path=path,
                primary_path=primary_path,
                fallback_path=fallback_path,
            )
        if _string_value(payload.get("secret_key")) is None:
            return ExchangeTradingCredentialsStatus(
                exchange=normalized_exchange,
                configured=True,
                ready=False,
                state=f"{state_prefix}_missing_secret_key",
                source_path=path,
                primary_path=primary_path,
                fallback_path=fallback_path,
                access_key_field=access_key_field,
            )
        return ExchangeTradingCredentialsStatus(
            exchange=normalized_exchange,
            configured=True,
            ready=True,
            state=f"{state_prefix}_ready",
            source_path=path,
            primary_path=primary_path,
            fallback_path=fallback_path,
            access_key_field=access_key_field,
        )
    return ExchangeTradingCredentialsStatus(
        exchange=normalized_exchange,
        configured=False,
        ready=False,
        state="not_found",
        source_path=None,
        primary_path=primary_path,
        fallback_path=fallback_path,
    )


def inspect_exchange_trading_credentials_from_config(
    config: AppConfig,
    exchange: str,
) -> ExchangeTradingCredentialsStatus:
    return inspect_exchange_trading_credentials(
        exchange,
        primary_dir=config.exchange_key_primary_dir,
        fallback_dir=config.exchange_key_fallback_dir,
    )


def load_exchange_trading_credentials_from_config(
    config: AppConfig,
    exchange: str,
) -> ExchangeTradingCredentials | None:
    return load_exchange_trading_credentials(
        exchange,
        primary_dir=config.exchange_key_primary_dir,
        fallback_dir=config.exchange_key_fallback_dir,
    )


def _candidate_paths(
    *,
    exchange: str,
    primary_dir: Path,
    fallback_dir: Path,
) -> tuple[Path, Path]:
    return (
        primary_dir / f"{exchange}_trading.json",
        fallback_dir / f"{exchange}.json",
    )


def _normalize_exchange(exchange: str) -> str:
    normalized = exchange.strip().lower()
    if normalized not in SUPPORTED_EXCHANGES:
        raise ValueError(f"unsupported exchange for trading credentials: {exchange}")
    return normalized


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"failed to read trading credential file: {path}") from exc
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"trading credential file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"trading credential file must contain a JSON object: {path}")
    return payload


def _resolve_access_key(payload: dict[str, object], exchange: str) -> str:
    field_name = _resolve_access_key_field(payload, exchange)
    if field_name is None:
        raise ValueError(
            "trading credential file is missing access_key "
            f"(exchange={exchange}, accepted_legacy_fields={LEGACY_ACCESS_KEY_FIELDS.get(exchange, ())})"
        )
    value = _string_value(payload.get(field_name))
    if value is None:
        raise ValueError(
            "trading credential file is missing access_key "
            f"(exchange={exchange}, field={field_name})"
        )
    return value


def _resolve_access_key_field(payload: dict[str, object], exchange: str) -> str | None:
    if _string_value(payload.get("access_key")) is not None:
        return "access_key"
    for field_name in LEGACY_ACCESS_KEY_FIELDS.get(exchange, ()):
        value = _string_value(payload.get(field_name))
        if value is not None:
            return field_name
    return None


def _require_non_empty_string(
    payload: dict[str, object],
    field_name: str,
    *,
    path: Path,
    exchange: str,
) -> str:
    value = _string_value(payload.get(field_name))
    if value is None:
        raise ValueError(
            f"trading credential file is missing {field_name}: {path} (exchange={exchange})"
        )
    return value


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
