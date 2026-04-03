from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import threading
from typing import Any

from .storage.read_store import MemoryReadStore


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class JsonLogFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": _iso_now(),
            "level": record.levelname,
            "service": self.service_name,
            "module": record.name,
            "event_name": getattr(record, "event_name", "log"),
            "bot_id": getattr(record, "bot_id", None),
            "strategy_run_id": getattr(record, "strategy_run_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "message": record.getMessage(),
        }
        for key in (
            "client_ip",
            "http_method",
            "path",
            "status_code",
            "duration_ms",
            "alert_code",
            "alert_level",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=True)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_requests: dict[tuple[str, str], int] = defaultdict(int)
        self._http_duration_count: dict[str, int] = defaultdict(int)
        self._http_duration_sum: dict[str, float] = defaultdict(float)
        self._alerts_emitted: dict[str, int] = defaultdict(int)
        self._alerts_acknowledged = 0

    def observe_request(self, method: str, status_code: int, duration_seconds: float) -> None:
        status = str(status_code)
        with self._lock:
            self._http_requests[(method, status)] += 1
            self._http_duration_count[method] += 1
            self._http_duration_sum[method] += duration_seconds

    def observe_alert_emitted(self, level: str) -> None:
        with self._lock:
            self._alerts_emitted[level] += 1

    def observe_alert_acknowledged(self) -> None:
        with self._lock:
            self._alerts_acknowledged += 1

    def render(self, read_store: MemoryReadStore) -> str:
        lines = [
            "# HELP control_plane_http_requests_total Total HTTP requests handled by control-plane.",
            "# TYPE control_plane_http_requests_total counter",
        ]

        with self._lock:
            request_items = sorted(self._http_requests.items())
            duration_count = dict(self._http_duration_count)
            duration_sum = dict(self._http_duration_sum)
            alerts_emitted = dict(self._alerts_emitted)
            alerts_acknowledged = self._alerts_acknowledged

        for (method, status), value in request_items:
            lines.append(
                'control_plane_http_requests_total{method="%s",status="%s"} %s'
                % (method, status, value)
            )

        lines.extend(
            [
                "# HELP control_plane_http_request_duration_seconds Request duration summary by method.",
                "# TYPE control_plane_http_request_duration_seconds summary",
            ]
        )
        for method in sorted(duration_count):
            lines.append(
                'control_plane_http_request_duration_seconds_count{method="%s"} %s'
                % (method, duration_count[method])
            )
            lines.append(
                'control_plane_http_request_duration_seconds_sum{method="%s"} %.6f'
                % (method, duration_sum[method])
            )

        lines.extend(
            [
                "# HELP control_plane_active_bots Running bots visible in the read model.",
                "# TYPE control_plane_active_bots gauge",
                f"control_plane_active_bots {read_store.active_bot_count()}",
                "# HELP control_plane_active_strategy_runs Running strategy runs visible in the read model.",
                "# TYPE control_plane_active_strategy_runs gauge",
                f"control_plane_active_strategy_runs {read_store.active_strategy_run_count()}",
                "# HELP alerts_emitted_total Alert events emitted by level.",
                "# TYPE alerts_emitted_total counter",
            ]
        )
        for level in sorted(alerts_emitted):
            lines.append(
                'alerts_emitted_total{level="%s"} %s' % (level, alerts_emitted[level])
            )

        lines.extend(
            [
                "# HELP alerts_acknowledged_total Alert events acknowledged by operators.",
                "# TYPE alerts_acknowledged_total counter",
                f"alerts_acknowledged_total {alerts_acknowledged}",
            ]
        )
        return "\n".join(lines) + "\n"


class AlertHookNotifier:
    def __init__(self, output_path: Path | None, service_name: str) -> None:
        self.output_path = output_path
        self.service_name = service_name
        self._lock = threading.Lock()

    def emit(self, *, alert: dict[str, Any], trace_id: str | None = None) -> bool:
        if self.output_path is None:
            return False

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sent_at": _iso_now(),
            "service": self.service_name,
            "event_name": "critical_alert_sent",
            "trace_id": trace_id,
            "alert": alert,
        }
        line = json.dumps(payload, ensure_ascii=True) + "\n"
        with self._lock:
            with self.output_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        return True
