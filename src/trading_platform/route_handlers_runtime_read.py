from __future__ import annotations

from http import HTTPStatus


class ControlPlaneRuntimeReadRouteMixin:
    STREAM_NAMES = (
        "market_events",
        "bot_events",
        "strategy_events",
        "order_events",
        "alert_events",
    )

    def _runtime_streams_response(self) -> tuple[HTTPStatus, dict[str, object]]:
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
        items: list[dict[str, object]] = []
        for stream_name in self.STREAM_NAMES:
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
            items.append(summary)
        return HTTPStatus.OK, self._response(data={"items": items, "count": len(items)})
