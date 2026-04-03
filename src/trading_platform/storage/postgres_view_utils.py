from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID


def uuid_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def timestamp_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def iso_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decimal_text(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    normalized = format(decimal.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def int_value(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def assigned_config(row: dict[str, object]) -> dict[str, object] | None:
    scope = row.get("assigned_config_scope")
    version_no = row.get("assigned_version_no")
    if scope is None or version_no is None:
        return None
    payload: dict[str, object] = {
        "config_scope": scope,
        "version_no": int_value(version_no),
    }
    config_version_id = row.get("assigned_config_version_id")
    assigned_at = row.get("assigned_at")
    if config_version_id is not None:
        payload["config_version_id"] = config_version_id
    if assigned_at is not None:
        payload["assigned_at"] = iso_text(assigned_at)
    return payload


def config_version(row: dict[str, object]) -> dict[str, object]:
    return {
        "config_version_id": row["config_version_id"],
        "config_scope": row["config_scope"],
        "version_no": int_value(row["version_no"]) or 0,
        "config_json": row.get("config_json") or {},
        "checksum": row["checksum"],
        "created_by": row.get("created_by"),
        "created_at": iso_text(row.get("created_at")),
    }


def heartbeat_entry(row: dict[str, object]) -> dict[str, object]:
    return {
        "created_at": iso_text(row.get("created_at")),
        "is_process_alive": row["is_process_alive"],
        "is_market_data_alive": row["is_market_data_alive"],
        "is_ordering_alive": row["is_ordering_alive"],
        "lag_ms": int_value(row.get("lag_ms")),
        "payload": row.get("payload") or {},
    }


def alert_event(row: dict[str, object]) -> dict[str, object]:
    return {
        "alert_id": row["alert_id"],
        "bot_id": row.get("bot_id"),
        "level": row["level"],
        "code": row["code"],
        "message": row["message"],
        "created_at": iso_text(row.get("created_at")),
        "acknowledged_at": iso_text(row.get("acknowledged_at")),
    }


def bot_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "bot_id": row["bot_id"],
        "bot_key": row["bot_key"],
        "strategy_name": row["strategy_name"],
        "mode": row["mode"],
        "status": row["status"],
        "hostname": row.get("hostname"),
        "last_seen_at": iso_text(row.get("last_seen_at")),
        "assigned_config_version": assigned_config(row),
    }


def strategy_run(row: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "bot_id": row["bot_id"],
        "strategy_name": row["strategy_name"],
        "mode": row["mode"],
        "status": "created" if row["status"] == "pending" else row["status"],
        "created_at": iso_text(row.get("created_at")),
        "started_at": iso_text(row.get("started_at")),
        "stopped_at": iso_text(row.get("stopped_at")),
        "decision_count": int_value(row.get("decision_count")) or 0,
    }


def order_intent(row: dict[str, object]) -> dict[str, object]:
    return {
        "intent_id": row["intent_id"],
        "bot_id": row.get("bot_id"),
        "strategy_run_id": row["strategy_run_id"],
        "market": row["market"],
        "buy_exchange": row["buy_exchange"],
        "sell_exchange": row["sell_exchange"],
        "side_pair": row["side_pair"],
        "target_qty": decimal_text(row["target_qty"]),
        "expected_profit": decimal_text(row.get("expected_profit")),
        "expected_profit_ratio": decimal_text(row.get("expected_profit_ratio")),
        "status": row["status"],
        "created_at": iso_text(row["created_at"]),
        "decision_context": row.get("decision_context") or {},
    }


def order(row: dict[str, object]) -> dict[str, object]:
    return {
        "order_id": row["order_id"],
        "order_intent_id": row.get("order_intent_id"),
        "bot_id": row.get("bot_id"),
        "strategy_run_id": row.get("strategy_run_id"),
        "exchange_name": row["exchange_name"],
        "exchange_order_id": row.get("exchange_order_id"),
        "market": row["market"],
        "side": row["side"],
        "requested_price": decimal_text(row.get("requested_price")),
        "requested_qty": decimal_text(row["requested_qty"]),
        "filled_qty": decimal_text(row.get("filled_qty"), default="0"),
        "avg_fill_price": decimal_text(row.get("avg_fill_price")),
        "fee_amount": decimal_text(row.get("fee_amount")),
        "status": row["status"],
        "internal_error_code": row.get("internal_error_code"),
        "created_at": iso_text(row.get("created_at")),
        "submitted_at": iso_text(row.get("submitted_at")),
        "updated_at": iso_text(row.get("updated_at")),
    }


def fill(row: dict[str, object]) -> dict[str, object]:
    return {
        "fill_id": row["fill_id"],
        "order_id": row["order_id"],
        "order_intent_id": row.get("order_intent_id"),
        "bot_id": row.get("bot_id"),
        "strategy_run_id": row.get("strategy_run_id"),
        "exchange_name": row["exchange_name"],
        "market": row["market"],
        "side": row["side"],
        "fill_price": decimal_text(row["fill_price"]),
        "fill_qty": decimal_text(row["fill_qty"]),
        "fee_asset": row.get("fee_asset"),
        "fee_amount": decimal_text(row.get("fee_amount")),
        "order_status": row.get("order_status"),
        "filled_at": iso_text(row["filled_at"]),
        "created_at": iso_text(row["created_at"]),
    }
