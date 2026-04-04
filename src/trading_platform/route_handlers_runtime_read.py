from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from urllib.parse import parse_qs

from .request_utils import optional_bool, single_query_value


class ControlPlaneRuntimeReadRouteMixin:
    STREAM_NAMES = (
        "market_events",
        "bot_events",
        "strategy_events",
        "order_events",
        "alert_events",
    )

    def _runtime_streams_response(self, query: str) -> tuple[HTTPStatus, dict[str, object]]:
        params = parse_qs(query)
        if not self.server.redis_runtime.info.enabled:
            return (
                HTTPStatus.SERVICE_UNAVAILABLE,
                self._response(
                    error={
                        "code": "REDIS_RUNTIME_UNAVAILABLE",
                        "message": "redis runtime is not enabled",
                    }
                ),
            )
        requested_stream = (single_query_value(params, "stream_name") or "").strip()
        stream_names = list(self.STREAM_NAMES)
        if requested_stream:
            if requested_stream not in self.STREAM_NAMES:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "stream_name is not supported",
                        }
                    ),
                )
            stream_names = [requested_stream]
        include_empty = optional_bool(single_query_value(params, "include_empty"))
        if include_empty is None:
            include_empty = True
        status = (single_query_value(params, "status") or "").strip().lower()
        if status and status not in {"empty", "fresh", "stale"}:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "status must be empty, fresh, or stale",
                    }
                ),
            )
        raw_stale_only = (single_query_value(params, "stale_only") or "").strip()
        stale_only = optional_bool(raw_stale_only)
        if raw_stale_only and stale_only is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "stale_only must be true or false",
                    }
                ),
            )
        sort_by = (single_query_value(params, "sort_by") or "").strip()
        if not sort_by:
            sort_by = "stream_name"
        if sort_by not in {"stream_name", "length", "newest_age_seconds"}:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "sort_by must be stream_name, length, or newest_age_seconds",
                    }
                ),
            )
        order = (single_query_value(params, "order") or "").strip().lower()
        if not order:
            order = "asc"
        if order not in {"asc", "desc"}:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "order must be asc or desc",
                    }
                ),
            )
        stale_after_seconds = self._stale_after_seconds(params)
        if stale_after_seconds is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "stale_after_seconds must be a non-negative integer",
                    }
                ),
            )
        limit = self._limit_value(params)
        if limit is None and single_query_value(params, "limit") is not None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "limit must be an integer between 1 and 5",
                    }
                ),
            )
        items: list[dict[str, object]] = []
        for stream_name in stream_names:
            summary = self.server.redis_runtime.get_stream_summary(stream_name=stream_name)
            if summary is None:
                return (
                    HTTPStatus.BAD_GATEWAY,
                    self._response(
                        error={
                            "code": "REDIS_RUNTIME_READ_FAILED",
                            "message": f"failed to read stream summary: {stream_name}",
                        }
                    ),
                )
            self._annotate_stream_summary(summary, stale_after_seconds=stale_after_seconds)
            if not include_empty and int(summary.get("length") or 0) == 0:
                continue
            if stale_only is True and summary.get("is_stale") is not True:
                continue
            if status and summary.get("status") != status:
                continue
            items.append(summary)
        reverse = order == "desc"
        if sort_by == "stream_name":
            items.sort(key=lambda item: str(item.get("stream_name") or ""), reverse=reverse)
        elif sort_by == "length":
            items.sort(
                key=lambda item: (int(item.get("length") or 0), str(item.get("stream_name") or "")),
                reverse=reverse,
            )
        else:
            items.sort(
                key=lambda item: self._newest_age_sort_key(item, reverse=reverse),
            )
        matched_count = len(items)
        if limit is not None:
            items = items[:limit]
        total_length = sum(int(item.get("length") or 0) for item in items)
        non_empty_count = sum(1 for item in items if int(item.get("length") or 0) > 0)
        stale_count = sum(1 for item in items if item.get("is_stale") is True)
        return HTTPStatus.OK, self._response(
            data={
                "items": items,
                "count": len(items),
                "matched_count": matched_count,
                "non_empty_count": non_empty_count,
                "total_length": total_length,
                "stale_after_seconds": stale_after_seconds,
                "stale_count": stale_count,
                "stale_only": stale_only is True,
                "status": status or None,
                "limit": limit,
                "has_more": matched_count > len(items),
                "sort_by": sort_by,
                "order": order,
            }
        )

    def _limit_value(self, params: dict[str, list[str]]) -> int | None:
        raw = (single_query_value(params, "limit") or "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        if value < 1 or value > len(self.STREAM_NAMES):
            return None
        return value

    def _stale_after_seconds(self, params: dict[str, list[str]]) -> int | None:
        raw = (single_query_value(params, "stale_after_seconds") or "").strip()
        if not raw:
            return 300
        try:
            value = int(raw)
        except ValueError:
            return None
        if value < 0:
            return None
        return value

    def _annotate_stream_summary(
        self, summary: dict[str, object], *, stale_after_seconds: int
    ) -> None:
        length = int(summary.get("length") or 0)
        occurred_at = summary.get("newest_occurred_at")
        if not isinstance(occurred_at, str) or not occurred_at:
            summary["newest_age_seconds"] = None
            summary["is_stale"] = None
            summary["status"] = "empty" if length == 0 else "fresh"
            return
        newest_at = self._parse_iso_datetime(occurred_at)
        if newest_at is None:
            summary["newest_age_seconds"] = None
            summary["is_stale"] = None
            summary["status"] = "empty" if length == 0 else "fresh"
            return
        age_seconds = max(
            0,
            int((datetime.now(UTC) - newest_at).total_seconds()),
        )
        summary["newest_age_seconds"] = age_seconds
        summary["is_stale"] = age_seconds > stale_after_seconds
        if length == 0:
            summary["status"] = "empty"
        elif summary["is_stale"] is True:
            summary["status"] = "stale"
        else:
            summary["status"] = "fresh"

    def _newest_age_sort_key(
        self, item: dict[str, object], *, reverse: bool
    ) -> tuple[bool, int, str]:
        age = item.get("newest_age_seconds")
        stream_name = str(item.get("stream_name") or "")
        if not isinstance(age, int):
            return (True, 0, stream_name)
        if reverse:
            return (False, -age, stream_name)
        return (False, age, stream_name)

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
