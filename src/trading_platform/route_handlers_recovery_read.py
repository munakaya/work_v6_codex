from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs

from .request_utils import query_limit, single_query_value


class ControlPlaneRecoveryReadRouteMixin:
    def _recovery_traces_response(
        self, query: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
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
        params = parse_qs(query)
        traces = self.server.redis_runtime.list_recovery_traces(
            limit=query_limit(params),
            bot_id=single_query_value(params, "bot_id"),
            run_id=single_query_value(params, "run_id"),
            status=single_query_value(params, "status"),
            lifecycle_state=single_query_value(params, "lifecycle_state"),
        )
        if traces is None:
            return (
                HTTPStatus.BAD_GATEWAY,
                self._response(
                    error={
                        "code": "REDIS_RECOVERY_TRACE_READ_FAILED",
                        "message": "failed to read recovery trace list",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data={"items": traces, "count": len(traces)})

    def _match_recovery_trace_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/recovery-traces/"
        if not path.startswith(prefix):
            return None
        recovery_trace_id = path.removeprefix(prefix)
        if not recovery_trace_id:
            return None
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
        item = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        if item is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_NOT_FOUND",
                        "message": "recovery_trace_id not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=item)
