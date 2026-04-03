from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import UTC, datetime
from decimal import Decimal
import importlib
import io
import json
import shutil
import subprocess
from typing import Any, Iterator
from uuid import UUID


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return value


class PostgresDriverAdapter:
    def __init__(self, dsn: str, driver_name: str) -> None:
        self.dsn = dsn
        self.driver_name = driver_name
        self._module = importlib.import_module(driver_name)

    def fetch_all(
        self, query: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        with self._cursor() as cursor:
            cursor.execute(query, params)
            columns = [description[0] for description in cursor.description]
            return [
                {column: _normalize_value(value) for column, value in zip(columns, row)}
                for row in cursor.fetchall()
            ]

    def fetch_one(
        self, query: str, params: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        rows = self.fetch_all(query, params)
        if not rows:
            return None
        return rows[0]

    def fetch_value(self, query: str, params: tuple[object, ...] = ()) -> object | None:
        row = self.fetch_one(query, params)
        if row is None:
            return None
        return next(iter(row.values()))

    def probe(self) -> tuple[bool, str | None]:
        try:
            value = self.fetch_value("select 1 as ok")
        except Exception as exc:  # noqa: BLE001
            return False, exc.__class__.__name__
        return value == 1, None

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        connection = self._module.connect(self.dsn)
        try:
            if hasattr(connection, "autocommit"):
                connection.autocommit = True
            cursor = connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            connection.close()


class PsqlCliAdapter:
    driver_name = "psql"

    def __init__(self, dsn: str, psql_path: str | None = None) -> None:
        self.dsn = dsn
        self.psql_path = psql_path or shutil.which("psql") or "psql"

    def fetch_all(
        self, query: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        rendered_query = _render_query(query, params)
        output = subprocess.run(
            [
                self.psql_path,
                self.dsn,
                "--csv",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                rendered_query,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        reader = csv.DictReader(io.StringIO(output.stdout))
        return [
            {str(key): _decode_text(value) for key, value in row.items()}
            for row in reader
        ]

    def fetch_one(
        self, query: str, params: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        rows = self.fetch_all(query, params)
        if not rows:
            return None
        return rows[0]

    def fetch_value(self, query: str, params: tuple[object, ...] = ()) -> object | None:
        row = self.fetch_one(query, params)
        if row is None:
            return None
        return next(iter(row.values()))

    def probe(self) -> tuple[bool, str | None]:
        try:
            value = self.fetch_value("select 1 as ok")
        except Exception as exc:  # noqa: BLE001
            return False, exc.__class__.__name__
        if value in (1, "1"):
            return True, None
        return False, "unexpected_probe_result"


def _render_query(query: str, params: tuple[object, ...]) -> str:
    rendered = query
    for param in params:
        rendered = rendered.replace("%s", _sql_literal(param), 1)
    return rendered


def _sql_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _decode_text(value: str | None) -> object:
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _looks_like_json(value):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _looks_like_json(value: str) -> bool:
    return value.startswith("{") or value.startswith("[")
