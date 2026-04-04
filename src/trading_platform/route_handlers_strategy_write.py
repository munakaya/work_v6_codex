from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus

from .request_utils import json_bool, json_string, optional_object
from .strategy_runtime_execution import execute_persisted_arbitrage_intent
from .strategy import (
    build_arbitrage_evaluation_payload,
    evaluate_arbitrage,
    load_strategy_inputs,
    persist_order_intent_plan,
)


class ControlPlaneStrategyWriteRouteMixin:
    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _split_symbol_assets(self, canonical_symbol: str) -> tuple[str, str]:
        parts = canonical_symbol.split("-")
        if len(parts) == 2 and all(parts):
            return parts[0], parts[1]
        return canonical_symbol, "QUOTE"

    def _normalize_evaluate_arbitrage_payload(
        self,
        *,
        canonical_symbol: str,
        market: str,
        base_exchange: str,
        hedge_exchange: str,
        base_orderbook: dict[str, object],
        hedge_orderbook: dict[str, object],
        base_balance: dict[str, object],
        hedge_balance: dict[str, object],
        risk_config: dict[str, object],
        runtime_state: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        now_iso = self._now_iso()
        base_asset, quote_asset = self._split_symbol_assets(canonical_symbol)
        normalized_base_orderbook = {
            "exchange_name": base_exchange,
            "market": market,
            "observed_at": now_iso,
            **base_orderbook,
        }
        normalized_hedge_orderbook = {
            "exchange_name": hedge_exchange,
            "market": market,
            "observed_at": now_iso,
            **hedge_orderbook,
        }
        normalized_base_balance = {
            "exchange_name": base_exchange,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "observed_at": now_iso,
            "is_fresh": True,
            **base_balance,
        }
        normalized_hedge_balance = {
            "exchange_name": hedge_exchange,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "observed_at": now_iso,
            "is_fresh": True,
            **hedge_balance,
        }
        normalized_risk_config = {
            "min_profit_bps": "0",
            "max_clock_skew_ms": 1000,
            "max_orderbook_age_ms": 3000,
            "max_balance_age_ms": 3000,
            "max_notional_per_order": risk_config.get("max_quote_notional", "1000000"),
            "max_total_notional_per_bot": risk_config.get("max_quote_notional", "1000000"),
            **risk_config,
        }
        normalized_runtime_state = {
            "now": now_iso,
            "open_order_count": 0,
            "open_order_cap": 0,
            "unwind_in_progress": False,
            "connector_private_healthy": True,
            "duplicate_intent_active": False,
            **runtime_state,
        }
        return (
            normalized_base_orderbook,
            normalized_hedge_orderbook,
            normalized_base_balance,
            normalized_hedge_balance,
            normalized_risk_config,
            normalized_runtime_state,
        )

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
        execute = json_bool(body.get("execute"))
        if "execute" in body and execute is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "execute must be boolean",
                    }
                ),
            )
        execute = bool(execute)
        persist_intent = bool(persist_intent)
        if execute and not persist_intent:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "execute requires persist_intent=true",
                    }
                ),
            )
        if persist_intent:
            unsupported = self._ensure_mutation_supported()
            if unsupported is not None:
                return unsupported
        if execute and not self.server.strategy_runtime.execution_enabled:
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "STRATEGY_EXECUTION_DISABLED",
                        "message": "strategy runtime execution is disabled",
                    }
                ),
            )

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

        (
            normalized_base_orderbook,
            normalized_hedge_orderbook,
            normalized_base_balance,
            normalized_hedge_balance,
            normalized_risk_config,
            normalized_runtime_state,
        ) = self._normalize_evaluate_arbitrage_payload(
            canonical_symbol=required_strings["canonical_symbol"],
            market=required_strings["market"],
            base_exchange=required_strings["base_exchange"],
            hedge_exchange=required_strings["hedge_exchange"],
            base_orderbook=required_objects["base_orderbook"],
            hedge_orderbook=required_objects["hedge_orderbook"],
            base_balance=required_objects["base_balance"],
            hedge_balance=required_objects["hedge_balance"],
            risk_config=required_objects["risk_config"],
            runtime_state=required_objects["runtime_state"],
        )

        payload = {
            "bot_id": str(run.get("bot_id")),
            "strategy_run_id": run_id,
            "canonical_symbol": required_strings["canonical_symbol"],
            "market": required_strings["market"],
            "base_exchange": required_strings["base_exchange"],
            "hedge_exchange": required_strings["hedge_exchange"],
            "base_orderbook": normalized_base_orderbook,
            "hedge_orderbook": normalized_hedge_orderbook,
            "base_balance": normalized_base_balance,
            "hedge_balance": normalized_hedge_balance,
            "risk_config": normalized_risk_config,
            "runtime_state": {
                **normalized_runtime_state,
                "bot_id": str(run.get("bot_id")),
                "strategy_run_id": run_id,
            },
        }
        try:
            decision = evaluate_arbitrage(load_strategy_inputs(payload))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"invalid arbitrage evaluation payload: {exc}",
                    }
                ),
            )
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
                "execute": execute,
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
        if execute:
            execution_outcome = execute_persisted_arbitrage_intent(
                store=self.server.read_store,
                redis_runtime=self.server.redis_runtime,
                decision=decision,
                intent=intent,
                run_id=run_id,
                bot_id=str(run.get("bot_id")),
                trace_id=self.headers.get("X-Trace-Id") or f"http-eval-{run_id}",
                execution_adapter=self.server.strategy_runtime.execution_adapter,
                auto_unwind_on_failure=self.server.strategy_runtime.auto_unwind_on_failure,
                payload_builder=build_arbitrage_evaluation_payload,
            )
            response_data = execution_outcome.latest_payload
        return HTTPStatus.CREATED, self._response(data=response_data)
