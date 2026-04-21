from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib import error, request
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_platform.storage.postgres_driver import PsqlCliAdapter


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _db_dsn(db_name: str) -> str:
    return f"postgresql:///{db_name}"


def _http_json(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        base_url + path,
        method=method,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _wait_ready(base_url: str, timeout_seconds: float = 15.0) -> tuple[int, dict[str, object]]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            status, payload = _http_json(base_url=base_url, method="GET", path="/api/v1/ready")
            last_payload = payload
            if status in {200, 503}:
                return status, payload
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"server did not become ready in time: {last_payload}")


def _bootstrap_database(db_name: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    subprocess.run(
        [str(PYTHON_BIN), "tools_for_ai/db_bootstrap_local.py", db_name],
        cwd=str(ROOT_DIR),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _drop_database(db_name: str) -> None:
    subprocess.run(
        ["dropdb", "--if-exists", db_name],
        cwd=str(ROOT_DIR),
        check=True,
        capture_output=True,
        text=True,
    )


def _build_payload() -> dict[str, object]:
    return {
        "persist_intent": True,
        "execute": True,
        "canonical_symbol": "BTC-KRW",
        "market": "KRW-BTC",
        "base_exchange": "sample",
        "hedge_exchange": "upbit",
        "base_orderbook": {
            "asks": [
                {"price": "100000", "quantity": "0.5"},
                {"price": "100010", "quantity": "0.5"},
            ],
            "bids": [
                {"price": "99900", "quantity": "0.5"},
                {"price": "99890", "quantity": "0.5"},
            ],
        },
        "hedge_orderbook": {
            "asks": [
                {"price": "100550", "quantity": "0.5"},
                {"price": "100560", "quantity": "0.5"},
            ],
            "bids": [
                {"price": "100500", "quantity": "0.5"},
                {"price": "100490", "quantity": "0.5"},
            ],
        },
        "base_balance": {
            "available_quote": "150000000",
            "available_base": "0",
        },
        "hedge_balance": {
            "available_quote": "0",
            "available_base": "5",
        },
        "risk_config": {
            "min_profit_quote": "100",
            "max_target_qty": "0.2",
            "max_quote_notional": "5000000",
            "max_spread_bps": "2000",
        },
        "runtime_state": {
            "open_order_count": 0,
            "duplicate_intent_active": False,
            "unwind_in_progress": False,
        },
    }


def _register_bot(base_url: str, bot_key: str) -> str:
    status, payload = _http_json(
        base_url=base_url,
        method="POST",
        path="/api/v1/bots/register",
        payload={
            "bot_key": bot_key,
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "hostname": "postgres-execute-api-case",
        },
    )
    _assert(status == 200, f"bot register failed: {status} {payload}")
    return str(payload["data"]["bot_id"])


def _record_heartbeat(base_url: str, bot_id: str) -> None:
    status, payload = _http_json(
        base_url=base_url,
        method="POST",
        path=f"/api/v1/bots/{bot_id}/heartbeat",
        payload={
            "is_process_alive": True,
            "is_market_data_alive": True,
            "is_ordering_alive": True,
            "lag_ms": 15,
            "context": {"source": "postgres_execute_api_cases"},
        },
    )
    _assert(status == 202, f"heartbeat failed: {status} {payload}")


def _create_and_start_run(base_url: str, bot_id: str) -> str:
    status, payload = _http_json(
        base_url=base_url,
        method="POST",
        path="/api/v1/strategy-runs",
        payload={
            "bot_id": bot_id,
            "strategy_name": "arbitrage",
            "mode": "shadow",
        },
    )
    _assert(status == 201, f"strategy run create failed: {status} {payload}")
    run_id = str(payload["data"]["run_id"])
    status, payload = _http_json(
        base_url=base_url,
        method="POST",
        path=f"/api/v1/strategy-runs/{run_id}/start",
        payload={},
    )
    _assert(status == 202, f"strategy run start failed: {status} {payload}")
    return run_id


def _assert_ready_payload(status: int, payload: dict[str, object]) -> None:
    _assert(status == 200, f"ready should be ok: {status} {payload}")
    data = payload["data"]
    _assert(data["status"] == "ok", f"ready status mismatch: {data}")
    _assert(data["read_store"]["mode"] == "postgres", f"store mode mismatch: {data}")
    _assert(
        data["read_store"]["supports_mutation"] is True,
        f"store mutation support mismatch: {data}",
    )
    _assert(
        data["readiness_checks"]["dependencies_ready"] is True,
        f"dependency readiness mismatch: {data}",
    )
    _assert(
        data["readiness_checks"]["redis_runtime_ready"] is True,
        f"redis readiness mismatch: {data}",
    )
    _assert(
        data["readiness_checks"]["read_store_ready"] is True,
        f"read store readiness mismatch: {data}",
    )


def _assert_api_roundtrip(base_url: str, bot_id: str, run_id: str) -> tuple[str, tuple[str, str]]:
    status, payload = _http_json(base_url=base_url, method="GET", path="/api/v1/bots")
    _assert(status == 200, f"bot list failed: {status} {payload}")
    bot_items = payload["data"]["items"]
    _assert(
        any(str(item.get("bot_id") or "") == bot_id for item in bot_items),
        f"registered bot not listed: {payload}",
    )

    status, payload = _http_json(
        base_url=base_url,
        method="GET",
        path=f"/api/v1/bots/{bot_id}/heartbeats",
    )
    _assert(status == 200, f"heartbeat list failed: {status} {payload}")
    _assert(payload["data"]["count"] >= 1, f"heartbeat count mismatch: {payload}")

    status, payload = _http_json(
        base_url=base_url,
        method="POST",
        path=f"/api/v1/strategy-runs/{run_id}/evaluate-arbitrage",
        payload=_build_payload(),
    )
    _assert(status == 201, f"evaluate execute failed: {status} {payload}")

    data = payload["data"]
    _assert(data["lifecycle_preview"] == "closed", f"lifecycle mismatch: {data}")
    _assert(data["submit_result"]["outcome"] == "filled", f"submit result mismatch: {data}")
    _assert(
        data["persisted_intent"]["status"] == "created",
        f"intent response snapshot mismatch: {data}",
    )

    created_orders = data["submit_result"]["created_orders"]
    created_fills = data["submit_result"]["created_fills"]
    _assert(len(created_orders) == 2, f"created order count mismatch: {data}")
    _assert(len(created_fills) == 2, f"created fill count mismatch: {data}")

    status, latest_payload = _http_json(
        base_url=base_url,
        method="GET",
        path=f"/api/v1/strategy-runs/{run_id}/latest-evaluation",
    )
    _assert(status == 200, f"latest evaluation failed: {status} {latest_payload}")
    _assert(
        latest_payload["data"]["lifecycle_preview"] == "closed",
        f"latest evaluation lifecycle mismatch: {latest_payload}",
    )
    _assert(
        latest_payload["data"]["submit_result"]["outcome"] == "filled",
        f"latest evaluation submit result mismatch: {latest_payload}",
    )

    return str(data["persisted_intent"]["intent_id"]), (
        str(created_orders[0]["order_id"]),
        str(created_orders[1]["order_id"]),
    )


def _assert_database_rows(
    adapter: PsqlCliAdapter,
    *,
    bot_id: str,
    run_id: str,
    intent_id: str,
    order_ids: tuple[str, str],
) -> None:
    bot_row = adapter.fetch_one(
        """
        select id::text as bot_id, bot_key, mode::text as mode, status::text as status
        from bots
        where id = %s::uuid
        """,
        (bot_id,),
    )
    _assert(bot_row is not None, "registered bot missing in postgres")
    _assert(bot_row["status"] == "running", f"bot status mismatch: {bot_row}")

    heartbeat_count = adapter.fetch_value(
        "select count(*) as count from bot_heartbeats where bot_id = %s::uuid",
        (bot_id,),
    )
    _assert(int(heartbeat_count or 0) >= 1, f"heartbeat not persisted: {heartbeat_count}")

    run_row = adapter.fetch_one(
        """
        select id::text as run_id, status::text as status
        from strategy_runs
        where id = %s::uuid
        """,
        (run_id,),
    )
    _assert(run_row is not None, "strategy run missing in postgres")
    _assert(run_row["status"] == "running", f"run status mismatch: {run_row}")

    intent_row = adapter.fetch_one(
        """
        select id::text as intent_id, status::text as status, strategy_run_id::text as run_id
        from order_intents
        where id = %s::uuid
        """,
        (intent_id,),
    )
    _assert(intent_row is not None, "order intent missing in postgres")
    _assert(intent_row["status"] == "simulated", f"intent row mismatch: {intent_row}")
    _assert(intent_row["run_id"] == run_id, f"intent run_id mismatch: {intent_row}")

    order_rows = adapter.fetch_all(
        """
        select id::text as order_id, status::text as status
        from orders
        where order_intent_id = %s::uuid
        order by id::text
        """,
        (intent_id,),
    )
    _assert(len(order_rows) == 2, f"order row count mismatch: {order_rows}")
    _assert(
        {str(row["order_id"]) for row in order_rows} == set(order_ids),
        f"order id mismatch: {order_rows}",
    )
    _assert(
        all(str(row["status"]) == "filled" for row in order_rows),
        f"order status mismatch: {order_rows}",
    )

    fill_count = adapter.fetch_value(
        """
        select count(*) as count
        from trade_fills
        where order_id in (
            select id
            from orders
            where order_intent_id = %s::uuid
        )
        """,
        (intent_id,),
    )
    _assert(int(fill_count or 0) == 2, f"fill row count mismatch: {fill_count}")


def main() -> None:
    db_name = f"work_v6_codex_exec_{uuid4().hex[:8]}"
    redis_prefix = f"tp_exec_api_case_{uuid4().hex[:8]}"
    port = _allocate_local_port()
    base_url = f"http://127.0.0.1:{port}"
    dsn = _db_dsn(db_name)
    server: subprocess.Popen[str] | None = None

    try:
        _bootstrap_database(db_name)

        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(SRC_DIR),
                "TP_HOST": "127.0.0.1",
                "TP_PORT": str(port),
                "TP_POSTGRES_DSN": dsn,
                "TP_REDIS_URL": "redis://127.0.0.1:6379/0",
                "TP_REDIS_KEY_PREFIX": redis_prefix,
                "TP_USE_SAMPLE_READ_MODEL": "false",
                "TP_ENABLE_POSTGRES_MUTATION": "true",
                "TP_STRATEGY_RUNTIME_ENABLED": "false",
                "TP_RECOVERY_RUNTIME_ENABLED": "false",
                "TP_STRATEGY_RUNTIME_EXECUTION_ENABLED": "true",
                "TP_STRATEGY_RUNTIME_EXECUTION_MODE": "simulate_fill",
            }
        )
        server = subprocess.Popen(
            [str(PYTHON_BIN), "-m", "trading_platform.main"],
            cwd=str(ROOT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        ready_status, ready_payload = _wait_ready(base_url)
        _assert_ready_payload(ready_status, ready_payload)

        bot_id = _register_bot(base_url, f"postgres-execute-api-{uuid4().hex[:8]}")
        _record_heartbeat(base_url, bot_id)
        run_id = _create_and_start_run(base_url, bot_id)
        intent_id, order_ids = _assert_api_roundtrip(base_url, bot_id, run_id)

        adapter = PsqlCliAdapter(dsn)
        _assert_database_rows(
            adapter,
            bot_id=bot_id,
            run_id=run_id,
            intent_id=intent_id,
            order_ids=order_ids,
        )

        print("PASS postgres-backed evaluate-arbitrage execute flow persists API and DB state")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        _drop_database(db_name)


if __name__ == "__main__":
    main()
