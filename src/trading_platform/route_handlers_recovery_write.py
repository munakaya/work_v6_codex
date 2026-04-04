from __future__ import annotations

from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from .request_utils import (
    is_nonnegative_number_text,
    is_positive_number_text,
    json_number_text,
    optional_object,
    optional_bool,
    optional_string,
    json_string,
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
            "/submit-unwind-order": self._submit_unwind_order_response,
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
        create_unwind_intent_param = optional_bool(optional_string(body.get("create_unwind_intent")))
        if "create_unwind_intent" in body and create_unwind_intent_param is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "create_unwind_intent must be true or false",
                    }
                ),
            )
        create_unwind_intent = bool(create_unwind_intent_param)
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
        current_status = str(current.get("status") or "").strip().lower()
        if current_status in {"resolved", "cancelled"}:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_TERMINAL",
                        "message": "recovery trace is already terminal",
                    }
                ),
            )
        unwind_intent = None
        unwind_intent_patch: dict[str, object] = {}
        if create_unwind_intent:
            unsupported = self._ensure_mutation_supported()
            if unsupported is not None:
                return unsupported
            existing_linked_id = optional_string(current.get("linked_unwind_action_id"))
            if existing_linked_id:
                return (
                    HTTPStatus.CONFLICT,
                    self._response(
                        error={
                            "code": "RECOVERY_TRACE_UNWIND_INTENT_EXISTS",
                            "message": "recovery trace already has a linked unwind action",
                        }
                    ),
                )
            required_fields = {
                "market": json_string(body.get("market")),
                "buy_exchange": json_string(body.get("buy_exchange")),
                "sell_exchange": json_string(body.get("sell_exchange")),
                "side_pair": json_string(body.get("side_pair")),
                "target_qty": json_number_text(body.get("target_qty")),
            }
            invalid_fields = [
                key for key, value in required_fields.items() if key in body and value is None
            ]
            missing = [key for key, value in required_fields.items() if not value]
            if invalid_fields or missing:
                parts: list[str] = []
                if invalid_fields:
                    parts.append("invalid fields: " + ", ".join(sorted(set(invalid_fields))))
                if missing:
                    parts.append("missing required fields: " + ", ".join(missing))
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "; ".join(parts),
                        }
                    ),
                )
            if not is_positive_number_text(required_fields["target_qty"]):
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "target_qty must be a positive number",
                        }
                    ),
                )
            run_id = optional_string(current.get("run_id"))
            if not run_id:
                return (
                    HTTPStatus.CONFLICT,
                    self._response(
                        error={
                            "code": "RECOVERY_TRACE_RUN_ID_MISSING",
                            "message": "recovery trace does not have a strategy run id",
                        }
                    ),
                )
            decision_context = {
                "recovery_action": "manual_unwind",
                "recovery_trace_id": recovery_trace_id,
                "operator_requested": True,
                "operator_context": optional_object(body.get("operator_context")) or {},
            }
            outcome, unwind_intent = self.server.read_store.create_order_intent(
                strategy_run_id=run_id,
                market=required_fields["market"],
                buy_exchange=required_fields["buy_exchange"],
                sell_exchange=required_fields["sell_exchange"],
                side_pair=required_fields["side_pair"],
                target_qty=required_fields["target_qty"],
                expected_profit=None,
                expected_profit_ratio=None,
                status="created",
                decision_context=decision_context,
            )
            if outcome != "created" or unwind_intent is None:
                return (
                    HTTPStatus.CONFLICT,
                    self._response(
                        error={
                            "code": "RECOVERY_TRACE_UNWIND_INTENT_CREATE_FAILED",
                            "message": "failed to create linked unwind intent",
                        }
                    ),
                )
            unwind_intent_patch = {
                "linked_unwind_action_id": unwind_intent.get("intent_id"),
                "linked_unwind_intent_id": unwind_intent.get("intent_id"),
            }
        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="active",
            lifecycle_state="unwind_in_progress",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                **unwind_intent_patch,
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
        data = dict(trace)
        if unwind_intent is not None:
            self._publish_order_event(
                "order_intent.created",
                {
                    "intent_id": unwind_intent.get("intent_id"),
                    "bot_id": unwind_intent.get("bot_id"),
                    "strategy_run_id": unwind_intent.get("strategy_run_id"),
                    "market": unwind_intent.get("market"),
                },
            )
            data["created_unwind_intent"] = unwind_intent
        return HTTPStatus.OK, self._response(data=data)

    def _submit_unwind_order_response(
        self, recovery_trace_id: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported
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
        body, error = self._read_json_body()
        if error is not None:
            return error
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
        current_status = str(current.get("status") or "").strip().lower()
        if current_status in {"resolved", "cancelled"}:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_TERMINAL",
                        "message": "recovery trace is already terminal",
                    }
                ),
            )
        linked_intent_id = optional_string(current.get("linked_unwind_action_id"))
        if not linked_intent_id:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_UNWIND_INTENT_MISSING",
                        "message": "recovery trace does not have a linked unwind intent",
                    }
                ),
            )
        existing_linked_order_id = optional_string(current.get("linked_unwind_order_id"))
        if existing_linked_order_id:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_UNWIND_ORDER_EXISTS",
                        "message": "recovery trace already has a linked unwind order",
                    }
                ),
            )

        required_fields = {
            "exchange_name": json_string(body.get("exchange_name")),
            "market": json_string(body.get("market")),
            "side": json_string(body.get("side")),
            "requested_qty": json_number_text(body.get("requested_qty")),
        }
        invalid_fields = [
            key for key, value in required_fields.items() if key in body and value is None
        ]
        exchange_order_id = json_string(body.get("exchange_order_id"))
        if "exchange_order_id" in body and exchange_order_id is None:
            invalid_fields.append("exchange_order_id")
        requested_price = json_number_text(body.get("requested_price"))
        if "requested_price" in body and requested_price is None:
            invalid_fields.append("requested_price")
        if "raw_payload" in body and optional_object(body.get("raw_payload")) is None:
            invalid_fields.append("raw_payload")
        status = json_string(body.get("status")) or "new"
        if "status" in body and status not in {"new", "partially_filled", "filled", "cancelled", "rejected", "expired"}:
            invalid_fields.append("status")
        side_value = required_fields["side"]
        if side_value is not None and side_value not in {"buy", "sell"}:
            invalid_fields.append("side")
        if invalid_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "invalid fields: " + ", ".join(sorted(set(invalid_fields))),
                    }
                ),
            )
        missing = [key for key, value in required_fields.items() if not value]
        if missing:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"missing required fields: {', '.join(missing)}",
                    }
                ),
            )
        if not is_positive_number_text(required_fields["requested_qty"]):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "requested_qty must be a positive number",
                    }
                ),
            )
        if requested_price is not None and not is_positive_number_text(requested_price):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "requested_price must be a positive number",
                    }
                ),
            )

        outcome, order = self.server.read_store.create_order(
            order_intent_id=linked_intent_id,
            exchange_name=required_fields["exchange_name"],
            exchange_order_id=exchange_order_id,
            market=required_fields["market"],
            side=required_fields["side"],
            requested_price=requested_price,
            requested_qty=required_fields["requested_qty"],
            status=status,
            raw_payload=optional_object(body.get("raw_payload")),
        )
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "ORDER_INTENT_NOT_FOUND",
                        "message": "linked unwind intent not found",
                    }
                ),
            )
        if outcome == "conflict":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "ORDER_CONFLICT",
                        "message": "exchange_name and exchange_order_id already exist",
                    }
                ),
            )
        if outcome == "invalid":
            return (
                HTTPStatus.UNPROCESSABLE_ENTITY,
                self._response(
                    error={
                        "code": "ORDER_VALIDATION_FAILED",
                        "message": "market or exchange_name does not match linked unwind intent",
                    }
                ),
            )

        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="active",
            lifecycle_state="unwind_in_progress",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "linked_unwind_order_id": order.get("order_id"),
                "unwind_order_created_at": self.server.redis_runtime.now_iso(),
            },
            event_type="strategy.recovery_trace.unwind_order_created",
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
        self._publish_order_event(
            "order.created",
            {
                "order_id": order.get("order_id"),
                "order_intent_id": order.get("order_intent_id"),
                "bot_id": order.get("bot_id"),
                "exchange_name": order.get("exchange_name"),
                "status": order.get("status"),
            },
        )
        data = dict(trace)
        data["created_unwind_order"] = order
        return HTTPStatus.CREATED, self._response(data=data)
