from __future__ import annotations

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
            if not include_empty and int(summary.get("length") or 0) == 0:
                continue
            items.append(summary)
        total_length = sum(int(item.get("length") or 0) for item in items)
        non_empty_count = sum(1 for item in items if int(item.get("length") or 0) > 0)
        return HTTPStatus.OK, self._response(
            data={
                "items": items,
                "count": len(items),
                "non_empty_count": non_empty_count,
                "total_length": total_length,
            }
        )
