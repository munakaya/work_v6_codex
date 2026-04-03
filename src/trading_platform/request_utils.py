from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
import json


def response_payload(
    *,
    request_id_factory,
    data: dict[str, object] | None = None,
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "request_id": request_id_factory(),
    }


def write_json(handler, status: HTTPStatus, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def write_text(
    handler,
    status: HTTPStatus,
    payload: str,
    content_type: str = "text/plain; version=0.0.4; charset=utf-8",
) -> None:
    encoded = payload.encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def read_json_body(handler) -> tuple[dict[str, object], tuple[HTTPStatus, dict[str, object]] | None]:
    length_header = handler.headers.get("Content-Length")
    if not length_header:
        return {}, (
            HTTPStatus.BAD_REQUEST,
            handler._response(
                error={"code": "INVALID_REQUEST", "message": "missing request body"}
            ),
        )

    try:
        length = int(length_header)
    except ValueError:
        return {}, (
            HTTPStatus.BAD_REQUEST,
            handler._response(
                error={
                    "code": "INVALID_REQUEST",
                    "message": "invalid content length",
                }
            ),
        )

    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}, (
            HTTPStatus.BAD_REQUEST,
            handler._response(
                error={"code": "INVALID_JSON", "message": "request body is not valid json"}
            ),
        )

    if not isinstance(payload, dict):
        return {}, (
            HTTPStatus.BAD_REQUEST,
            handler._response(
                error={"code": "INVALID_REQUEST", "message": "request body must be an object"}
            ),
        )
    return payload, None


def single_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def query_limit(params: dict[str, list[str]], default: int = 20) -> int:
    raw = single_query_value(params, "limit")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, 100))


def optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def json_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


def json_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def optional_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return None


def json_number_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not decimal.is_finite():
            return None
        normalized = format(decimal.normalize(), "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized or "0"
    return None


def is_positive_number_text(value: str | None) -> bool:
    if value is None:
        return False
    try:
        decimal = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    if not decimal.is_finite():
        return False
    return decimal > 0


def is_nonnegative_number_text(value: str | None) -> bool:
    if value is None:
        return False
    try:
        decimal = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    if not decimal.is_finite():
        return False
    return decimal >= 0


def json_datetime_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
