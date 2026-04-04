from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

from trading_platform.recovery_runtime import RecoveryRuntime
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.storage.store_factory import sample_read_store


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    redis_url = os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0")
    prefix = f"tp_recovery_runtime_case_{uuid4().hex[:8]}"
    redis_runtime = RedisRuntime(redis_url, prefix, "recovery-runtime-case")
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for recovery runtime cases")

    store = sample_read_store()
    run = store.list_strategy_runs()[0]
    bot_id = str(run["bot_id"])
    run_id = str(run["run_id"])
    runtime = RecoveryRuntime(
        enabled=True,
        interval_ms=1000,
        handoff_after_seconds=1,
        read_store=store,
        redis_runtime=redis_runtime,
    )

    resolved_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=resolved_trace_id,
        payload={
            "recovery_trace_id": resolved_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "0",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
        },
    )
    runtime.run_once()
    resolved = redis_runtime.get_recovery_trace(recovery_trace_id=resolved_trace_id)
    _assert(resolved is not None, "resolved trace missing")
    _assert(resolved.get("status") == "resolved", "resolved case status mismatch")
    _assert(resolved.get("lifecycle_state") == "closed", "resolved case lifecycle mismatch")

    handoff_trace_id = f"rt_{uuid4().hex}"
    redis_runtime.sync_recovery_trace(
        recovery_trace_id=handoff_trace_id,
        payload={
            "recovery_trace_id": handoff_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": "",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "125000",
            "created_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
            "updated_at": _iso(datetime.now(UTC) - timedelta(seconds=5)),
        },
    )
    runtime.run_once()
    handoff = redis_runtime.get_recovery_trace(recovery_trace_id=handoff_trace_id)
    _assert(handoff is not None, "handoff trace missing")
    _assert(handoff.get("status") == "handoff_required", "handoff case status mismatch")
    _assert(
        handoff.get("lifecycle_state") == "manual_handoff",
        "handoff case lifecycle mismatch",
    )
    _assert(
        handoff.get("incident_code") == "ARB-302 MANUAL_HANDOFF_REQUIRED",
        "handoff incident mismatch",
    )

    print("PASS recovery runtime resolves zero-exposure traces")
    print("PASS recovery runtime escalates aged traces to manual handoff")


if __name__ == "__main__":
    main()
