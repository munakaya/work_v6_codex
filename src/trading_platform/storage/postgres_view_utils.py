from __future__ import annotations

from datetime import datetime
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


def assigned_config(row: dict[str, object]) -> dict[str, object] | None:
    scope = row.get("assigned_config_scope")
    version_no = row.get("assigned_version_no")
    if scope is None or version_no is None:
        return None
    payload: dict[str, object] = {
        "config_scope": scope,
        "version_no": version_no,
    }
    config_version_id = row.get("assigned_config_version_id")
    assigned_at = row.get("assigned_at")
    if config_version_id is not None:
        payload["config_version_id"] = config_version_id
    if assigned_at is not None:
        payload["assigned_at"] = assigned_at
    return payload


def bot_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "bot_id": row["bot_id"],
        "bot_key": row["bot_key"],
        "strategy_name": row["strategy_name"],
        "mode": row["mode"],
        "status": row["status"],
        "hostname": row.get("hostname"),
        "last_seen_at": row.get("last_seen_at"),
        "assigned_config_version": assigned_config(row),
    }


def strategy_run(row: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "bot_id": row["bot_id"],
        "strategy_name": row["strategy_name"],
        "mode": row["mode"],
        "status": "created" if row["status"] == "pending" else row["status"],
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "stopped_at": row.get("stopped_at"),
        "decision_count": row.get("decision_count", 0),
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
        "target_qty": row["target_qty"],
        "expected_profit": row.get("expected_profit"),
        "expected_profit_ratio": row.get("expected_profit_ratio"),
        "status": row["status"],
        "created_at": row["created_at"],
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
        "requested_price": row.get("requested_price"),
        "requested_qty": row["requested_qty"],
        "filled_qty": row.get("filled_qty") or "0",
        "avg_fill_price": row.get("avg_fill_price"),
        "fee_amount": row.get("fee_amount"),
        "status": row["status"],
        "internal_error_code": row.get("internal_error_code"),
        "created_at": row.get("created_at"),
        "submitted_at": row.get("submitted_at"),
        "updated_at": row.get("updated_at"),
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
        "fill_price": row["fill_price"],
        "fill_qty": row["fill_qty"],
        "fee_asset": row.get("fee_asset"),
        "fee_amount": row.get("fee_amount"),
        "order_status": row.get("order_status"),
        "filled_at": row["filled_at"],
        "created_at": row["created_at"],
    }
