from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


TABLE_PATTERN = re.compile(r"create\s+table\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)


@dataclass(frozen=True)
class MigrationFile:
    revision: str
    path: Path


def migration_files(migrations_dir: Path) -> list[MigrationFile]:
    sql_dir = migrations_dir / "versions"
    files = sorted(sql_dir.glob("*.sql"))
    return [MigrationFile(revision=path.stem, path=path) for path in files]


def code_managed_tables(migrations_dir: Path) -> list[str]:
    tables: list[str] = []
    for migration in migration_files(migrations_dir):
        content = migration.path.read_text(encoding="utf-8")
        tables.extend(match.group(1) for match in TABLE_PATTERN.finditer(content))
    return tables
