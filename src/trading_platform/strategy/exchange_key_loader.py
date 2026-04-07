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


def load_exchange_trading_credentials(
    exchange: str,
    *,
    primary_dir: Path,
    fallback_dir: Path,
) -> ExchangeTradingCredentials | None:
    normalized_exchange = _normalize_exchange(exchange)
    for path in _candidate_paths(
        exchange=normalized_exchange,
        primary_dir=primary_dir,
        fallback_dir=fallback_dir,
    ):
        if not path.is_file():
            continue
        payload = _read_json_object(path)
        access_key = _resolve_access_key(payload, normalized_exchange)
        secret_key = _require_non_empty_string(
            payload,
            "secret_key",
            path=path,
            exchange=normalized_exchange,
        )
        return ExchangeTradingCredentials(
            exchange=normalized_exchange,
            access_key=access_key,
            secret_key=secret_key,
            source_path=path,
        )
    return None


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
    if _string_value(payload.get("access_key")) is not None:
        return _string_value(payload.get("access_key")) or ""
    for field_name in LEGACY_ACCESS_KEY_FIELDS.get(exchange, ()):
        value = _string_value(payload.get(field_name))
        if value is not None:
            return value
    raise ValueError(
        "trading credential file is missing access_key "
        f"(exchange={exchange}, accepted_legacy_fields={LEGACY_ACCESS_KEY_FIELDS.get(exchange, ())})"
    )


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
