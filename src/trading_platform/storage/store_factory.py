from __future__ import annotations

from ..config import AppConfig
from .read_store import MemoryReadStore, _sample_time
from .sample_data import build_sample_state


def build_read_store(config: AppConfig) -> MemoryReadStore:
    if config.use_sample_read_model:
        return sample_read_store()
    return MemoryReadStore(
        bots=[],
        bot_details={},
        strategy_runs={},
        order_intents={},
        orders={},
        fills=[],
        heartbeats={},
        alerts=[],
        config_versions={},
    )


def sample_read_store() -> MemoryReadStore:
    state = build_sample_state(_sample_time)
    return MemoryReadStore(
        bots=state["bots"],
        bot_details=state["bot_details"],
        strategy_runs=state["strategy_runs"],
        order_intents=state["order_intents"],
        orders=state["orders"],
        fills=state["fills"],
        heartbeats=state["heartbeats"],
        alerts=state["alerts"],
        config_versions=state["config_versions"],
    )
