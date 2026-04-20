from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from shutil import which
import threading
from typing import Any
from uuid import uuid4

from .redis_client import RedisClient, RedisClientError


LOGGER = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
        self._state_lock = threading.Lock()
        self._last_error_message: str | None = None
        self._client: RedisClient | None = None
        if redis_url:
            try:
                self._client = RedisClient(redis_url, max_connections=8, socket_timeout_seconds=5.0)
            except ValueError as exc:
                LOGGER.warning(
                    "redis runtime configuration invalid: %s",
                    exc,
                    extra={
                        "event_name": "redis_runtime_failed",
                    },
                )

    @property
    def info(self) -> RedisRuntimeInfo:
        return RedisRuntimeInfo(
            configured=bool(self.redis_url),
            cli_available=bool(self.redis_cli_path),
            enabled=bool(self.redis_url and self._client is not None),
            key_prefix=self.key_prefix,
            state=self._state_name(),
        )

    def _state_name(self) -> str:
        if not self.redis_url:
            return "not_configured"
        if self._client is None:
            return "invalid_config"
        if self._last_error_message:
            return "degraded"
        return "enabled"

    def now_iso(self) -> str:
        return _iso_now()

    def set_json(
        self, key_parts: list[str], payload: dict[str, Any], ttl_seconds: int | None = None
    ) -> bool:
        command = [
            "SET",
            self._key(*key_parts),
            json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        ]
        if ttl_seconds is not None:
            command.extend(["EX", str(ttl_seconds)])
        result = self._execute(command)
        return result == "OK"

    def get_json(self, key_parts: list[str]) -> dict[str, Any] | None:
        raw = self._execute(["GET", self._key(*key_parts)])
        if raw is None or not isinstance(raw, str):
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
        result = self._execute(
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
        return isinstance(result, str) and bool(result)

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
        publish_event: bool = True,
    ) -> None:
        payload_to_store = {
            **payload,
            "strategy_run_id": run_id,
            "cached_at": _iso_now(),
        }
        if not self.set_json(["strategy_run", run_id, "latest_evaluation"], payload_to_store):
            return
        if not publish_event:
            return
        self.append_event(
            "strategy_events",
            event_type="strategy.arbitrage_latest_evaluation.updated",
            payload={
                "run_id": run_id,
                "accepted": payload_to_store.get("accepted"),
                "reason_code": payload_to_store.get("reason_code"),
                "lifecycle_preview": payload_to_store.get("lifecycle_preview"),
            },
            trace_id=trace_id,
        )

    def sync_arbitrage_evaluation_recovery_state(
        self,
        *,
        run_id: str,
        recovery_trace: dict[str, Any],
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_arbitrage_evaluation(run_id=run_id)
        if current is None:
            return None
        status = str(recovery_trace.get("status") or "").strip().lower()
        lifecycle_state = str(recovery_trace.get("lifecycle_state") or "").strip()
        lifecycle_preview = lifecycle_state or str(current.get("lifecycle_preview") or "")
        if status in {"resolved", "cancelled"}:
            lifecycle_preview = "closed"
        elif status == "handoff_required":
            lifecycle_preview = "manual_handoff"
        payload = {
            **current,
            "lifecycle_preview": lifecycle_preview,
            "recovery_trace_id": recovery_trace.get("recovery_trace_id"),
            "recovery_status": recovery_trace.get("status"),
            "recovery_lifecycle_state": recovery_trace.get("lifecycle_state"),
            "recovery_updated_at": recovery_trace.get("updated_at"),
        }
        self.sync_arbitrage_evaluation(
            run_id=run_id,
            payload=payload,
            trace_id=trace_id,
            publish_event=True,
        )
        return self.get_arbitrage_evaluation(run_id=run_id)

    def publish_order_event(
        self, *, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        self.append_event("order_events", event_type=event_type, payload=payload, trace_id=trace_id)

    def publish_alert_event(
        self, *, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        self.append_event("alert_events", event_type=event_type, payload=payload, trace_id=trace_id)

    def sync_recovery_trace(
        self,
        *,
        recovery_trace_id: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        payload_to_store = {
            **payload,
            "recovery_trace_id": recovery_trace_id,
            "updated_at": _iso_now(),
        }
        if not self.set_json(["recovery_trace", recovery_trace_id], payload_to_store):
            return
        self.append_event(
            "strategy_events",
            event_type="strategy.recovery_trace.updated",
            payload={
                "recovery_trace_id": recovery_trace_id,
                "run_id": payload_to_store.get("run_id"),
                "bot_id": payload_to_store.get("bot_id"),
                "status": payload_to_store.get("status"),
                "lifecycle_state": payload_to_store.get("lifecycle_state"),
            },
            trace_id=trace_id,
        )

    def get_recovery_trace(self, *, recovery_trace_id: str) -> dict[str, Any] | None:
        return self.get_json(["recovery_trace", recovery_trace_id])

    def transition_recovery_trace(
        self,
        *,
        recovery_trace_id: str,
        status: str,
        lifecycle_state: str,
        patch: dict[str, Any] | None = None,
        trace_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_recovery_trace(recovery_trace_id=recovery_trace_id)
        if current is None:
            return None
        current_status = str(current.get("status") or "").strip().lower()
        if current_status in {"resolved", "cancelled"}:
            return {**current, "_conflict": "terminal"}
        payload = {
            **current,
            "status": status,
            "lifecycle_state": lifecycle_state,
            **(patch or {}),
        }
        self.sync_recovery_trace(
            recovery_trace_id=recovery_trace_id,
            payload=payload,
            trace_id=trace_id,
        )
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            latest_trace = self.get_recovery_trace(recovery_trace_id=recovery_trace_id)
            if latest_trace is not None:
                self.sync_arbitrage_evaluation_recovery_state(
                    run_id=run_id,
                    recovery_trace=latest_trace,
                    trace_id=trace_id,
                )
        if event_type:
            self.append_event(
                "strategy_events",
                event_type=event_type,
                payload={
                    "recovery_trace_id": recovery_trace_id,
                    "run_id": payload.get("run_id"),
                    "bot_id": payload.get("bot_id"),
                    "status": payload.get("status"),
                    "lifecycle_state": payload.get("lifecycle_state"),
                },
                trace_id=trace_id,
            )
        return self.get_recovery_trace(recovery_trace_id=recovery_trace_id)

    def list_recovery_traces(
        self,
        *,
        limit: int = 20,
        bot_id: str | None = None,
        run_id: str | None = None,
        status: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[dict[str, Any]] | None:
        key_prefix = self._key("recovery_trace") + ":"
        keys = self._scan_keys(self._key("recovery_trace", "*"))
        if keys is None:
            return None
        normalized_status = (status or "").strip().lower()
        normalized_lifecycle = (lifecycle_state or "").strip().lower()
        items: list[dict[str, Any]] = []
        for key in keys:
            if not key.startswith(key_prefix):
                continue
            payload = self._get_json_by_full_key(key)
            if payload is None:
                continue
            if bot_id and str(payload.get("bot_id") or "") != bot_id:
                continue
            if run_id and str(payload.get("run_id") or "") != run_id:
                continue
            if normalized_status and str(payload.get("status") or "").strip().lower() != normalized_status:
                continue
            if normalized_lifecycle and str(payload.get("lifecycle_state") or "").strip().lower() != normalized_lifecycle:
                continue
            items.append(payload)
        items.sort(
            key=lambda item: _parse_iso_datetime(item.get("updated_at"))
            or _parse_iso_datetime(item.get("created_at"))
            or datetime.fromtimestamp(0, UTC),
            reverse=True,
        )
        return items[: max(1, min(limit, 100))]

    def get_blocking_recovery_trace(
        self,
        *,
        bot_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for status in ("handoff_required", "active"):
            items = self.list_recovery_traces(
                limit=10,
                bot_id=bot_id,
                run_id=run_id,
                status=status,
            )
            if items is None:
                raise RuntimeError("failed to read blocking recovery traces")
            candidates.extend(items)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: _parse_iso_datetime(item.get("updated_at"))
            or _parse_iso_datetime(item.get("created_at"))
            or datetime.fromtimestamp(0, UTC),
            reverse=True,
        )
        return candidates[0]

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

    def list_arbitrage_evaluations(
        self,
        *,
        limit: int = 20,
        bot_id: str | None = None,
        accepted: bool | None = None,
        lifecycle_preview: str | None = None,
        reason_code: str | None = None,
    ) -> list[dict[str, Any]] | None:
        key_prefix = self._key("strategy_run") + ":"
        keys = self._scan_keys(self._key("strategy_run", "*", "latest_evaluation"))
        if keys is None:
            return None
        normalized_lifecycle = (lifecycle_preview or "").strip()
        normalized_reason = (reason_code or "").strip()
        evaluations: list[dict[str, Any]] = []
        for key in keys:
            if not key.startswith(key_prefix):
                continue
            payload = self._get_json_by_full_key(key)
            if payload is None:
                continue
            if bot_id and str(payload.get("bot_id") or "") != bot_id:
                continue
            if accepted is not None:
                payload_accepted = payload.get("accepted")
                if not isinstance(payload_accepted, bool):
                    continue
                if payload_accepted is not accepted:
                    continue
            if normalized_lifecycle and str(payload.get("lifecycle_preview") or "") != normalized_lifecycle:
                continue
            if normalized_reason and str(payload.get("reason_code") or "") != normalized_reason:
                continue
            evaluations.append(payload)
        evaluations.sort(
            key=lambda item: _parse_iso_datetime(item.get("cached_at")) or datetime.fromtimestamp(0, UTC),
            reverse=True,
        )
        return evaluations[: max(1, min(limit, 100))]

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
        raw = self._execute(
            [
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
        if not isinstance(raw, list):
            return None
        events: list[dict[str, Any]] = []
        for entry in raw:
            parsed = self._parse_stream_entry(entry)
            if parsed is not None:
                events.append(parsed)
        return events

    def get_stream_summary(self, *, stream_name: str) -> dict[str, Any] | None:
        key = self._key("stream", stream_name)
        length_raw = self._execute(["XLEN", key])
        if length_raw is None:
            return None
        try:
            length = int(length_raw)
        except (TypeError, ValueError):
            return None
        newest = self.list_stream_events(stream_name=stream_name, limit=1)
        oldest_raw = self._execute(["XRANGE", key, "-", "+", "COUNT", "1"])
        if oldest_raw is None:
            return None
        if not isinstance(oldest_raw, list):
            return None
        oldest_event = self._parse_stream_entry(oldest_raw[0]) if oldest_raw else None
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
        raw = self._execute(["GET", key])
        if raw is None or not isinstance(raw, str):
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

    def _scan_keys(self, pattern: str) -> list[str] | None:
        if not self.info.enabled:
            return None
        cursor = "0"
        keys: list[str] = []
        seen: set[str] = set()
        while True:
            result = self._execute(["SCAN", cursor, "MATCH", pattern, "COUNT", "100"])
            if result is None:
                return None
            if not isinstance(result, list) or len(result) != 2:
                return None
            next_cursor_raw, batch_raw = result
            next_cursor = str(next_cursor_raw)
            if not isinstance(batch_raw, list):
                return None
            for item in batch_raw:
                if not isinstance(item, str) or item in seen:
                    continue
                seen.add(item)
                keys.append(item)
            if next_cursor == "0":
                break
            cursor = next_cursor
        return keys

    def _execute(self, command: list[str]) -> object | None:
        client = self._client
        if client is None:
            return None
        try:
            result = client.execute(*command)
        except RedisClientError as exc:
            self._record_failure(str(exc))
            return None
        self._clear_failure()
        return result

    def _record_failure(self, message: str) -> None:
        with self._state_lock:
            self._last_error_message = message
        LOGGER.warning(
            "redis runtime command failed: %s",
            message,
            extra={
                "event_name": "redis_runtime_failed",
            },
        )

    def _clear_failure(self) -> None:
        with self._state_lock:
            self._last_error_message = None
