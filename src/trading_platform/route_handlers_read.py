from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs

from .request_utils import optional_bool, query_limit, single_query_value
from .storage.dependencies import postgres_status, redis_status


class ControlPlaneReadRouteMixin:
    def _health_payload(self) -> dict[str, object]:
        config = self.server.config
        return self._response(
            data={
                "status": "ok",
                "service": config.service_name,
                "version": config.service_version,
            }
        )

    def _ready_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        config = self.server.config
        dependencies = {
            "postgres": postgres_status(config.postgres_dsn).as_dict(),
            "redis": redis_status(config.redis_url).as_dict(),
        }
        ready = all(
            bool(dep["configured"]) and bool(dep["reachable"]) for dep in dependencies.values()
        )
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        payload = self._response(
            data={
                "status": "ok" if ready else "degraded",
                "service": config.service_name,
                "redis_key_prefix": config.redis_key_prefix,
                "dependencies": dependencies,
            }
        )
        return status, payload

    def _bots_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        bots = self.server.read_store.list_bots(
            status=single_query_value(params, "status"),
            strategy_name=single_query_value(params, "strategy_name"),
            mode=single_query_value(params, "mode"),
        )
        return self._response(data={"items": bots, "count": len(bots)})

    def _alerts_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        acknowledged = optional_bool(single_query_value(params, "acknowledged"))
        alerts = self.server.read_store.list_alerts(
            bot_id=single_query_value(params, "bot_id"),
            level=single_query_value(params, "level"),
            acknowledged=acknowledged,
        )
        return self._response(data={"items": alerts, "count": len(alerts)})

    def _strategy_runs_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        runs = self.server.read_store.list_strategy_runs(
            bot_id=single_query_value(params, "bot_id"),
            status=single_query_value(params, "status"),
            mode=single_query_value(params, "mode"),
        )
        return self._response(data={"items": runs, "count": len(runs)})

    def _order_intents_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        intents = self.server.read_store.list_order_intents(
            bot_id=single_query_value(params, "bot_id"),
            strategy_run_id=single_query_value(params, "strategy_run_id"),
            status=single_query_value(params, "status"),
            market=single_query_value(params, "market"),
            created_from=single_query_value(params, "created_from"),
            created_to=single_query_value(params, "created_to"),
        )
        return self._response(data={"items": intents, "count": len(intents)})

    def _match_latest_config(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/configs/"
        suffix = "/latest"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        config_scope = path[len(prefix) : -len(suffix)]
        if not config_scope:
            return None

        version = self.server.read_store.latest_config(config_scope)
        if version is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "CONFIG_NOT_FOUND",
                        "message": "config scope not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=version)

    def _match_strategy_run_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/strategy-runs/"
        if not path.startswith(prefix):
            return None

        run_id = path[len(prefix) :]
        if not run_id or "/" in run_id:
            return None

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
        return HTTPStatus.OK, self._response(data=run)

    def _match_bot_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/bots/"
        if not path.startswith(prefix):
            return None

        suffix = path[len(prefix) :]
        if "/" in suffix or not suffix:
            return None

        detail = self.server.read_store.get_bot_detail(suffix)
        if detail is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data=detail)

    def _match_bot_heartbeats(
        self, path: str, query: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/bots/"
        suffix = "/heartbeats"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        bot_id = path[len(prefix) : -len(suffix)]
        if not bot_id:
            return None

        params = parse_qs(query)
        limit = query_limit(params)
        heartbeats = self.server.read_store.list_heartbeats(bot_id, limit=limit)
        if heartbeats is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data={"items": heartbeats, "count": len(heartbeats)})

    def _match_order_intent_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/order-intents/"
        if not path.startswith(prefix):
            return None

        intent_id = path[len(prefix) :]
        if not intent_id or "/" in intent_id:
            return None

        intent = self.server.read_store.get_order_intent(intent_id)
        if intent is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "ORDER_INTENT_NOT_FOUND",
                        "message": "intent_id not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=intent)
