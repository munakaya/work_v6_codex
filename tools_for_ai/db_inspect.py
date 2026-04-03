from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.config import load_config
from trading_platform.storage.postgres_driver import PsqlCliAdapter
from trading_platform.storage.schema import code_managed_tables, migration_files


TABLE_PATTERN = re.compile(r"create\s+table\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)


@dataclass(frozen=True)
class InspectResult:
    db_kind: str
    configured: bool
    cli_available: bool
    details: str


def main() -> None:
    config = load_config()
    report_dir = config.tmp_dir / "db_report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "latest.md"

    postgres_result = inspect_postgres(config.postgres_dsn)
    redis_result = inspect_redis(config.redis_url)
    code_tables = code_managed_tables(config.migrations_dir)

    lines = [
        "# DB Inspection Report",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- project_root: {config.project_root}",
        "",
        "## Runtime Configuration",
        "",
        f"- postgres: {postgres_result.db_kind} / configured={postgres_result.configured} / cli_available={postgres_result.cli_available}",
        f"- redis: {redis_result.db_kind} / configured={redis_result.configured} / cli_available={redis_result.cli_available}",
        f"- redis_key_prefix: `{config.redis_key_prefix}`",
        "",
        "### PostgreSQL",
        "",
        postgres_result.details,
        "",
        "### Redis",
        "",
        redis_result.details,
        "",
        "## Code-Managed Schema",
        "",
        f"- migration_files: {len(migration_files(config.migrations_dir))}",
        f"- tables: {', '.join(code_tables) if code_tables else '(none)'}",
        "",
    ]

    for migration in migration_files(config.migrations_dir):
        lines.extend(render_migration_summary(migration.path))

    report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(report_path)


def inspect_postgres(dsn: str | None) -> InspectResult:
    if not dsn:
        return InspectResult(
            db_kind="postgresql",
            configured=False,
            cli_available=bool(shutil.which("psql")),
            details="- DSN not configured (`TP_POSTGRES_DSN` missing)",
        )

    parsed = urlparse(dsn)
    masked = mask_url(parsed)
    cli_available = bool(shutil.which("psql"))
    details = [f"- target: `{masked}`"]
    if not cli_available:
        details.append("- psql not available, runtime inspection skipped")
        return InspectResult("postgresql", True, False, "\n".join(details))

    try:
        adapter = PsqlCliAdapter(dsn)
        tables = fetch_runtime_tables(adapter)
        details.append(f"- runtime_tables: {', '.join(tables) if tables else '(none)'}")
        if tables:
            details.extend(render_postgres_runtime_details(adapter, tables))
    except Exception as exc:  # noqa: BLE001
        details.append(f"- runtime inspection failed: {exc.__class__.__name__}")
    return InspectResult("postgresql", True, True, "\n".join(details))


def inspect_redis(url: str | None) -> InspectResult:
    if not url:
        return InspectResult(
            db_kind="redis",
            configured=False,
            cli_available=bool(shutil.which("redis-cli")),
            details="- URL not configured (`TP_REDIS_URL` missing)",
        )

    parsed = urlparse(url)
    masked = mask_url(parsed)
    cli_available = bool(shutil.which("redis-cli"))
    details = [f"- target: `{masked}`"]
    if not cli_available:
        details.append("- redis-cli not available, runtime inspection skipped")
        return InspectResult("redis", True, False, "\n".join(details))

    args = ["redis-cli"]
    if parsed.hostname:
        args.extend(["-h", parsed.hostname])
    if parsed.port:
        args.extend(["-p", str(parsed.port)])
    if parsed.password:
        args.extend(["-a", parsed.password])
    if parsed.path and parsed.path != "/":
        args.extend(["-n", parsed.path.lstrip("/")])
    args.append("PING")
    try:
        output = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        details.append(f"- ping: `{output.stdout.strip()}`")
    except Exception as exc:  # noqa: BLE001
        details.append(f"- runtime inspection failed: {exc.__class__.__name__}")
    return InspectResult("redis", True, True, "\n".join(details))


def render_migration_summary(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    tables = [match.group(1) for match in TABLE_PATTERN.finditer(content)]
    return [
        f"### {path.name}",
        "",
        f"- tables: {', '.join(tables) if tables else '(none)'}",
        "",
    ]


def fetch_runtime_tables(adapter: PsqlCliAdapter) -> list[str]:
    rows = adapter.fetch_all(
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public'
        order by table_name
        """
    )
    return [str(row["table_name"]) for row in rows]


def render_postgres_runtime_details(
    adapter: PsqlCliAdapter, tables: list[str]
) -> list[str]:
    lines = [
        "",
        "#### Runtime Table Details",
        "",
    ]
    columns_by_table = fetch_columns(adapter)
    pk_by_table = fetch_primary_keys(adapter)
    fk_by_table = fetch_foreign_keys(adapter)
    indexes_by_table = fetch_indexes(adapter)
    constraints_by_table = fetch_constraints(adapter)
    row_counts = fetch_row_counts(adapter, tables)
    views = fetch_views(adapter)
    if views:
        lines.append(f"- views: {', '.join(views)}")
        lines.append("")
    for table in tables:
        lines.append(f"- table `{table}`")
        lines.append(f"  row_count: {row_counts.get(table, 'unknown')}")
        column_items = columns_by_table.get(table, [])
        if column_items:
            rendered_columns = ", ".join(
                f"{item['column_name']}:{item['data_type']}:{'null' if item['is_nullable'] == 'YES' else 'not_null'}"
                for item in column_items
            )
            lines.append(f"  columns: {rendered_columns}")
        else:
            lines.append("  columns: (none)")
        lines.append(
            f"  primary_key: {', '.join(pk_by_table.get(table, [])) if pk_by_table.get(table) else '(none)'}"
        )
        fk_items = fk_by_table.get(table, [])
        lines.append(
            "  foreign_keys: "
            + (
                ", ".join(
                    f"{item['column_name']}->{item['foreign_table_name']}.{item['foreign_column_name']}"
                    for item in fk_items
                )
                if fk_items
                else "(none)"
            )
        )
        idx_items = indexes_by_table.get(table, [])
        lines.append(
            "  indexes: "
            + (
                ", ".join(
                    f"{item['indexname']}({item['indexdef']})" for item in idx_items
                )
                if idx_items
                else "(none)"
            )
        )
        constraint_items = constraints_by_table.get(table, [])
        lines.append(
            "  constraints: "
            + (
                ", ".join(
                    f"{item['constraint_name']}:{item['constraint_type']}"
                    for item in constraint_items
                )
                if constraint_items
                else "(none)"
            )
        )
        lines.append("")
    return lines


def fetch_columns(adapter: PsqlCliAdapter) -> dict[str, list[dict[str, object]]]:
    rows = adapter.fetch_all(
        """
        select table_name, column_name, data_type, is_nullable
        from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position
        """
    )
    result: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        result.setdefault(str(row["table_name"]), []).append(row)
    return result


def fetch_primary_keys(adapter: PsqlCliAdapter) -> dict[str, list[str]]:
    rows = adapter.fetch_all(
        """
        select tc.table_name, kcu.column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
         and tc.table_schema = kcu.table_schema
        where tc.table_schema = 'public'
          and tc.constraint_type = 'PRIMARY KEY'
        order by tc.table_name, kcu.ordinal_position
        """
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row["table_name"]), []).append(str(row["column_name"]))
    return result


def fetch_foreign_keys(adapter: PsqlCliAdapter) -> dict[str, list[dict[str, object]]]:
    rows = adapter.fetch_all(
        """
        select
            tc.table_name,
            kcu.column_name,
            ccu.table_name as foreign_table_name,
            ccu.column_name as foreign_column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
         and tc.table_schema = kcu.table_schema
        join information_schema.constraint_column_usage ccu
          on ccu.constraint_name = tc.constraint_name
         and ccu.table_schema = tc.table_schema
        where tc.table_schema = 'public'
          and tc.constraint_type = 'FOREIGN KEY'
        order by tc.table_name, kcu.column_name
        """
    )
    result: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        result.setdefault(str(row["table_name"]), []).append(row)
    return result


def fetch_indexes(adapter: PsqlCliAdapter) -> dict[str, list[dict[str, object]]]:
    rows = adapter.fetch_all(
        """
        select tablename, indexname, indexdef
        from pg_indexes
        where schemaname = 'public'
        order by tablename, indexname
        """
    )
    result: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        result.setdefault(str(row["tablename"]), []).append(row)
    return result


def fetch_constraints(adapter: PsqlCliAdapter) -> dict[str, list[dict[str, object]]]:
    rows = adapter.fetch_all(
        """
        select table_name, constraint_name, constraint_type
        from information_schema.table_constraints
        where table_schema = 'public'
        order by table_name, constraint_name
        """
    )
    result: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        result.setdefault(str(row["table_name"]), []).append(row)
    return result


def fetch_row_counts(adapter: PsqlCliAdapter, tables: list[str]) -> dict[str, object]:
    counts: dict[str, object] = {}
    for table in tables:
        try:
            counts[table] = adapter.fetch_value(f"select count(*) as row_count from {table}")
        except Exception as exc:  # noqa: BLE001
            counts[table] = exc.__class__.__name__
    return counts


def fetch_views(adapter: PsqlCliAdapter) -> list[str]:
    rows = adapter.fetch_all(
        """
        select table_name
        from information_schema.views
        where table_schema = 'public'
        order by table_name
        """
    )
    return [str(row["table_name"]) for row in rows]


def mask_url(parsed) -> str:
    is_local_socket = parsed.scheme.startswith("postgres") and not parsed.hostname
    host = parsed.hostname or ("local_socket" if is_local_socket else "unknown")
    port = f":{parsed.port}" if parsed.port else ""
    db_name = parsed.path.lstrip("/") if parsed.path else ""
    user = parsed.username or ("local" if is_local_socket else "unknown")
    prefix = f"{parsed.scheme}://{user}:***@{host}{port}"
    return f"{prefix}/{db_name}" if db_name else prefix


if __name__ == "__main__":
    main()
