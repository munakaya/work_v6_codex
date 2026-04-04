from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from shutil import which
import subprocess
from typing import Any
from uuid import uuid4


LOGGER = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RedisRuntimeInfo:
    configured: bool
    cli_available: bool
    enabled: bool
    key_prefix: str
    state: str

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "cli_available": self.cli_available,
            "enabled": self.enabled,
            "key_prefix": self.key_prefix,
            "state": self.state,
        }


class RedisRuntime:
    BOT_STATE_TTL_SECONDS = 120
    MARKET_ORDERBOOK_TTL_SECONDS = 15
    EVENT_VERSION = 1

    def __init__(self, redis_url: str | None, key_prefix: str, service_name: str) -> None:
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.service_name = service_name
        self.redis_cli_path = which("redis-cli")
        self.info = RedisRuntimeInfo(
            configured=bool(redis_url),
            cli_available=bool(self.redis_cli_path),
            enabled=bool(redis_url and self.redis_cli_path),
            key_prefix=key_prefix,
            state=self._state_name(),
        )

    def _state_name(self) -> str:
        if not self.redis_url:
            return "not_configured"
        if not self.redis_cli_path:
            return "redis_cli_missing"
        return "enabled"

    def set_json(
        self, key_parts: list[str], payload: dict[str, Any], ttl_seconds: int | None = None
    ) -> bool:
        return self._run_command(
            [
                "SET",
                self._key(*key_parts),
                json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                *([] if ttl_seconds is None else ["EX", str(ttl_seconds)]),
            ]
        )

    def append_event(
        self,
        stream_name: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> bool:
        envelope = {
            "event_id": f"evt_{uuid4()}",
            "event_type": event_type,
            "event_version": self.EVENT_VERSION,
            "occurred_at": _iso_now(),
            "producer": self.service_name,
            "trace_id": trace_id,
            "payload": payload,
        }
        return self._run_command(
            [
                "XADD",
                self._key("stream", stream_name),
                "MAXLEN",
                "~",
                "1000",
                "*",
                "event",
                json.dumps(envelope, separators=(",", ":"), ensure_ascii=True),
            ]
        )

    def sync_bot_state(
        self,
        *,
        bot_key: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        if not self.set_json(
            ["bot", bot_key, "state"], payload, ttl_seconds=self.BOT_STATE_TTL_SECONDS
        ):
            return
        self.append_event(
            "bot_events",
            event_type="bot.state.updated",
            payload={"bot_key": bot_key, "bot_id": payload.get("bot_id")},
            trace_id=trace_id,
        )

    def sync_strategy_run_state(
        self, *, run_id: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        if not self.set_json(["strategy_run", run_id, "state"], payload):
            return
        self.append_event(
            "strategy_events",
            event_type="strategy_run.state.updated",
            payload={
                "run_id": run_id,
                "bot_id": payload.get("bot_id"),
                "status": payload.get("status"),
            },
            trace_id=trace_id,
        )

    def sync_latest_config(
        self, *, config_scope: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        if not self.set_json(["config", config_scope, "latest"], payload):
            return
        self.append_event(
            "strategy_events",
            event_type="config.latest.updated",
            payload={
                "config_scope": config_scope,
                "version_no": payload.get("version_no"),
                "config_version_id": payload.get("config_version_id"),
            },
            trace_id=trace_id,
        )

    def publish_order_event(
        self, *, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        self.append_event("order_events", event_type=event_type, payload=payload, trace_id=trace_id)

    def publish_alert_event(
        self, *, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        self.append_event("alert_events", event_type=event_type, payload=payload, trace_id=trace_id)

    def sync_market_orderbook_top(
        self,
        *,
        exchange: str,
        market: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        if not self.set_json(
            ["market", "orderbook_top", exchange, market],
            payload,
            ttl_seconds=ttl_seconds or self.MARKET_ORDERBOOK_TTL_SECONDS,
        ):
            return
        self.append_event(
            "market_events",
            event_type="market.orderbook_top.updated",
            payload={
                "exchange": exchange,
                "market": market,
                "stale": payload.get("stale"),
                "source_type": payload.get("source_type"),
                "exchange_age_ms": payload.get("exchange_age_ms"),
            },
            trace_id=trace_id,
        )

    def _key(self, *parts: str) -> str:
        return ":".join([self.key_prefix, *parts])

    def _run_command(self, command: list[str]) -> bool:
        if not self.info.enabled or not self.redis_url or not self.redis_cli_path:
            return False
        try:
            subprocess.run(
                [self.redis_cli_path, "-u", self.redis_url, *command],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.warning(
                "redis runtime command failed: %s",
                exc.__class__.__name__,
                extra={
                    "event_name": "redis_runtime_failed",
                },
            )
            return False
