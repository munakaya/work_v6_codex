from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
import importlib
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
