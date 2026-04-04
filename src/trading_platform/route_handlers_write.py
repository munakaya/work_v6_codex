from __future__ import annotations

from http import HTTPStatus

from .request_utils import (
    json_int,
    json_string,
    optional_int,
    optional_object,
    optional_string,
)


class ControlPlaneWriteRouteMixin:
    def _ensure_mutation_supported(self) -> tuple[HTTPStatus, dict[str, object]] | None:
        if self.server.read_store.supports_mutation:
            return None
        return (
            HTTPStatus.NOT_IMPLEMENTED,
            self._response(
                error={
                    "code": "STORE_MUTATION_UNAVAILABLE",
                    "message": (
                        f"write operations are disabled for backend "
                        f"{self.server.read_store.backend_name}"
                    ),
                }
            ),
        )

    def _register_bot_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        required = ["bot_key", "strategy_name", "mode"]
        missing = [key for key in required if not body.get(key)]
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

        result = self.server.read_store.register_bot(
            bot_key=str(body["bot_key"]),
            strategy_name=str(body["strategy_name"]),
            mode=str(body["mode"]),
            hostname=optional_string(body.get("hostname")),
        )
        self._sync_bot_state(str(result["bot_id"]))
        return HTTPStatus.OK, self._response(data=result)

    def _record_heartbeat_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/bots/"
        suffix = "/heartbeat"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        bot_id = path[len(prefix) : -len(suffix)]
        if not bot_id:
            return None

        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        required = [
            "is_process_alive",
            "is_market_data_alive",
            "is_ordering_alive",
        ]
        missing = [key for key in required if key not in body]
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

        invalid_bool_fields = [
            key for key in required if not isinstance(body.get(key), bool)
        ]
        if invalid_bool_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": f"fields must be boolean: {', '.join(invalid_bool_fields)}",
                    }
                ),
            )

        result = self.server.read_store.record_heartbeat(
            bot_id=bot_id,
            is_process_alive=body["is_process_alive"],
            is_market_data_alive=body["is_market_data_alive"],
            is_ordering_alive=body["is_ordering_alive"],
            lag_ms=optional_int(body.get("lag_ms")),
            context=optional_object(body.get("context")),
        )
        if result is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        emitted_alert = self._emit_heartbeat_alert_if_needed(
            bot_id=bot_id,
            is_process_alive=body["is_process_alive"],
            is_market_data_alive=body["is_market_data_alive"],
            is_ordering_alive=body["is_ordering_alive"],
        )
        if emitted_alert is not None:
            self.server.metrics.observe_alert_emitted(emitted_alert["level"])
            self._publish_alert_event(
                "alert.emitted",
                {
                    "alert_id": emitted_alert.get("alert_id"),
                    "bot_id": emitted_alert.get("bot_id"),
                    "code": emitted_alert.get("code"),
                    "level": emitted_alert.get("level"),
                },
            )
        self._sync_bot_state(bot_id)
        return HTTPStatus.ACCEPTED, self._response(data=result)

    def _create_config_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        config_scope = json_string(body.get("config_scope"))
        checksum = json_string(body.get("checksum"))
        config_json = optional_object(body.get("config_json"))
        created_by = json_string(body.get("created_by"))
        invalid_string_fields = [
            key
            for key in ("config_scope", "checksum")
            if key in body and json_string(body.get(key)) is None
        ]
        if "created_by" in body and created_by is None:
            invalid_string_fields.append("created_by")

        if invalid_string_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": (
                            "fields must be strings: "
                            + ", ".join(sorted(set(invalid_string_fields)))
                        ),
                    }
                ),
            )

        if not config_scope or not checksum or config_json is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "config_scope, config_json, checksum are required",
                    }
                ),
            )

        result = self.server.read_store.create_config_version(
            config_scope=config_scope,
            config_json=config_json,
            checksum=checksum,
            created_by=created_by,
        )
        self._sync_latest_config(config_scope, result)
        return HTTPStatus.CREATED, self._response(data=result)

    def _create_strategy_run_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        bot_id = json_string(body.get("bot_id"))
        strategy_name = json_string(body.get("strategy_name"))
        mode = json_string(body.get("mode"))
        invalid_string_fields = [
            key
            for key in ("bot_id", "strategy_name", "mode")
            if key in body and json_string(body.get(key)) is None
        ]
        if invalid_string_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": (
                            "fields must be strings: "
                            + ", ".join(sorted(set(invalid_string_fields)))
                        ),
                    }
                ),
            )

        if not bot_id or not strategy_name or not mode:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "bot_id, strategy_name, mode are required",
                    }
                ),
            )

        outcome, result = self.server.read_store.create_strategy_run(
            bot_id=bot_id,
            strategy_name=strategy_name,
            mode=mode,
        )
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "BOT_NOT_FOUND", "message": "bot_id not found"}
                ),
            )
        if outcome == "conflict":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_CONFLICT",
                        "message": "bot already has an active strategy run",
                    }
                ),
            )
        self._sync_strategy_run_state(result)
        return HTTPStatus.CREATED, self._response(data=result)

    def _acknowledge_alert_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/alerts/"
        suffix = "/ack"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        alert_id = path[len(prefix) : -len(suffix)]
        if not alert_id:
            return None

        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        result = self.server.read_store.acknowledge_alert(alert_id)
        if result is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={"code": "ALERT_NOT_FOUND", "message": "alert_id not found"}
                ),
            )
        self.server.metrics.observe_alert_acknowledged()
        detail = self.server.read_store.get_alert_detail(alert_id)
        if detail is not None:
            self._publish_alert_event(
                "alert.acknowledged",
                {
                    "alert_id": detail.get("alert_id"),
                    "bot_id": detail.get("bot_id"),
                    "code": detail.get("code"),
                    "level": detail.get("level"),
                },
            )
        return HTTPStatus.ACCEPTED, self._response(data=result)

    def _assign_config_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/bots/"
        suffix = "/assign-config"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None

        bot_id = path[len(prefix) : -len(suffix)]
        if not bot_id:
            return None

        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        body, error = self._read_json_body()
        if error is not None:
            return error

        config_scope = json_string(body.get("config_scope"))
        version_no = json_int(body.get("version_no"))
        invalid_fields = []
        if "config_scope" in body and config_scope is None:
            invalid_fields.append("config_scope")
        if "version_no" in body and version_no is None:
            invalid_fields.append("version_no")
        if invalid_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": (
                            "fields must use json scalar types: "
                            + ", ".join(sorted(set(invalid_fields)))
                        ),
                    }
                ),
            )

        if not config_scope or version_no is None:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "config_scope and version_no are required",
                    }
                ),
            )

        result = self.server.read_store.assign_config(
            bot_id=bot_id,
            config_scope=config_scope,
            version_no=version_no,
        )
        if result is None:
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "BOT_OR_CONFIG_NOT_FOUND",
                        "message": "bot_id or config version not found",
                    }
                ),
            )
        self.server.metrics.observe_alert_emitted("info")
        self._sync_bot_state(bot_id)
        return HTTPStatus.ACCEPTED, self._response(data=result)

    def _strategy_run_action_response(
        self, path: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        prefix = "/api/v1/strategy-runs/"
        if not path.startswith(prefix):
            return None

        suffix = path[len(prefix) :]
        if suffix.endswith("/start"):
            run_id = suffix[: -len("/start")]
            return self._start_strategy_run_response(run_id)
        if suffix.endswith("/stop"):
            run_id = suffix[: -len("/stop")]
            return self._stop_strategy_run_response(run_id)
        return None

    def _start_strategy_run_response(
        self, run_id: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        if not run_id:
            return None

        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        outcome, run = self.server.read_store.start_strategy_run(run_id)
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_NOT_FOUND",
                        "message": "run_id not found",
                    }
                ),
            )
        if outcome == "conflict":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_CONFLICT",
                        "message": "strategy run cannot be started from current state",
                    }
                ),
            )
        self._sync_strategy_run_state(run)
        return HTTPStatus.ACCEPTED, self._response(data=run)

    def _stop_strategy_run_response(
        self, run_id: str
    ) -> tuple[HTTPStatus, dict[str, object]] | None:
        if not run_id:
            return None

        unsupported = self._ensure_mutation_supported()
        if unsupported is not None:
            return unsupported

        outcome, run = self.server.read_store.stop_strategy_run(run_id)
        if outcome == "not_found":
            return (
                HTTPStatus.NOT_FOUND,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_NOT_FOUND",
                        "message": "run_id not found",
                    }
                ),
            )
        if outcome == "conflict":
            return (
                HTTPStatus.CONFLICT,
                self._response(
                    error={
                        "code": "STRATEGY_RUN_CONFLICT",
                        "message": "strategy run cannot be stopped from current state",
                    }
                ),
            )
        self._sync_strategy_run_state(run)
        return HTTPStatus.ACCEPTED, self._response(data=run)

    def _emit_heartbeat_alert_if_needed(
        self,
        *,
        bot_id: str,
        is_process_alive: bool,
        is_market_data_alive: bool,
        is_ordering_alive: bool,
    ) -> dict[str, object] | None:
        if is_process_alive and is_market_data_alive and is_ordering_alive:
            return None

        if not is_process_alive:
            level = "critical"
            code = "BOT_PROCESS_DOWN"
            message = "bot process is not alive"
        elif not is_ordering_alive:
            level = "critical"
            code = "ORDERING_PIPELINE_DOWN"
            message = "ordering pipeline is not alive"
        else:
            level = "warn"
            code = "MARKET_DATA_DEGRADED"
            message = "market data pipeline is not alive"

        alert = self.server.read_store.emit_alert(
            bot_id=bot_id,
            level=level,
            code=code,
            message=message,
        )
        if level == "critical":
            self.server.alert_hook.emit(alert=alert)
        return alert
