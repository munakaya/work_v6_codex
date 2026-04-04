from __future__ import annotations

from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from .request_utils import (
    is_nonnegative_number_text,
    json_number_text,
    optional_object,
    optional_string,
)


class ControlPlaneRecoveryWriteRouteMixin:
    def _is_zero_number_text(self, value: str | None) -> bool:
        if value is None:
            return False
        try:
            return Decimal(value) == Decimal("0")
        except (InvalidOperation, ValueError):
            return False

    def _recovery_trace_action_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/recovery-traces/"
        if not path.startswith(prefix):
            return None
        suffixes = {
            "/resolve": self._resolve_recovery_trace_response,
            "/handoff": self._handoff_recovery_trace_response,
            "/start-unwind": self._start_unwind_recovery_trace_response,
        }
        for suffix, handler in suffixes.items():
            if not path.endswith(suffix):
                continue
            recovery_trace_id = path[len(prefix) : -len(suffix)]
            if not recovery_trace_id:
                return None
            return handler(recovery_trace_id)
        return None

    def _read_optional_body(self) -> tuple[dict[str, object], tuple[HTTPStatus, dict[str, object]] | None]:
        if not self.headers.get("Content-Length"):
            return {}, None
        return self._read_json_body()

    def _resolve_recovery_trace_response(
        self, recovery_trace_id: str
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
        body, error = self._read_optional_body()
        if error is not None:
            return error
        residual_exposure_quote = json_number_text(body.get("residual_exposure_quote"))
        if "residual_exposure_quote" in body and residual_exposure_quote is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "residual_exposure_quote must be a finite number",
                    }
                ),
            )
        current = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        if current is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_NOT_FOUND",
                        "message": "recovery_trace_id not found",
                    }
                ),
            )
        effective_residual = residual_exposure_quote
        if effective_residual is None:
            effective_residual = optional_string(current.get("residual_exposure_quote"))
        if not self._is_zero_number_text(effective_residual):
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_RESIDUAL_EXPOSURE_ACTIVE",
                        "message": "recovery trace cannot be resolved while residual exposure remains",
                    }
                ),
            )
        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="resolved",
            lifecycle_state="closed",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "manual_handoff_required": False,
                "residual_exposure_quote": effective_residual,
                "resolution_reason": optional_string(body.get("resolution_reason"))
                or "operator_resolved",
                "verified_by": optional_string(body.get("verified_by")),
                "summary": optional_string(body.get("summary")),
                "closed_at": self.server.redis_runtime.now_iso(),
            },
            event_type="strategy.recovery_trace.resolved_by_operator",
        )
        if trace is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_NOT_FOUND",
                        "message": "recovery_trace_id not found",
                    }
                ),
            )
        if trace.get("_conflict") == "terminal":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_TERMINAL",
                        "message": "recovery trace is already terminal",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=trace)

    def _handoff_recovery_trace_response(
        self, recovery_trace_id: str
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
        body, error = self._read_optional_body()
        if error is not None:
            return error
        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="handoff_required",
            lifecycle_state="manual_handoff",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "manual_handoff_required": True,
                "incident_code": "ARB-302 MANUAL_HANDOFF_REQUIRED",
                "handoff_reason": optional_string(body.get("handoff_reason"))
                or "operator_requested",
                "verified_by": optional_string(body.get("verified_by")),
                "summary": optional_string(body.get("summary")),
                "operator_context": optional_object(body.get("operator_context")),
            },
            event_type="strategy.recovery_trace.handoff_requested",
        )
        if trace is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_NOT_FOUND",
                        "message": "recovery_trace_id not found",
                    }
                ),
            )
        if trace.get("_conflict") == "terminal":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_TERMINAL",
                        "message": "recovery trace is already terminal",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=trace)

    def _start_unwind_recovery_trace_response(
        self, recovery_trace_id: str
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
        body, error = self._read_optional_body()
        if error is not None:
            return error
        residual_exposure_quote = json_number_text(body.get("residual_exposure_quote"))
        if "residual_exposure_quote" in body and (
            residual_exposure_quote is None
            or not is_nonnegative_number_text(residual_exposure_quote)
        ):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "residual_exposure_quote must be a finite non-negative number",
                    }
                ),
            )
        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="active",
            lifecycle_state="unwind_in_progress",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "manual_handoff_required": False,
                "incident_code": "ARB-202 UNWIND_IN_PROGRESS",
                "unwind_reason": optional_string(body.get("unwind_reason"))
                or "operator_requested",
                "verified_by": optional_string(body.get("verified_by")),
                "summary": optional_string(body.get("summary")),
                "operator_context": optional_object(body.get("operator_context")),
                "residual_exposure_quote": residual_exposure_quote,
                "unwind_started_at": self.server.redis_runtime.now_iso(),
            },
            event_type="strategy.recovery_trace.unwind_started",
        )
        if trace is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_NOT_FOUND",
                        "message": "recovery_trace_id not found",
                    }
                ),
            )
        if trace.get("_conflict") == "terminal":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_TERMINAL",
                        "message": "recovery trace is already terminal",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=trace)
