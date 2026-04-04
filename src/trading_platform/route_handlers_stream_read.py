from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
import re
from urllib.parse import parse_qs

from .request_utils import query_limit, single_query_value


EventValueExtractor = Callable[[dict[str, object]], object]
EventValueNormalizer = Callable[[str], str]
STREAM_ID_PATTERN = re.compile(r"^\d+-\d+$")


class ControlPlaneStreamReadRouteMixin:
    def _market_events_response(self, query: str) -> tuple[HTTPStatus, dict[str, object]]:
        return self._stream_events_response(
            query=query,
            stream_name="market_events",
            stream_label="market event stream",
            filters=(
                self._event_filter(
                    query_keys=("exchange",),
                    extractor=lambda event: (event.get("payload") or {}).get("exchange"),
                    normalizer=lambda value: value.strip().lower(),
                ),
                self._event_filter(
                    query_keys=("market",),
                    extractor=lambda event: (event.get("payload") or {}).get("market"),
                    normalizer=lambda value: value.strip().upper(),
                ),
            ),
        )

    def _bot_events_response(self, query: str) -> tuple[HTTPStatus, dict[str, object]]:
        return self._stream_events_response(
            query=query,
            stream_name="bot_events",
            stream_label="bot event stream",
            filters=(
                self._event_filter(
                    query_keys=("bot_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("bot_id"),
                ),
                self._event_filter(
                    query_keys=("bot_key",),
                    extractor=lambda event: (event.get("payload") or {}).get("bot_key"),
                ),
            ),
        )

    def _strategy_events_response(
        self, query: str
    ) -> tuple[HTTPStatus, dict[str, object]]:
        return self._stream_events_response(
            query=query,
            stream_name="strategy_events",
            stream_label="strategy event stream",
            filters=(
                self._event_filter(
                    query_keys=("bot_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("bot_id"),
                ),
                self._event_filter(
                    query_keys=("run_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("run_id"),
                ),
                self._event_filter(
                    query_keys=("config_scope",),
                    extractor=lambda event: (event.get("payload") or {}).get("config_scope"),
                ),
            ),
        )

    def _order_events_response(self, query: str) -> tuple[HTTPStatus, dict[str, object]]:
        return self._stream_events_response(
            query=query,
            stream_name="order_events",
            stream_label="order event stream",
            filters=(
                self._event_filter(
                    query_keys=("bot_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("bot_id"),
                ),
                self._event_filter(
                    query_keys=("order_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("order_id"),
                ),
                self._event_filter(
                    query_keys=("order_intent_id", "intent_id"),
                    extractor=lambda event: (event.get("payload") or {}).get("order_intent_id")
                    or (event.get("payload") or {}).get("intent_id"),
                ),
                self._event_filter(
                    query_keys=("exchange_name", "exchange"),
                    extractor=lambda event: (event.get("payload") or {}).get("exchange_name"),
                    normalizer=lambda value: value.strip().lower(),
                ),
            ),
        )

    def _alert_events_response(self, query: str) -> tuple[HTTPStatus, dict[str, object]]:
        return self._stream_events_response(
            query=query,
            stream_name="alert_events",
            stream_label="alert event stream",
            filters=(
                self._event_filter(
                    query_keys=("bot_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("bot_id"),
                ),
                self._event_filter(
                    query_keys=("alert_id",),
                    extractor=lambda event: (event.get("payload") or {}).get("alert_id"),
                ),
                self._event_filter(
                    query_keys=("level",),
                    extractor=lambda event: (event.get("payload") or {}).get("level"),
                    normalizer=lambda value: value.strip().lower(),
                ),
            ),
        )

    def _stream_events_response(
        self,
        *,
        query: str,
        stream_name: str,
        stream_label: str,
        filters: tuple[dict[str, object], ...],
    ) -> tuple[HTTPStatus, dict[str, object]]:
        params = parse_qs(query)
        limit = query_limit(params)
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
        before_stream_id = (single_query_value(params, "before_stream_id") or "").strip()
        if before_stream_id and not STREAM_ID_PATTERN.fullmatch(before_stream_id):
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "before_stream_id must be a Redis stream id",
                    }
                ),
            )
        raw_events = self.server.redis_runtime.list_stream_events(
            stream_name=stream_name,
            limit=limit,
            before_stream_id=before_stream_id or None,
        )
        if raw_events is None:
            return (
                HTTPStatus.BAD_GATEWAY,
                self._response(
                    error={
                        "code": "REDIS_STREAM_READ_FAILED",
                        "message": f"failed to read {stream_label}",
                    }
                ),
            )
        next_before_stream_id: str | None = None
        if len(raw_events) >= limit:
            last_stream_id = raw_events[-1].get("stream_id")
            if isinstance(last_stream_id, str) and last_stream_id:
                next_before_stream_id = last_stream_id
        events = list(raw_events)

        event_type = (single_query_value(params, "event_type") or "").strip()
        if event_type:
            events = [
                event
                for event in events
                if str(event.get("event_type") or "").strip() == event_type
            ]
        trace_id = (single_query_value(params, "trace_id") or "").strip()
        if trace_id:
            events = [
                event
                for event in events
                if str(event.get("trace_id") or "").strip() == trace_id
            ]

        for event_filter in filters:
            raw_value = None
            for query_key in event_filter["query_keys"]:
                raw_value = single_query_value(params, query_key)
                if raw_value is not None:
                    break
            if raw_value is None:
                continue
            normalized_value = event_filter["normalizer"](raw_value)
            if not normalized_value:
                continue
            extractor = event_filter["extractor"]
            events = [
                event
                for event in events
                if event_filter["normalizer"](str(extractor(event) or "")) == normalized_value
            ]
        return HTTPStatus.OK, self._response(
            data={
                "items": events,
                "count": len(events),
                "next_before_stream_id": next_before_stream_id,
            }
        )

    def _event_filter(
        self,
        *,
        query_keys: tuple[str, ...],
        extractor: EventValueExtractor,
        normalizer: EventValueNormalizer | None = None,
    ) -> dict[str, object]:
        return {
            "query_keys": query_keys,
            "extractor": extractor,
            "normalizer": normalizer or (lambda value: value.strip()),
        }
