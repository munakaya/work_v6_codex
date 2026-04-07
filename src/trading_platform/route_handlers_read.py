from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from http import HTTPStatus
from urllib.parse import parse_qs

from .request_utils import optional_bool, query_limit, single_query_value
from .storage.dependencies import postgres_status, private_execution_status, redis_status


class ControlPlaneReadRouteMixin:
    def _parse_iso_datetime(self, value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _cached_age_seconds(self, item: dict[str, object], now: datetime) -> int | None:
        cached_at = self._parse_iso_datetime(item.get("cached_at"))
        if cached_at is None:
            return None
        age_seconds = int((now - cached_at).total_seconds())
        return max(0, age_seconds)

    def _annotate_latest_strategy_evaluations(
        self,
        evaluations: list[dict[str, object]],
        *,
        now: datetime,
        stale_after_seconds: int | None,
    ) -> list[dict[str, object]]:
        annotated: list[dict[str, object]] = []
        for item in evaluations:
            enriched = dict(item)
            cached_age_seconds = self._cached_age_seconds(item, now)
            enriched["cached_age_seconds"] = cached_age_seconds
            enriched["is_stale"] = (
                None
                if stale_after_seconds is None or cached_age_seconds is None
                else cached_age_seconds > stale_after_seconds
            )
            annotated.append(enriched)
        return annotated

    def _latest_strategy_evaluation_summary(
        self,
        evaluations: list[dict[str, object]],
        *,
        now: datetime,
        stale_after_seconds: int | None,
    ) -> dict[str, object]:
        accepted_count = 0
        rejected_count = 0
        reason_counts: Counter[str] = Counter()
        lifecycle_counts: Counter[str] = Counter()
        bot_ids: set[str] = set()
        stale_count = 0
        for item in evaluations:
            accepted = item.get("accepted")
            if accepted is True:
                accepted_count += 1
            elif accepted is False:
                rejected_count += 1
            bot_id = str(item.get("bot_id") or "").strip()
            if bot_id:
                bot_ids.add(bot_id)
            reason_code = str(item.get("reason_code") or "").strip()
            if reason_code:
                reason_counts[reason_code] += 1
            lifecycle_preview = str(item.get("lifecycle_preview") or "").strip()
            if lifecycle_preview:
                lifecycle_counts[lifecycle_preview] += 1
            cached_age_seconds = self._cached_age_seconds(item, now)
            if (
                stale_after_seconds is not None
                and cached_age_seconds is not None
                and cached_age_seconds > stale_after_seconds
            ):
                stale_count += 1
        return {
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "unique_bot_count": len(bot_ids),
            "newest_cached_at": (
                str(evaluations[0].get("cached_at")) if evaluations else None
            ),
            "oldest_cached_at": (
                str(evaluations[-1].get("cached_at")) if evaluations else None
            ),
            "stale_after_seconds": stale_after_seconds,
            "stale_count": stale_count if stale_after_seconds is not None else None,
            "reason_code_counts": dict(reason_counts),
            "lifecycle_preview_counts": dict(lifecycle_counts),
        }

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
            "private_execution": private_execution_status(
                execution_enabled=config.strategy_runtime_execution_enabled,
                execution_mode=config.strategy_runtime_execution_mode,
                submit_url=config.strategy_private_execution_url,
                health_url=config.strategy_private_execution_health_url,
                token=config.strategy_private_execution_token,
                timeout_ms=config.strategy_private_execution_timeout_ms,
            ).as_dict(),
        }
        required_dependency_names = ["postgres", "redis"]
        if (
            config.strategy_runtime_execution_enabled
            and config.strategy_runtime_execution_mode.strip().lower() == "private_http"
        ):
            required_dependency_names.append("private_execution")
        dependency_ready = all(
            bool(dependencies[name]["configured"]) and bool(dependencies[name]["reachable"])
            for name in required_dependency_names
        )
        redis_runtime_ready = self.server.redis_runtime.info.enabled
        read_store_ready = self.server.store_bootstrap.mode == "postgres"
        ready = dependency_ready and redis_runtime_ready and read_store_ready
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        payload = self._response(
            data={
                "status": "ok" if ready else "degraded",
                "service": config.service_name,
                "redis_key_prefix": config.redis_key_prefix,
                "redis_runtime": self.server.redis_runtime.info.as_dict(),
                "market_data_runtime": self.server.market_data_runtime.info.as_dict(),
                "strategy_runtime": self.server.strategy_runtime.info.as_dict(),
                "recovery_runtime": self.server.recovery_runtime.info.as_dict(),
                "read_store": self.server.store_bootstrap.as_dict(),
                "dependencies": dependencies,
                "readiness_checks": {
                    "dependencies_ready": dependency_ready,
                    "redis_runtime_ready": redis_runtime_ready,
                    "read_store_ready": read_store_ready,
                },
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

    def _config_versions_response(
        self, versions: list[dict[str, object]]
    ) -> dict[str, object]:
        return self._response(data={"items": versions, "count": len(versions)})

    def _strategy_runs_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        runs = self.server.read_store.list_strategy_runs(
            bot_id=single_query_value(params, "bot_id"),
            status=single_query_value(params, "status"),
            mode=single_query_value(params, "mode"),
        )
        return self._response(data={"items": runs, "count": len(runs)})

    def _latest_strategy_evaluations_response(
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
        accepted_param = single_query_value(params, "accepted")
        accepted = optional_bool(accepted_param)
        if accepted_param is not None and accepted is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "accepted must be true or false",
                    }
                ),
            )
        stale_after_param = single_query_value(params, "stale_after_seconds")
        stale_after_seconds: int | None = None
        if stale_after_param is not None:
            try:
                stale_after_seconds = int(stale_after_param)
            except ValueError:
                stale_after_seconds = None
            if stale_after_seconds is None or stale_after_seconds < 0:
                return (
                    HTTPStatus.BAD_REQUEST,
                    self._response(
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "stale_after_seconds must be a non-negative integer",
                        }
                    ),
                )
        stale_only_param = single_query_value(params, "stale_only")
        stale_only = optional_bool(stale_only_param)
        if stale_only_param is not None and stale_only is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "stale_only must be true or false",
                    }
                ),
            )
        if stale_only and stale_after_seconds is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "stale_after_seconds is required when stale_only=true",
                    }
                ),
            )
        evaluations = self.server.redis_runtime.list_arbitrage_evaluations(
            limit=100,
            bot_id=single_query_value(params, "bot_id"),
            accepted=accepted,
            lifecycle_preview=single_query_value(params, "lifecycle_preview"),
            reason_code=single_query_value(params, "reason_code"),
        )
        if evaluations is None:
            return (
                HTTPStatus.BAD_GATEWAY,
                self._response(
                    error={
                        "code": "REDIS_RUNTIME_READ_FAILED",
                        "message": "failed to read latest strategy evaluations",
                    }
                ),
            )
        now = datetime.now(UTC)
        annotated = self._annotate_latest_strategy_evaluations(
            evaluations,
            now=now,
            stale_after_seconds=stale_after_seconds,
        )
        filtered = (
            [item for item in annotated if item.get("is_stale") is True]
            if stale_only
            else annotated
        )
        limited = filtered[: query_limit(params)]
        return HTTPStatus.OK, self._response(
            data={
                "items": limited,
                "count": len(limited),
                "matched_count": len(filtered),
                **self._latest_strategy_evaluation_summary(
                    filtered,
                    now=now,
                    stale_after_seconds=stale_after_seconds,
                ),
            }
        )

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

    def _orders_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        orders = self.server.read_store.list_orders(
            bot_id=single_query_value(params, "bot_id"),
            exchange_name=single_query_value(params, "exchange_name")
            or single_query_value(params, "exchange"),
            status=single_query_value(params, "status"),
            market=single_query_value(params, "market")
            or single_query_value(params, "canonical_symbol"),
            strategy_run_id=single_query_value(params, "strategy_run_id"),
            created_from=single_query_value(params, "from"),
            created_to=single_query_value(params, "to"),
        )
        return self._response(data={"items": orders, "count": len(orders)})

    def _fills_response(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        fills = self.server.read_store.list_fills(
            bot_id=single_query_value(params, "bot_id"),
            exchange_name=single_query_value(params, "exchange_name")
            or single_query_value(params, "exchange"),
            market=single_query_value(params, "market")
            or single_query_value(params, "canonical_symbol"),
            strategy_run_id=single_query_value(params, "strategy_run_id"),
            order_id=single_query_value(params, "order_id"),
            created_from=single_query_value(params, "from"),
            created_to=single_query_value(params, "to"),
        )
        return self._response(data={"items": fills, "count": len(fills)})

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

    def _match_config_versions(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/configs/"
        suffix = "/versions"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        config_scope = path[len(prefix) : -len(suffix)]
        if not config_scope:
            return None

        versions = self.server.read_store.list_config_versions(config_scope)
        if not versions:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "CONFIG_NOT_FOUND",
                        "message": "config scope not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._config_versions_response(versions)

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

    def _match_latest_strategy_evaluation(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/strategy-runs/"
        suffix = "/latest-evaluation"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        run_id = path[len(prefix) : -len(suffix)]
        if not run_id:
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

        evaluation = self.server.redis_runtime.get_arbitrage_evaluation(run_id=run_id)
        if evaluation is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_EVALUATION_NOT_FOUND",
                        "message": "latest strategy evaluation not found",
                    }
                ),
            )
        return HTTPStatus.OK, self._response(data=evaluation)

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

    def _match_order_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/orders/"
        if not path.startswith(prefix):
            return None

        order_id = path[len(prefix) :]
        if not order_id or "/" in order_id:
            return None

        order = self.server.read_store.get_order_detail(order_id)
        if order is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "ORDER_NOT_FOUND", "message": "order_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data=order)

    def _match_alert_detail(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/alerts/"
        if not path.startswith(prefix):
            return None

        alert_id = path[len(prefix) :]
        if not alert_id or "/" in alert_id:
            return None

        alert = self.server.read_store.get_alert_detail(alert_id)
        if alert is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "ALERT_NOT_FOUND", "message": "alert_id not found"}
                ),
            )
        return HTTPStatus.OK, self._response(data=alert)
