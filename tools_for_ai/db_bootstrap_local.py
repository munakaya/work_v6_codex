from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.storage.read_store import _sample_time
from trading_platform.storage.sample_data import build_sample_state


DEFAULT_DB_NAME = "work_v6_codex_dev"
MIGRATIONS_DIR = ROOT_DIR / "migrations" / "versions"
OUTPUT_DIR = ROOT_DIR / ".tmp" / "db_report"


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_NAME
    if not db_name.startswith("work_v6_codex_"):
        raise SystemExit("refusing to manage non-project database name")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sql_path = OUTPUT_DIR / f"bootstrap_{db_name}.sql"
    sql_path.write_text(render_seed_sql(), encoding="utf-8")

    run(["dropdb", "--if-exists", db_name])
    run(["createdb", db_name])
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        run(["psql", "-v", "ON_ERROR_STOP=1", "-d", db_name, "-f", str(migration)])
    run(["psql", "-v", "ON_ERROR_STOP=1", "-d", db_name, "-f", str(sql_path)])

    print(json.dumps({"database": db_name, "seed_sql": str(sql_path)}, ensure_ascii=True))


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, cwd=ROOT_DIR)


def render_seed_sql() -> str:
    state = build_sample_state(_sample_time)
    lines = [
        "begin;",
        render_config_versions(state["config_versions"]),
        render_bots(state["bots"]),
        render_bot_assignments(state["bots"], state["config_versions"]),
        render_strategy_runs(state["strategy_runs"]),
        render_order_intents(state["order_intents"]),
        render_orders(state["orders"]),
        render_fills(state["fills"]),
        render_heartbeats(state["heartbeats"]),
        render_alerts(state["alerts"]),
        "commit;",
        "",
    ]
    return "\n".join(lines)


def render_config_versions(config_versions: dict[str, list[dict[str, object]]]) -> str:
    values: list[str] = []
    for versions in config_versions.values():
        for item in versions:
            values.append(
                row_sql(
                    item["config_version_id"],
                    item["config_scope"],
                    item["version_no"],
                    json.dumps(item["config_json"], ensure_ascii=True),
                    item["checksum"],
                    item["created_by"],
                    item["created_at"],
                )
            )
    return insert_sql(
        "config_versions",
        ["id", "config_scope", "version_no", "config_json", "checksum", "created_by", "created_at"],
        values,
        cast_columns={
            "id": "uuid",
            "version_no": "integer",
            "config_json": "jsonb",
            "created_at": "timestamptz",
        },
    )


def render_bots(bots: list[dict[str, object]]) -> str:
    values = [
        row_sql(
            bot["bot_id"],
            bot["bot_key"],
            None,
            bot["strategy_name"],
            bot["mode"],
            bot["status"],
            bot.get("hostname"),
            bot["last_seen_at"],
            bot["last_seen_at"],
            bot["last_seen_at"],
        )
        for bot in bots
    ]
    return insert_sql(
        "bots",
        [
            "id",
            "bot_key",
            "exchange_group",
            "strategy_name",
            "mode",
            "status",
            "hostname",
            "started_at",
            "last_seen_at",
            "updated_at",
        ],
        values,
        cast_columns={
            "id": "uuid",
            "started_at": "timestamptz",
            "last_seen_at": "timestamptz",
            "updated_at": "timestamptz",
            "mode": "run_mode",
            "status": "strategy_status",
        },
    )


def render_bot_assignments(
    bots: list[dict[str, object]], config_versions: dict[str, list[dict[str, object]]]
) -> str:
    version_map = {
        (item["config_scope"], item["version_no"]): item["config_version_id"]
        for versions in config_versions.values()
        for item in versions
    }
    values = []
    for bot in bots:
        assigned = bot["assigned_config_version"]
        config_version_id = version_map[(assigned["config_scope"], assigned["version_no"])]
        values.append(
            row_sql(
                bot["bot_id"],
                config_version_id,
                True,
                bot["last_seen_at"],
                bot["last_seen_at"],
            )
        )
    return insert_sql(
        "bot_config_assignments",
        ["bot_id", "config_version_id", "applied", "applied_at", "created_at"],
        values,
        cast_columns={
            "bot_id": "uuid",
            "config_version_id": "uuid",
            "applied_at": "timestamptz",
            "created_at": "timestamptz",
        },
    )


def render_strategy_runs(strategy_runs: dict[str, dict[str, object]]) -> str:
    values = [
        row_sql(
            run["run_id"],
            run["bot_id"],
            run["strategy_name"],
            run["mode"],
            run["status"],
            run["started_at"],
            run["stopped_at"],
            None,
            run["created_at"],
        )
        for run in strategy_runs.values()
    ]
    return insert_sql(
        "strategy_runs",
        ["id", "bot_id", "strategy_name", "mode", "status", "started_at", "ended_at", "reason", "created_at"],
        values,
        cast_columns={
            "id": "uuid",
            "bot_id": "uuid",
            "started_at": "timestamptz",
            "ended_at": "timestamptz",
            "created_at": "timestamptz",
            "mode": "run_mode",
            "status": "strategy_status",
        },
    )


def render_order_intents(order_intents: dict[str, dict[str, object]]) -> str:
    values = [
        row_sql(
            intent["intent_id"],
            intent["strategy_run_id"],
            intent["market"],
            intent["buy_exchange"],
            intent["sell_exchange"],
            intent["side_pair"],
            intent["target_qty"],
            intent["expected_profit"],
            intent["expected_profit_ratio"],
            intent["status"],
            json.dumps(intent["decision_context"], ensure_ascii=True),
            intent["created_at"],
        )
        for intent in order_intents.values()
    ]
    return insert_sql(
        "order_intents",
        [
            "id",
            "strategy_run_id",
            "market",
            "buy_exchange",
            "sell_exchange",
            "side_pair",
            "target_qty",
            "expected_profit",
            "expected_profit_ratio",
            "status",
            "decision_context",
            "created_at",
        ],
        values,
        cast_columns={"decision_context": "jsonb", "created_at": "timestamptz"},
        cast_columns_extra={
            "id": "uuid",
            "strategy_run_id": "uuid",
            "target_qty": "numeric",
            "expected_profit": "numeric",
            "expected_profit_ratio": "numeric",
            "status": "order_intent_status",
        },
    )


def render_orders(orders: dict[str, dict[str, object]]) -> str:
    values = [
        row_sql(
            order["order_id"],
            order["order_intent_id"],
            order["bot_id"],
            order["exchange_name"],
            order["exchange_order_id"],
            order["market"],
            order["side"],
            order["requested_price"],
            order["requested_qty"],
            order["status"],
            order["submitted_at"],
            order["updated_at"],
            json.dumps({"internal_error_code": order["internal_error_code"]}, ensure_ascii=True),
        )
        for order in orders.values()
    ]
    return insert_sql(
        "orders",
        [
            "id",
            "order_intent_id",
            "bot_id",
            "exchange_name",
            "exchange_order_id",
            "market",
            "side",
            "price",
            "quantity",
            "status",
            "submitted_at",
            "updated_at",
            "raw_payload",
        ],
        values,
        cast_columns={
            "id": "uuid",
            "order_intent_id": "uuid",
            "bot_id": "uuid",
            "price": "numeric",
            "quantity": "numeric",
            "status": "order_status",
            "submitted_at": "timestamptz",
            "updated_at": "timestamptz",
            "raw_payload": "jsonb",
        },
    )


def render_fills(fills: list[dict[str, object]]) -> str:
    values = [
        row_sql(
            fill["fill_id"],
            fill["order_id"],
            None,
            fill["fill_price"],
            fill["fill_qty"],
            fill["fee_asset"],
            fill["fee_amount"],
            fill["filled_at"],
            fill["created_at"],
        )
        for fill in fills
    ]
    return insert_sql(
        "trade_fills",
        ["id", "order_id", "exchange_trade_id", "fill_price", "fill_qty", "fee_asset", "fee_amount", "filled_at", "created_at"],
        values,
        cast_columns={"filled_at": "timestamptz", "created_at": "timestamptz"},
        cast_columns_extra={
            "id": "uuid",
            "order_id": "uuid",
            "fill_price": "numeric",
            "fill_qty": "numeric",
            "fee_amount": "numeric",
        },
    )


def render_heartbeats(heartbeats: dict[str, list[dict[str, object]]]) -> str:
    values = []
    for bot_id, entries in heartbeats.items():
        for item in entries:
            values.append(
                row_sql(
                    bot_id,
                    item["is_process_alive"],
                    item["is_market_data_alive"],
                    item["is_ordering_alive"],
                    item["lag_ms"],
                    json.dumps(item["payload"], ensure_ascii=True),
                    item["created_at"],
                )
            )
    return insert_sql(
        "bot_heartbeats",
        ["bot_id", "is_process_alive", "is_market_data_alive", "is_ordering_alive", "lag_ms", "payload", "created_at"],
        values,
        cast_columns={"payload": "jsonb", "created_at": "timestamptz"},
        cast_columns_extra={"bot_id": "uuid", "lag_ms": "integer"},
    )


def render_alerts(alerts: list[dict[str, object]]) -> str:
    values = [
        row_sql(
            alert["alert_id"],
            alert["bot_id"],
            alert["level"],
            alert["code"],
            alert["message"],
            None,
            alert["created_at"],
            alert["acknowledged_at"],
        )
        for alert in alerts
    ]
    return insert_sql(
        "alert_events",
        ["id", "bot_id", "level", "code", "message", "context", "created_at", "acknowledged_at"],
        values,
        cast_columns={
            "id": "uuid",
            "bot_id": "uuid",
            "level": "alert_level",
            "context": "jsonb",
            "created_at": "timestamptz",
            "acknowledged_at": "timestamptz",
        },
    )


def insert_sql(
    table: str,
    columns: list[str],
    values: list[str],
    *,
    cast_columns: dict[str, str] | None = None,
    cast_columns_extra: dict[str, str] | None = None,
) -> str:
    cast_map = {}
    cast_map.update(cast_columns or {})
    cast_map.update(cast_columns_extra or {})
    column_sql = ", ".join(columns)
    row_sql_block = ",\n".join(f"    ({value})" for value in values)
    select_columns = []
    for column in columns:
        cast = cast_map.get(column)
        if cast:
            select_columns.append(f"{column}::{cast}")
        else:
            select_columns.append(column)
    select_sql = ", ".join(select_columns)
    return (
        f"insert into {table} ({column_sql})\n"
        f"select {select_sql}\n"
        f"from (values\n{row_sql_block}\n) as seed ({column_sql});\n"
    )


def row_sql(*values: object) -> str:
    return ", ".join(sql_literal(value) for value in values)


def sql_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace("'", "''")
    return f"'{text}'"


if __name__ == "__main__":
    main()
