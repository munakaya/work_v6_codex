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

    def get_json(self, key_parts: list[str]) -> dict[str, Any] | None:
        raw = self._run_command_output(["GET", self._key(*key_parts)])
        if raw is None:
            return None
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

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

    def sync_arbitrage_evaluation(
        self,
        *,
        run_id: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        if not self.set_json(["strategy_run", run_id, "latest_evaluation"], payload):
            return
        self.append_event(
            "strategy_events",
            event_type="strategy.arbitrage_latest_evaluation.updated",
            payload={
                "run_id": run_id,
                "accepted": payload.get("accepted"),
                "reason_code": payload.get("reason_code"),
                "lifecycle_preview": payload.get("lifecycle_preview"),
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

    def get_market_orderbook_top(
        self, *, exchange: str, market: str
    ) -> dict[str, Any] | None:
        return self.get_json(["market", "orderbook_top", exchange, market])

    def get_arbitrage_evaluation(self, *, run_id: str) -> dict[str, Any] | None:
        return self.get_json(["strategy_run", run_id, "latest_evaluation"])

    def list_market_orderbook_tops(
        self,
        *,
        exchange: str | None = None,
        market: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]] | None:
        key_prefix = self._key("market", "orderbook_top") + ":"
        keys = self._scan_keys(self._key("market", "orderbook_top", "*"))
        if keys is None:
            return None
        normalized_exchange = (exchange or "").strip().lower()
        normalized_market = (market or "").strip().upper()
        snapshots: list[dict[str, Any]] = []
        for key in keys:
            if not key.startswith(key_prefix):
                continue
            suffix = key[len(key_prefix) :]
            if ":" not in suffix:
                continue
            key_exchange, key_market = suffix.split(":", 1)
            if normalized_exchange and key_exchange.strip().lower() != normalized_exchange:
                continue
            if normalized_market and key_market.strip().upper() != normalized_market:
                continue
            payload = self._get_json_by_full_key(key)
            if payload is None:
                continue
            snapshots.append(payload)
        snapshots.sort(key=lambda item: str(item.get("received_at") or ""), reverse=True)
        return snapshots[: max(1, min(limit, 100))]

    def list_stream_events(
        self,
        *,
        stream_name: str,
        limit: int = 20,
        before_stream_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        upper_bound = "+"
        if before_stream_id:
            upper_bound = f"({before_stream_id.strip()}"
        raw = self._run_command_output(
            [
                "--json",
                "XREVRANGE",
                self._key("stream", stream_name),
                upper_bound,
                "-",
                "COUNT",
                str(limit),
            ]
        )
        if raw is None:
            return None
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            entries = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(entries, list):
            return None
        events: list[dict[str, Any]] = []
        for entry in entries:
            parsed = self._parse_stream_entry(entry)
            if parsed is not None:
                events.append(parsed)
        return events

    def get_stream_summary(self, *, stream_name: str) -> dict[str, Any] | None:
        key = self._key("stream", stream_name)
        length_raw = self._run_command_output(["XLEN", key])
        if length_raw is None:
            return None
        try:
            length = int(length_raw.strip() or "0")
        except ValueError:
            return None
        newest = self.list_stream_events(stream_name=stream_name, limit=1)
        oldest_raw = self._run_command_output(["--json", "XRANGE", key, "-", "+", "COUNT", "1"])
        if oldest_raw is None:
            return None
        stripped = oldest_raw.strip()
        oldest_entries: list[Any] = []
        if stripped:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            if not isinstance(parsed, list):
                return None
            oldest_entries = parsed
        oldest_event = self._parse_stream_entry(oldest_entries[0]) if oldest_entries else None
        newest_event = newest[0] if newest else None
        if length == 0 and (newest_event is not None or oldest_event is not None):
            length = 1
        if newest_event is None and oldest_event is not None:
            newest_event = oldest_event
        if oldest_event is None and newest_event is not None:
            oldest_event = newest_event
        return {
            "stream_name": stream_name,
            "length": length,
            "newest_stream_id": newest_event.get("stream_id") if newest_event else None,
            "newest_occurred_at": newest_event.get("occurred_at") if newest_event else None,
            "oldest_stream_id": oldest_event.get("stream_id") if oldest_event else None,
            "oldest_occurred_at": oldest_event.get("occurred_at") if oldest_event else None,
        }

    def _key(self, *parts: str) -> str:
        return ":".join([self.key_prefix, *parts])

    def _get_json_by_full_key(self, key: str) -> dict[str, Any] | None:
        raw = self._run_command_output(["GET", key])
        if raw is None:
            return None
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _parse_stream_entry(self, entry: object) -> dict[str, Any] | None:
        if not isinstance(entry, list) or len(entry) != 2:
            return None
        stream_id, values = entry
        if not isinstance(stream_id, str):
            return None
        if not isinstance(values, list) or len(values) < 2:
            return None
        payload_text = values[1]
        if not isinstance(payload_text, str):
            return None
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return {"stream_id": stream_id, **payload}

    def _run_command(self, command: list[str]) -> bool:
        return self._run_command_output(command) is not None

    def _scan_keys(self, pattern: str) -> list[str] | None:
        output = self._run_command_output(["--scan", "--pattern", pattern])
        if output is None:
            return None
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _run_command_output(self, command: list[str]) -> str | None:
        if not self.info.enabled or not self.redis_url or not self.redis_cli_path:
            return None
        try:
            completed = subprocess.run(
                [self.redis_cli_path, "-u", self.redis_url, *command],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return completed.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.warning(
                "redis runtime command failed: %s",
                exc.__class__.__name__,
                extra={
                    "event_name": "redis_runtime_failed",
                },
            )
            return None
