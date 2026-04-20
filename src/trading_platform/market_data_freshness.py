from __future__ import annotations

from datetime import UTC, datetime


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_iso_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat().replace("+00:00", "Z")



def choose_freshness_observed_at(
    snapshot: dict[str, object],
    *,
    fallback_now: str | None = None,
) -> tuple[str, str]:
    explicit_observed_at = _normalize_iso_text(snapshot.get("freshness_observed_at"))
    explicit_source = str(snapshot.get("freshness_observed_at_source") or "").strip()
    if explicit_observed_at:
        return explicit_observed_at, explicit_source or "explicit"

    exchange = str(snapshot.get("exchange") or "").strip().lower()
    source_type = str(snapshot.get("source_type") or "").strip().lower()
    exchange_timestamp = _normalize_iso_text(snapshot.get("exchange_timestamp"))
    received_at = _normalize_iso_text(snapshot.get("received_at"))

    if exchange == "coinone" and source_type == "public_ws" and received_at:
        return received_at, "received_at"
    if exchange_timestamp:
        return exchange_timestamp, "exchange_timestamp"
    if received_at:
        return received_at, "received_at"
    fallback = _normalize_iso_text(fallback_now) or _iso_now()
    return fallback, "fallback_now"


def snapshot_sort_datetime(snapshot: dict[str, object] | None) -> datetime | None:
    if not isinstance(snapshot, dict):
        return None
    observed_at, _source = choose_freshness_observed_at(snapshot)
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
