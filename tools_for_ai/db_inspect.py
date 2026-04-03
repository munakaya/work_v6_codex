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

    query = """
    select table_name
    from information_schema.tables
    where table_schema = 'public'
    order by table_name;
    """
    try:
        output = subprocess.run(
            ["psql", dsn, "-At", "-c", query],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        tables = [line.strip() for line in output.stdout.splitlines() if line.strip()]
        details.append(f"- runtime_tables: {', '.join(tables) if tables else '(none)'}")
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


def mask_url(parsed) -> str:
    host = parsed.hostname or "unknown"
    port = f":{parsed.port}" if parsed.port else ""
    db_name = parsed.path.lstrip("/") if parsed.path else ""
    user = parsed.username or "unknown"
    prefix = f"{parsed.scheme}://{user}:***@{host}{port}"
    return f"{prefix}/{db_name}" if db_name else prefix


if __name__ == "__main__":
    main()
