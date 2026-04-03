from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..config import AppConfig


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sample_time(minutes_ago: int) -> str:
    return _iso(datetime.now(UTC) - timedelta(minutes=minutes_ago))


class MemoryReadStore:
    def __init__(
        self,
        *,
        bots: list[dict[str, object]],
        bot_details: dict[str, dict[str, object]],
        heartbeats: dict[str, list[dict[str, object]]],
        alerts: list[dict[str, object]],
    ) -> None:
        self.bots = bots
        self.bot_details = bot_details
        self.heartbeats = heartbeats
        self.alerts = alerts

    def list_bots(
        self,
        *,
        status: str | None = None,
        strategy_name: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]:
        bots = self.bots
        if status:
            bots = [bot for bot in bots if bot["status"] == status]
        if strategy_name:
            bots = [bot for bot in bots if bot["strategy_name"] == strategy_name]
        if mode:
            bots = [bot for bot in bots if bot["mode"] == mode]
        return bots

    def get_bot_detail(self, bot_id: str) -> dict[str, object] | None:
        return self.bot_details.get(bot_id)

    def list_heartbeats(self, bot_id: str, limit: int = 20) -> list[dict[str, object]] | None:
        entries = self.heartbeats.get(bot_id)
        if entries is None:
            return None
        return entries[:limit]

    def list_alerts(
        self,
        *,
        bot_id: str | None = None,
        level: str | None = None,
        acknowledged: bool | None = None,
    ) -> list[dict[str, object]]:
        alerts = self.alerts
        if bot_id:
            alerts = [alert for alert in alerts if alert.get("bot_id") == bot_id]
        if level:
            alerts = [alert for alert in alerts if alert["level"] == level]
        if acknowledged is not None:
            alerts = [
                alert
                for alert in alerts
                if (alert.get("acknowledged_at") is not None) == acknowledged
            ]
        return alerts

    def register_bot(
        self,
        *,
        bot_key: str,
        strategy_name: str,
        mode: str,
        hostname: str | None,
    ) -> dict[str, object]:
        existing = next((bot for bot in self.bots if bot["bot_key"] == bot_key), None)
        if existing is not None:
            existing["strategy_name"] = strategy_name
            existing["mode"] = mode
            existing["hostname"] = hostname
            existing["status"] = "running"
            existing["last_seen_at"] = _sample_time(0)
            detail = self.bot_details[str(existing["bot_id"])]
            detail.update(existing)
            return {
                "bot_id": existing["bot_id"],
                "assigned_config_version": existing["assigned_config_version"],
                "status": existing["status"],
            }

        bot_id = str(uuid4())
        assigned_config_version = {"config_scope": "default", "version_no": 1}
        bot = {
            "bot_id": bot_id,
            "bot_key": bot_key,
            "strategy_name": strategy_name,
            "mode": mode,
            "status": "running",
            "hostname": hostname,
            "last_seen_at": _sample_time(0),
            "assigned_config_version": assigned_config_version,
        }
        self.bots.append(bot)
        self.bot_details[bot_id] = {
            **bot,
            "latest_heartbeat": None,
            "latest_strategy_run": None,
            "recent_alerts": [],
        }
        self.heartbeats[bot_id] = []
        return {
            "bot_id": bot_id,
            "assigned_config_version": assigned_config_version,
            "status": bot["status"],
        }

    def record_heartbeat(
        self,
        *,
        bot_id: str,
        is_process_alive: bool,
        is_market_data_alive: bool,
        is_ordering_alive: bool,
        lag_ms: int | None,
        context: dict[str, object] | None,
    ) -> dict[str, object] | None:
        detail = self.bot_details.get(bot_id)
        if detail is None:
            return None

        heartbeat = {
            "created_at": _sample_time(0),
            "is_process_alive": is_process_alive,
            "is_market_data_alive": is_market_data_alive,
            "is_ordering_alive": is_ordering_alive,
            "lag_ms": lag_ms,
            "payload": context or {},
        }
        history = self.heartbeats.setdefault(bot_id, [])
        history.insert(0, heartbeat)
        detail["latest_heartbeat"] = heartbeat
        detail["last_seen_at"] = heartbeat["created_at"]

        for bot in self.bots:
            if bot["bot_id"] == bot_id:
                bot["last_seen_at"] = heartbeat["created_at"]
                bot["status"] = "running" if is_process_alive else "failed"
                detail["status"] = bot["status"]
                break

        return {
            "bot_id": bot_id,
            "status": detail["status"],
            "recorded_at": heartbeat["created_at"],
        }


def build_read_store(config: AppConfig) -> MemoryReadStore:
    if config.use_sample_read_model:
        return sample_read_store()
    return MemoryReadStore(bots=[], bot_details={}, heartbeats={}, alerts=[])


def sample_read_store() -> MemoryReadStore:
    bot_1_id = "9d0f9b5d-8f1d-4fe0-bd90-5b7bcb3b4e21"
    bot_2_id = "0ecf5f88-c7d3-4307-b4e7-e54caef0eab3"

    bot_1_heartbeat = {
        "created_at": _sample_time(1),
        "is_process_alive": True,
        "is_market_data_alive": True,
        "is_ordering_alive": True,
        "lag_ms": 240,
        "payload": {
            "orderbook_stale_count": 0,
            "balance_refresh_age_ms": 1800,
        },
    }
    bot_2_heartbeat = {
        "created_at": _sample_time(3),
        "is_process_alive": True,
        "is_market_data_alive": False,
        "is_ordering_alive": True,
        "lag_ms": 1450,
        "payload": {
            "orderbook_stale_count": 4,
            "balance_refresh_age_ms": 6400,
        },
    }

    bots = [
        {
            "bot_id": bot_1_id,
            "bot_key": "arb-upbit-bithumb-001",
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "status": "running",
            "hostname": "trade-host-01",
            "last_seen_at": bot_1_heartbeat["created_at"],
            "assigned_config_version": {"config_scope": "default", "version_no": 3},
        },
        {
            "bot_id": bot_2_id,
            "bot_key": "arb-upbit-coinone-002",
            "strategy_name": "arbitrage",
            "mode": "dry_run",
            "status": "running",
            "hostname": "trade-host-02",
            "last_seen_at": bot_2_heartbeat["created_at"],
            "assigned_config_version": {"config_scope": "default", "version_no": 2},
        },
    ]

    alerts = [
        {
            "alert_id": "2274470a-1b8d-4bb1-8b60-68ba2f2c17c9",
            "bot_id": bot_2_id,
            "level": "warn",
            "code": "ORDERBOOK_STALE",
            "message": "coinone orderbook freshness exceeded threshold",
            "created_at": _sample_time(4),
            "acknowledged_at": None,
        },
        {
            "alert_id": "47083d47-1b3f-43ab-a76a-f967f2e824a8",
            "bot_id": bot_1_id,
            "level": "info",
            "code": "CONFIG_APPLIED",
            "message": "config version 3 applied",
            "created_at": _sample_time(9),
            "acknowledged_at": _sample_time(8),
        },
    ]

    bot_details = {
        bot_1_id: {
            **bots[0],
            "latest_heartbeat": bot_1_heartbeat,
            "latest_strategy_run": {
                "run_id": "eb8f7c39-d23f-433f-b839-6d2e89d4bbd6",
                "status": "running",
                "mode": "shadow",
                "started_at": _sample_time(12),
                "decision_count": 184,
            },
            "recent_alerts": [alerts[1]],
        },
        bot_2_id: {
            **bots[1],
            "latest_heartbeat": bot_2_heartbeat,
            "latest_strategy_run": {
                "run_id": "7d9cf351-5b29-44a4-9cb4-ff5d1c4e0a0f",
                "status": "running",
                "mode": "dry_run",
                "started_at": _sample_time(30),
                "decision_count": 42,
            },
            "recent_alerts": [alerts[0]],
        },
    }

    heartbeats = {
        bot_1_id: [
            bot_1_heartbeat,
            {
                "created_at": _sample_time(2),
                "is_process_alive": True,
                "is_market_data_alive": True,
                "is_ordering_alive": True,
                "lag_ms": 210,
                "payload": {
                    "orderbook_stale_count": 0,
                    "balance_refresh_age_ms": 1600,
                },
            },
        ],
        bot_2_id: [
            bot_2_heartbeat,
            {
                "created_at": _sample_time(5),
                "is_process_alive": True,
                "is_market_data_alive": True,
                "is_ordering_alive": True,
                "lag_ms": 320,
                "payload": {
                    "orderbook_stale_count": 1,
                    "balance_refresh_age_ms": 2200,
                },
            },
        ],
    }

    return MemoryReadStore(
        bots=bots,
        bot_details=bot_details,
        heartbeats=heartbeats,
        alerts=alerts,
    )
