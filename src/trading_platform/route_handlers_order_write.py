from __future__ import annotations

from http import HTTPStatus

from .request_utils import (
    is_nonnegative_number_text,
    is_positive_number_text,
    json_datetime_text,
    json_number_text,
    json_string,
    optional_object,
)


ORDER_INTENT_STATUSES = {
    "created",
    "submitted",
    "cancelled",
    "expired",
    "rejected",
    "simulated",
}

ORDER_STATUSES = {
    "new",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "expired",
}

ORDER_SIDES = {"buy", "sell"}


class ControlPlaneOrderWriteRouteMixin:
    def _create_order_intent_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        required_fields = {
            "strategy_run_id": json_string(body.get("strategy_run_id")),
            "market": json_string(body.get("market")),
            "buy_exchange": json_string(body.get("buy_exchange")),
            "sell_exchange": json_string(body.get("sell_exchange")),
            "side_pair": json_string(body.get("side_pair")),
            "target_qty": json_number_text(body.get("target_qty")),
        }
        invalid_fields = [
            key
            for key, value in required_fields.items()
            if key in body and value is None
        ]
        expected_profit = json_number_text(body.get("expected_profit"))
        expected_profit_ratio = json_number_text(body.get("expected_profit_ratio"))
        if "expected_profit" in body and expected_profit is None:
            invalid_fields.append("expected_profit")
        if "expected_profit_ratio" in body and expected_profit_ratio is None:
            invalid_fields.append("expected_profit_ratio")
        if "decision_context" in body and optional_object(body.get("decision_context")) is None:
            invalid_fields.append("decision_context")
        status = json_string(body.get("status")) or "created"
        if "status" in body and status not in ORDER_INTENT_STATUSES:
            invalid_fields.append("status")
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

        outcome, intent = self.server.read_store.create_order_intent(
            strategy_run_id=required_fields["strategy_run_id"],
            market=required_fields["market"],
            buy_exchange=required_fields["buy_exchange"],
            sell_exchange=required_fields["sell_exchange"],
            side_pair=required_fields["side_pair"],
            target_qty=required_fields["target_qty"],
            expected_profit=expected_profit,
            expected_profit_ratio=expected_profit_ratio,
            status=status,
            decision_context=optional_object(body.get("decision_context")),
        )
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_NOT_FOUND",
                        "message": "strategy_run_id not found",
                    }
                ),
            )
        self._publish_order_event(
            "order_intent.created",
            {
                "intent_id": intent.get("intent_id"),
                "bot_id": intent.get("bot_id"),
                "strategy_run_id": intent.get("strategy_run_id"),
                "market": intent.get("market"),
            },
        )
        return HTTPStatus.CREATED, self._response(data=intent)

    def _create_order_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        required_fields = {
            "order_intent_id": json_string(body.get("order_intent_id")),
            "exchange_name": json_string(body.get("exchange_name")),
            "market": json_string(body.get("market")),
            "side": json_string(body.get("side")),
            "requested_qty": json_number_text(body.get("requested_qty")),
        }
        invalid_fields = [
            key
            for key, value in required_fields.items()
            if key in body and value is None
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
        if "status" in body and status not in ORDER_STATUSES:
            invalid_fields.append("status")
        side_value = required_fields["side"]
        if side_value is not None and side_value not in ORDER_SIDES:
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
            order_intent_id=required_fields["order_intent_id"],
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
                        "message": "order_intent_id not found",
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
                        "message": "market or exchange_name does not match order_intent",
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
        return HTTPStatus.CREATED, self._response(data=order)

    def _create_fill_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        required_fields = {
            "order_id": json_string(body.get("order_id")),
            "fill_price": json_number_text(body.get("fill_price")),
            "fill_qty": json_number_text(body.get("fill_qty")),
            "filled_at": json_datetime_text(body.get("filled_at")),
        }
        invalid_fields = [
            key
            for key, value in required_fields.items()
            if key in body and value is None
        ]
        exchange_trade_id = json_string(body.get("exchange_trade_id"))
        fee_asset = json_string(body.get("fee_asset"))
        fee_amount = json_number_text(body.get("fee_amount"))
        if "exchange_trade_id" in body and exchange_trade_id is None:
            invalid_fields.append("exchange_trade_id")
        if "fee_asset" in body and fee_asset is None:
            invalid_fields.append("fee_asset")
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
            order_id=required_fields["order_id"],
            exchange_trade_id=exchange_trade_id,
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
                        "message": "order_id not found",
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
        return HTTPStatus.CREATED, self._response(data=fill)
