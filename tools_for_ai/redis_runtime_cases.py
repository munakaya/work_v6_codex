from __future__ import annotations

import os
from uuid import uuid4

from trading_platform.redis_runtime import RedisRuntime


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    redis_url = os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0")
    previous_path = os.environ.get("PATH")
    try:
        os.environ["PATH"] = ""
        runtime = RedisRuntime(
            redis_url,
            f"tp_redis_runtime_case_{uuid4().hex[:8]}",
            "redis-runtime-case",
        )
    finally:
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path

    _assert(runtime.info.enabled, "redis runtime should not depend on redis-cli")
    _assert(runtime.info.cli_available is False, "cli availability should reflect empty PATH")
    _assert(runtime.info.state == "enabled", "redis runtime initial state mismatch")

    recovery_trace_id = f"rt_{uuid4().hex}"
    runtime.sync_recovery_trace(
        recovery_trace_id=recovery_trace_id,
        payload={
            "recovery_trace_id": recovery_trace_id,
            "run_id": "run-1",
            "bot_id": "bot-1",
            "intent_id": "intent-1",
            "status": "active",
            "lifecycle_state": "recovery_required",
            "residual_exposure_quote": "10",
            "created_at": runtime.now_iso(),
            "updated_at": runtime.now_iso(),
        },
    )
    stored = runtime.get_recovery_trace(recovery_trace_id=recovery_trace_id)
    _assert(stored is not None, "redis runtime should roundtrip JSON payloads")
    _assert(stored.get("run_id") == "run-1", "redis runtime stored payload mismatch")

    broken = RedisRuntime(
        "redis://127.0.0.1:1/0",
        f"tp_redis_runtime_broken_{uuid4().hex[:8]}",
        "redis-runtime-case",
    )
    _assert(broken.info.enabled, "broken runtime should still be configured")
    _assert(broken.get_json(["missing"]) is None, "broken runtime get_json should fail closed")
    _assert(broken.info.state == "degraded", "broken runtime should enter degraded state")

    print("PASS redis runtime works without redis-cli on PATH")
    print("PASS redis runtime marks failed commands as degraded")


if __name__ == "__main__":
    main()
