from __future__ import annotations

from http import HTTPStatus

from .request_utils import json_bool, json_string, optional_object
from .strategy import (
    build_arbitrage_evaluation_payload,
    evaluate_arbitrage,
    load_strategy_inputs,
    persist_order_intent_plan,
)


class ControlPlaneStrategyWriteRouteMixin:
    def _evaluate_arbitrage_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/strategy-runs/"
        suffix = "/evaluate-arbitrage"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        run_id = path[len(prefix) : -len(suffix)]
        if not run_id:
            return None

        body, error = self._read_json_body()
        if error is not None:
            return error

        run = self.server.read_store.get_strategy_run(run_id)
        if run is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_NOT_FOUND",
                        "message": "run_id not found",
                    }
                ),
            )

        if str(run.get("strategy_name")) != "arbitrage":
            return (
                HTTPStatus.UNPROCESSABLE_ENTITY,
                self._response(
                    error={
                        "code": "STRATEGY_NOT_SUPPORTED",
                        "message": "evaluate-arbitrage is only supported for arbitrage runs",
                    }
                ),
            )

        persist_intent = json_bool(body.get("persist_intent"))
        if "persist_intent" in body and persist_intent is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "persist_intent must be boolean",
                    }
                ),
            )
        persist_intent = bool(persist_intent)
        if persist_intent:
            unsupported = self._ensure_mutation_supported()
            if unsupported is not None:
                return unsupported

        required_objects = {
            "base_orderbook": optional_object(body.get("base_orderbook")),
            "hedge_orderbook": optional_object(body.get("hedge_orderbook")),
            "base_balance": optional_object(body.get("base_balance")),
            "hedge_balance": optional_object(body.get("hedge_balance")),
            "risk_config": optional_object(body.get("risk_config")),
            "runtime_state": optional_object(body.get("runtime_state")),
        }
        missing_objects = [key for key, value in required_objects.items() if value is None]
        required_strings = {
            "canonical_symbol": json_string(body.get("canonical_symbol")),
            "market": json_string(body.get("market")),
            "base_exchange": json_string(body.get("base_exchange")),
            "hedge_exchange": json_string(body.get("hedge_exchange")),
        }
        missing_strings = [key for key, value in required_strings.items() if not value]
        if missing_objects or missing_strings:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "missing required fields: "
                        + ", ".join(missing_objects + missing_strings),
                    }
                ),
            )

        payload = {
            "bot_id": str(run.get("bot_id")),
            "strategy_run_id": run_id,
            "canonical_symbol": required_strings["canonical_symbol"],
            "market": required_strings["market"],
            "base_exchange": required_strings["base_exchange"],
            "hedge_exchange": required_strings["hedge_exchange"],
            "base_orderbook": required_objects["base_orderbook"],
            "hedge_orderbook": required_objects["hedge_orderbook"],
            "base_balance": required_objects["base_balance"],
            "hedge_balance": required_objects["hedge_balance"],
            "risk_config": required_objects["risk_config"],
            "runtime_state": {
                **required_objects["runtime_state"],
                "bot_id": str(run.get("bot_id")),
                "strategy_run_id": run_id,
            },
        }
        decision = evaluate_arbitrage(load_strategy_inputs(payload))
        response_data = build_arbitrage_evaluation_payload(
            decision=decision,
            bot_id=str(run.get("bot_id")),
            strategy_run_id=run_id,
        )

        self._sync_arbitrage_evaluation(run_id, response_data)
        self._publish_strategy_event(
            "strategy.arbitrage_evaluated",
            {
                "run_id": run_id,
                "bot_id": run.get("bot_id"),
                "accepted": decision.accepted,
                "reason_code": decision.reason_code,
                "lifecycle_preview": response_data.get("lifecycle_preview"),
                "persist_intent": persist_intent,
            },
        )

        if not persist_intent:
            return HTTPStatus.OK, self._response(data=response_data)

        outcome, intent = persist_order_intent_plan(
            store=self.server.read_store,
            decision=decision,
            strategy_run_id=run_id,
        )
        if outcome == "rejected":
            return HTTPStatus.OK, self._response(data=response_data)
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_NOT_FOUND",
                        "message": "strategy_run_id not found during persistence",
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
        self._publish_strategy_event(
            "strategy.arbitrage_intent_persisted",
            {
                "run_id": run_id,
                "bot_id": run.get("bot_id"),
                "intent_id": intent.get("intent_id"),
                "market": intent.get("market"),
            },
        )
        response_data = build_arbitrage_evaluation_payload(
            decision=decision,
            bot_id=str(run.get("bot_id")),
            strategy_run_id=run_id,
            persisted_intent=intent,
        )
        self._sync_arbitrage_evaluation(run_id, response_data)
        return HTTPStatus.CREATED, self._response(data=response_data)
