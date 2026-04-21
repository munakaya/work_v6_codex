from __future__ import annotations

from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from .request_utils import (
    is_nonnegative_number_text,
    is_positive_number_text,
    json_datetime_text,
    json_number_text,
    json_string_list,
    optional_object,
    optional_bool,
    optional_string,
    json_string,
)


class ControlPlaneRecoveryWriteRouteMixin:
    def _unique_string_list(self, value: object) -> list[str] | None:
        values = json_string_list(value)
        if values is None or not isinstance(value, list):
            return None
        return values if len(values) == len(value) else None

    def _observed_balances(
        self, value: object
    ) -> list[dict[str, str]] | None:
        if value is None or not isinstance(value, list):
            return None
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                return None
            exchange_name = json_string(item.get("exchange_name"))
            asset = json_string(item.get("asset"))
            free = json_number_text(item.get("free"))
            locked = json_number_text(item.get("locked"))
            if (
                exchange_name is None
                or asset is None
                or free is None
                or locked is None
                or not is_nonnegative_number_text(free)
                or not is_nonnegative_number_text(locked)
            ):
                return None
            exchange_name = exchange_name.strip()
            asset = asset.strip().upper()
            if not exchange_name or not asset:
                return None
            key = (exchange_name, asset)
            if key in seen:
                return None
            seen.add(key)
            result.append(
                {
                    "exchange_name": exchange_name,
                    "asset": asset,
                    "free": free,
                    "locked": locked,
                }
            )
        return result

    def _observed_order_statuses(
        self, value: object
    ) -> list[dict[str, str]] | None:
        if value is None or not isinstance(value, list):
            return None
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                return None
            order_id = json_string(item.get("order_id"))
            status = json_string(item.get("status"))
            if order_id is None or status is None:
                return None
            order_id = order_id.strip()
            status = status.strip().lower()
            if not order_id or not status:
                return None
            if order_id in seen:
                return None
            seen.add(order_id)
            result.append({"order_id": order_id, "status": status})
        return result

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
            "/cancel-open-orders": self._cancel_open_orders_response,
            "/record-unwind-fill": self._record_unwind_fill_response,
            "/record-reconciliation": self._record_reconciliation_response,
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

    def _cancel_open_orders_response(
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
        body, error = self._read_optional_body()
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
        candidate_orders = self._trace_cancel_candidate_orders(current)
        if not candidate_orders:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_OPEN_ORDER_MISSING",
                        "message": "recovery trace does not have open linked orders to cancel",
                    }
                ),
            )

        cancel_results: list[dict[str, object]] = []
        cancelled_order_ids: list[str] = []
        terminal_order_ids: list[str] = []
        failed_order_ids: list[str] = []
        skipped_order_ids: list[str] = []
        observed_order_statuses: list[dict[str, str]] = []
        updated_orders: list[dict[str, object]] = []

        for order in candidate_orders:
            result = self._cancel_trace_order(order)
            cancel_results.append(result)
            order_id = optional_string(result.get("order_id")) or ""
            observed_status = result.get("observed_status")
            if isinstance(observed_status, dict):
                normalized_observed = self._observed_order_statuses([observed_status])
                if normalized_observed:
                    observed_order_statuses.extend(normalized_observed)
            updated_order = result.get("updated_order")
            if isinstance(updated_order, dict):
                updated_orders.append(updated_order)
                self._publish_order_event(
                    "order.updated",
                    {
                        "order_id": updated_order.get("order_id"),
                        "order_intent_id": updated_order.get("order_intent_id"),
                        "bot_id": updated_order.get("bot_id"),
                        "exchange_name": updated_order.get("exchange_name"),
                        "status": updated_order.get("status"),
                    },
                )
            result_kind = str(result.get("result") or "").strip().lower()
            if result_kind == "cancelled" and order_id:
                cancelled_order_ids.append(order_id)
            elif result_kind == "terminal" and order_id:
                terminal_order_ids.append(order_id)
            elif result_kind == "skipped" and order_id:
                skipped_order_ids.append(order_id)
            elif order_id:
                failed_order_ids.append(order_id)

        remaining_open_order_ids = [
            str(order.get("order_id") or "")
            for order in self._trace_cancel_candidate_orders(current)
            if str(order.get("order_id") or "")
        ]
        trace = self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status=optional_string(current.get("status")) or "active",
            lifecycle_state=(
                optional_string(current.get("lifecycle_state")) or "recovery_required"
            ),
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "cancel_attempted_at": self.server.redis_runtime.now_iso(),
                "cancelled_order_ids": cancelled_order_ids,
                "cancel_terminal_order_ids": terminal_order_ids,
                "cancel_failed_order_ids": failed_order_ids,
                "cancel_skipped_order_ids": skipped_order_ids,
                "cancel_remaining_open_order_ids": remaining_open_order_ids,
                "cancel_observed_order_statuses": observed_order_statuses,
                "cancel_verified_by": optional_string(body.get("verified_by")),
                "cancel_summary": optional_string(body.get("summary"))
                or "operator requested open-order cancellation",
                "cancel_operator_context": optional_object(body.get("operator_context")),
            },
            event_type="strategy.recovery_trace.open_orders_cancel_requested",
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
        if self.server.recovery_runtime.enabled:
            self.server.recovery_runtime.run_once()
        latest_trace = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        run_id = optional_string(current.get("run_id"))
        evaluation_payload = None
        if run_id:
            evaluation_payload = self.server.redis_runtime.get_arbitrage_evaluation(run_id=run_id)
        data = dict(latest_trace) if latest_trace is not None else dict(trace)
        data["cancel_results"] = cancel_results
        data["updated_orders"] = updated_orders
        if evaluation_payload is not None:
            data["latest_evaluation"] = evaluation_payload
        return HTTPStatus.OK, self._response(data=data)

    def _trace_cancel_candidate_orders(
        self, trace: dict[str, object]
    ) -> list[dict[str, object]]:
        bot_id = optional_string(trace.get("bot_id"))
        run_id = optional_string(trace.get("run_id"))
        linked_order_id = optional_string(trace.get("linked_unwind_order_id"))
        intent_ids: list[str] = []
        for key in ("intent_id", "linked_unwind_action_id"):
            intent_id = optional_string(trace.get(key))
            if intent_id and intent_id not in intent_ids:
                intent_ids.append(intent_id)
        if not intent_ids and not linked_order_id:
            return []
        orders = self.server.read_store.list_orders(
            bot_id=bot_id or None,
            strategy_run_id=run_id or None,
        )
        candidates: list[dict[str, object]] = []
        seen_order_ids: set[str] = set()
        for order in orders:
            order_id = optional_string(order.get("order_id"))
            if not order_id or order_id in seen_order_ids:
                continue
            matches_intent = str(order.get("order_intent_id") or "") in intent_ids
            matches_linked_order = bool(linked_order_id and order_id == linked_order_id)
            if not matches_intent and not matches_linked_order:
                continue
            status = str(order.get("status") or "").strip().lower()
            if status in {"filled", "cancelled", "rejected", "expired"}:
                continue
            seen_order_ids.add(order_id)
            candidates.append(order)
        return candidates

    def _cancel_trace_order(self, order: dict[str, object]) -> dict[str, object]:
        order_id = optional_string(order.get("order_id")) or ""
        exchange_name = optional_string(order.get("exchange_name")) or ""
        exchange_order_id = optional_string(order.get("exchange_order_id")) or ""
        market = optional_string(order.get("market")) or ""
        if not exchange_order_id:
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": None,
                "result": "skipped",
                "error_code": "EXCHANGE_ORDER_ID_MISSING",
                "message": "order is missing exchange_order_id",
            }
        if not market:
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "ORDER_MARKET_MISSING",
                "message": "order is missing market",
            }
        connector = self.server.private_exchange_connectors.get(exchange_name)
        if connector is None:
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "PRIVATE_CONNECTOR_UNAVAILABLE",
                "message": f"private connector is unavailable for exchange={exchange_name}",
            }
        response = connector.cancel_order(
            exchange_order_id=exchange_order_id,
            market=market,
        )
        if response.outcome != "ok" or not isinstance(response.data, dict):
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": response.error_code or "CANCEL_REQUEST_FAILED",
                "message": response.reason or "cancel request failed",
            }
        observed_status = optional_string(response.data.get("status"))
        normalized_status = (
            None if observed_status is None else observed_status.strip().lower()
        )
        observed_order_status = (
            None
            if not normalized_status
            else {"order_id": order_id, "status": normalized_status}
        )
        if normalized_status not in {"cancelled", "partially_filled", "filled", "rejected", "expired"}:
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "CANCEL_NOT_CONFIRMED",
                "message": "exchange cancel response did not confirm a terminal order state",
                "observed_status": observed_order_status,
            }
        if normalized_status in {"filled", "partially_filled"}:
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "CANCEL_REQUIRES_RECONCILIATION",
                "message": "cancel response indicates fill activity; wait for reconciliation evidence before changing local order state",
                "observed_status": observed_order_status,
            }
        update_outcome, updated_order = self.server.read_store.update_order_status(
            order_id=order_id,
            status=normalized_status,
        )
        if update_outcome == "not_found":
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "ORDER_NOT_FOUND",
                "message": "order_id not found while updating local status",
                "observed_status": observed_order_status,
            }
        if update_outcome == "invalid":
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "ORDER_STATUS_INVALID",
                "message": f"unsupported local order status: {normalized_status}",
                "observed_status": observed_order_status,
            }
        if update_outcome == "conflict":
            return {
                "order_id": order_id,
                "exchange_name": exchange_name,
                "exchange_order_id": exchange_order_id,
                "result": "failed",
                "error_code": "ORDER_STATUS_CONFLICT",
                "message": "local order is already terminal with a different status",
                "observed_status": observed_order_status,
            }
        result_kind = "cancelled" if normalized_status == "cancelled" else "terminal"
        return {
            "order_id": order_id,
            "exchange_name": exchange_name,
            "exchange_order_id": exchange_order_id,
            "result": result_kind,
            "observed_status": observed_order_status,
            "updated_order": updated_order,
        }

    def _record_unwind_fill_response(
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
        linked_order_id = optional_string(current.get("linked_unwind_order_id"))
        if not linked_order_id:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "RECOVERY_TRACE_UNWIND_ORDER_MISSING",
                        "message": "recovery trace does not have a linked unwind order",
                    }
                ),
            )

        required_fields = {
            "exchange_trade_id": json_string(body.get("exchange_trade_id")),
            "fill_price": json_number_text(body.get("fill_price")),
            "fill_qty": json_number_text(body.get("fill_qty")),
            "filled_at": json_datetime_text(body.get("filled_at")),
        }
        invalid_fields = [
            key for key, value in required_fields.items() if key in body and value is None
        ]
        fee_asset = json_string(body.get("fee_asset"))
        if "fee_asset" in body and fee_asset is None:
            invalid_fields.append("fee_asset")
        fee_amount = json_number_text(body.get("fee_amount"))
        if "fee_amount" in body and fee_amount is None:
            invalid_fields.append("fee_amount")
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
        if not is_positive_number_text(required_fields["fill_price"]):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "fill_price must be a positive number",
                    }
                ),
            )
        if not is_positive_number_text(required_fields["fill_qty"]):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "fill_qty must be a positive number",
                    }
                ),
            )
        if fee_amount is not None and not is_nonnegative_number_text(fee_amount):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "fee_amount must be a non-negative number",
                    }
                ),
            )

        outcome, fill = self.server.read_store.create_fill(
            order_id=linked_order_id,
            exchange_trade_id=required_fields["exchange_trade_id"],
            fill_price=required_fields["fill_price"],
            fill_qty=required_fields["fill_qty"],
            fee_asset=fee_asset,
            fee_amount=fee_amount,
            filled_at=required_fields["filled_at"],
        )
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "ORDER_NOT_FOUND",
                        "message": "linked unwind order not found",
                    }
                ),
            )
        if outcome == "conflict":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "FILL_CONFLICT",
                        "message": "exchange_trade_id already exists for order",
                    }
                ),
            )
        if outcome == "invalid":
            return (
                HTTPStatus.UNPROCESSABLE_ENTITY,
                self._response(
                    error={
                        "code": "FILL_VALIDATION_FAILED",
                        "message": (
                            "fill exceeds requested quantity or order is already terminal"
                        ),
                    }
                ),
            )

        self._publish_order_event(
            "fill.created",
            {
                "fill_id": fill.get("fill_id"),
                "order_id": fill.get("order_id"),
                "order_intent_id": fill.get("order_intent_id"),
                "bot_id": fill.get("bot_id"),
                "exchange_name": fill.get("exchange_name"),
                "order_status": fill.get("order_status"),
            },
        )
        self.server.redis_runtime.transition_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            status="active",
            lifecycle_state="unwind_in_progress",
            trace_id=self.headers.get("X-Trace-Id"),
            patch={
                "manual_handoff_required": False,
                "last_unwind_fill_id": fill.get("fill_id"),
                "last_unwind_fill_at": fill.get("filled_at"),
                "last_unwind_order_status": fill.get("order_status"),
                "residual_exposure_quote": (
                    "0"
                    if str(fill.get("order_status") or "").strip().lower() == "filled"
                    else optional_string(current.get("residual_exposure_quote"))
                ),
            },
            event_type="strategy.recovery_trace.unwind_fill_recorded",
        )
        if self.server.recovery_runtime.enabled:
            self.server.recovery_runtime.run_once()
        latest_trace = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        run_id = optional_string(current.get("run_id"))
        evaluation_payload = None
        if run_id:
            evaluation_payload = self.server.redis_runtime.get_arbitrage_evaluation(
                run_id=run_id
            )
        data = dict(latest_trace) if latest_trace is not None else dict(current)
        data["created_unwind_fill"] = fill
        if evaluation_payload is not None:
            data["latest_evaluation"] = evaluation_payload
        return HTTPStatus.CREATED, self._response(data=data)

    def _record_reconciliation_response(
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
        body, error = self._read_json_body()
        if error is not None:
            return error
        matched_param = optional_bool(optional_string(body.get("matched")))
        if matched_param is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "matched must be true or false",
                    }
                ),
            )
        open_order_count = body.get("open_order_count")
        if not isinstance(open_order_count, int) or isinstance(open_order_count, bool) or open_order_count < 0:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "open_order_count must be a non-negative integer",
                    }
                ),
            )
        residual_exposure_quote = json_number_text(body.get("residual_exposure_quote"))
        if residual_exposure_quote is None or not is_nonnegative_number_text(residual_exposure_quote):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "residual_exposure_quote must be a finite non-negative number",
                    }
                ),
            )
        reconciliation_observed_at = None
        if "observed_at" in body:
            reconciliation_observed_at = json_datetime_text(body.get("observed_at"))
            if reconciliation_observed_at is None:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "observed_at must be an ISO datetime string",
                        }
                    ),
                )
        observed_order_ids = None
        if "observed_order_ids" in body:
            observed_order_ids = self._unique_string_list(body.get("observed_order_ids"))
            if observed_order_ids is None:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "observed_order_ids must be an array of unique non-empty strings",
                        }
                    ),
                )
        observed_fill_ids = None
        if "observed_fill_ids" in body:
            observed_fill_ids = self._unique_string_list(body.get("observed_fill_ids"))
            if observed_fill_ids is None:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "observed_fill_ids must be an array of unique non-empty strings",
                        }
                    ),
                )
        observed_order_statuses = None
        if "observed_order_statuses" in body:
            observed_order_statuses = self._observed_order_statuses(
                body.get("observed_order_statuses")
            )
            if observed_order_statuses is None:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "observed_order_statuses must be an array of unique {order_id, status} objects",
                        }
                    ),
                )
        observed_balances = None
        if "observed_balances" in body:
            observed_balances = self._observed_balances(body.get("observed_balances"))
            if observed_balances is None:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "observed_balances must be an array of unique {exchange_name, asset, free, locked} objects with non-negative numbers",
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
        previous_attempt_count = current.get("reconciliation_attempt_count")
        previous_matched_count = current.get("reconciliation_matched_count")
        previous_mismatch_count = current.get("reconciliation_mismatch_count")
        previous_mismatch_streak = current.get("reconciliation_mismatch_streak")
        reconciliation_attempt_count = (
            int(previous_attempt_count)
            if isinstance(previous_attempt_count, int) and not isinstance(previous_attempt_count, bool)
            else 0
        ) + 1
        reconciliation_matched_count = (
            int(previous_matched_count)
            if isinstance(previous_matched_count, int) and not isinstance(previous_matched_count, bool)
            else 0
        )
        reconciliation_mismatch_count = (
            int(previous_mismatch_count)
            if isinstance(previous_mismatch_count, int) and not isinstance(previous_mismatch_count, bool)
            else 0
        )
        reconciliation_mismatch_streak = (
            int(previous_mismatch_streak)
            if isinstance(previous_mismatch_streak, int) and not isinstance(previous_mismatch_streak, bool)
            else 0
        )
        if matched_param:
            reconciliation_matched_count += 1
            reconciliation_mismatch_streak = 0
        else:
            reconciliation_mismatch_count += 1
            reconciliation_mismatch_streak += 1
        patch = {
            "reconciliation_result": "matched" if matched_param else "mismatch",
            "reconciliation_open_order_count": open_order_count,
            "reconciliation_residual_exposure_quote": residual_exposure_quote,
            "reconciliation_attempt_count": reconciliation_attempt_count,
            "reconciliation_matched_count": reconciliation_matched_count,
            "reconciliation_mismatch_count": reconciliation_mismatch_count,
            "reconciliation_mismatch_streak": reconciliation_mismatch_streak,
            "reconciliation_reason": optional_string(body.get("reconciliation_reason")),
            "reconciliation_summary": optional_string(body.get("summary")),
            "reconciliation_source": optional_string(body.get("source")) or "operator_recorded",
            "reconciliation_observed_at": reconciliation_observed_at,
            "reconciliation_operator_context": optional_object(body.get("operator_context")),
            "reconciliation_observed_order_ids": observed_order_ids,
            "reconciliation_observed_fill_ids": observed_fill_ids,
            "reconciliation_observed_order_statuses": observed_order_statuses,
            "reconciliation_observed_balances": observed_balances,
            "reconciliation_verified_by": optional_string(body.get("verified_by")),
            "reconciliation_updated_at": self.server.redis_runtime.now_iso(),
        }
        self.server.redis_runtime.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload={**current, **patch},
            trace_id=self.headers.get("X-Trace-Id"),
        )
        updated_trace = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        if updated_trace is None:
            return (
                HTTPStatus.BAD_GATEWAY,
                self._response(
                    error={
                        "code": "REDIS_RUNTIME_WRITE_FAILED",
                        "message": "failed to persist reconciliation result",
                    }
                ),
            )
        run_id = optional_string(updated_trace.get("run_id"))
        if run_id:
            self.server.redis_runtime.sync_arbitrage_evaluation_recovery_state(
                run_id=run_id,
                recovery_trace=updated_trace,
                trace_id=self.headers.get("X-Trace-Id"),
            )
        self.server.redis_runtime.append_event(
            "strategy_events",
            event_type="strategy.recovery_trace.reconciliation_recorded",
            payload={
                "recovery_trace_id": recovery_trace_id,
                "run_id": updated_trace.get("run_id"),
                "bot_id": updated_trace.get("bot_id"),
                "matched": matched_param,
                "open_order_count": open_order_count,
                "observed_order_count": len(observed_order_ids or []),
                "observed_fill_count": len(observed_fill_ids or []),
                "observed_order_status_count": len(observed_order_statuses or []),
                "observed_balance_count": len(observed_balances or []),
            },
            trace_id=self.headers.get("X-Trace-Id"),
        )
        if self.server.recovery_runtime.enabled:
            self.server.recovery_runtime.run_once()
        latest_trace = self.server.redis_runtime.get_recovery_trace(
            recovery_trace_id=recovery_trace_id
        )
        evaluation_payload = None
        if run_id:
            evaluation_payload = self.server.redis_runtime.get_arbitrage_evaluation(run_id=run_id)
        data = dict(latest_trace) if latest_trace is not None else dict(updated_trace)
        if evaluation_payload is not None:
            data["latest_evaluation"] = evaluation_payload
        return HTTPStatus.OK, self._response(data=data)
