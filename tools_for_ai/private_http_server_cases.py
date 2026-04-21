from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib import error, request
from uuid import uuid4

from private_executor_stub import start_private_executor_stub


ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:38765"
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"


@dataclass(frozen=True)
class CaseSpec:
    name: str
    submit_path: str
    expected_outcome: str
    expected_lifecycles: tuple[str, ...]
    expected_order_count: int
    expected_fill_count: int
    expected_reason: str | None = None
    expect_recovery_trace: bool = False


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        BASE_URL + path,
        method=method,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _wait_ready(timeout_seconds: float = 10.0) -> dict[str, object]:
    started = time.monotonic()
    last_payload: dict[str, object] | None = None
    while time.monotonic() - started < timeout_seconds:
        try:
            status, payload = _http_json("GET", "/api/v1/ready")
            last_payload = payload
            if status in {200, 503}:
                return payload
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"server did not become ready in time: {last_payload}")


def _register_and_start_run(bot_key: str) -> tuple[str, str]:
    status, payload = _http_json(
        "POST",
        "/api/v1/bots/register",
        {
            "bot_key": bot_key,
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "hostname": "private-http-server-case",
        },
    )
    _assert(status == 200, f"bot register failed: {status} {payload}")
    bot_id = str(payload["data"]["bot_id"])
    status, payload = _http_json(
        "POST",
        "/api/v1/strategy-runs",
        {
            "bot_id": bot_id,
            "strategy_name": "arbitrage",
            "mode": "shadow",
        },
    )
    _assert(status == 201, f"strategy run create failed: {status} {payload}")
    run_id = str(payload["data"]["run_id"])
    status, payload = _http_json("POST", f"/api/v1/strategy-runs/{run_id}/start", {})
    _assert(status == 202, f"strategy run start failed: {status} {payload}")
    return bot_id, run_id


def _evaluate_payload(*, persist_intent: bool, execute: bool) -> dict[str, object]:
    return {
        "persist_intent": persist_intent,
        "execute": execute,
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


def _assert_ready_metadata(ready_payload: dict[str, object]) -> None:
    private_dep = ready_payload["data"]["dependencies"]["private_execution"]
    _assert(private_dep["configured"] is True, "private execution not configured")
    _assert(private_dep["reachable"] is True, "private execution not reachable")
    _assert(private_dep["mode"] == "private_http", "private execution mode mismatch")
    _assert(
        private_dep["path_kind"] == "temporary_external_delegate",
        "private execution path_kind mismatch",
    )
    _assert(private_dep["temporary"] is True, "private execution temporary mismatch")
    strategy_runtime = ready_payload["data"]["strategy_runtime"]
    _assert(strategy_runtime["execution_mode"] == "private_http", "execution mode mismatch")
    _assert(
        strategy_runtime["execution_path_kind"] == "temporary_external_delegate",
        "execution path kind mismatch",
    )
    _assert(
        strategy_runtime["execution_path_temporary"] is True,
        "execution path temporary mismatch",
    )


def _response_item_count(payload: dict[str, object]) -> int:
    data = payload.get("data")
    if isinstance(data, dict):
        count = data.get("count")
        if isinstance(count, int):
            return count
        items = data.get("items")
        if isinstance(items, list):
            return len(items)
    if isinstance(data, list):
        return len(data)
    return 0


def _assert_case_result(case: CaseSpec, *, run_id: str, payload: dict[str, object]) -> None:
    data = payload["data"]
    submit_result = data["submit_result"]
    _assert(
        submit_result["outcome"] == case.expected_outcome,
        f"{case.name}: submit result mismatch: {submit_result}",
    )
    lifecycle = str(data.get("lifecycle_preview") or "")
    _assert(
        lifecycle in case.expected_lifecycles,
        f"{case.name}: lifecycle mismatch: {lifecycle}",
    )
    if case.expected_reason is not None:
        details = submit_result.get("details") if isinstance(submit_result, dict) else None
        reason = str(details.get("reason") or "") if isinstance(details, dict) else ""
        _assert(reason == case.expected_reason, f"{case.name}: reason mismatch: {reason}")

    latest_status, latest_payload = _http_json(
        "GET", f"/api/v1/strategy-runs/{run_id}/latest-evaluation"
    )
    _assert(latest_status == 200, f"{case.name}: latest evaluation fetch failed")
    latest_data = latest_payload["data"]
    _assert(
        str(latest_data.get("lifecycle_preview") or "") in case.expected_lifecycles,
        f"{case.name}: latest evaluation lifecycle mismatch: {latest_data}",
    )
    latest_submit = latest_data.get("submit_result")
    _assert(
        isinstance(latest_submit, dict)
        and str(latest_submit.get("outcome") or "") == case.expected_outcome,
        f"{case.name}: latest evaluation submit result mismatch: {latest_data}",
    )

    orders_status, orders_payload = _http_json("GET", f"/api/v1/orders?strategy_run_id={run_id}")
    _assert(orders_status == 200, f"{case.name}: orders fetch failed")
    _assert(
        _response_item_count(orders_payload) == case.expected_order_count,
        f"{case.name}: order count mismatch: {orders_payload}",
    )

    fills_status, fills_payload = _http_json("GET", f"/api/v1/fills?strategy_run_id={run_id}")
    _assert(fills_status == 200, f"{case.name}: fills fetch failed")
    _assert(
        _response_item_count(fills_payload) == case.expected_fill_count,
        f"{case.name}: fill count mismatch: {fills_payload}",
    )

    traces_status, traces_payload = _http_json("GET", f"/api/v1/recovery-traces?run_id={run_id}")
    _assert(traces_status == 200, f"{case.name}: recovery traces fetch failed")
    trace_count = int(traces_payload["data"].get("count") or 0)
    if case.expect_recovery_trace:
        _assert(trace_count >= 1, f"{case.name}: recovery trace missing")
    else:
        _assert(trace_count == 0, f"{case.name}: unexpected recovery trace: {traces_payload}")


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        name="filled",
        submit_path="/filled",
        expected_outcome="filled",
        expected_lifecycles=("closed",),
        expected_order_count=2,
        expected_fill_count=2,
    ),
    CaseSpec(
        name="submitted",
        submit_path="/submitted",
        expected_outcome="submitted",
        expected_lifecycles=("entry_submitting",),
        expected_order_count=2,
        expected_fill_count=0,
    ),
    CaseSpec(
        name="failed",
        submit_path="/failed",
        expected_outcome="submit_failed",
        expected_lifecycles=("recovery_required", "unwind_in_progress"),
        expected_order_count=0,
        expected_fill_count=0,
        expect_recovery_trace=True,
    ),
    CaseSpec(
        name="submitted_with_fill_malformed",
        submit_path="/submitted-with-fill",
        expected_outcome="submit_failed",
        expected_lifecycles=("recovery_required", "unwind_in_progress"),
        expected_order_count=0,
        expected_fill_count=0,
        expected_reason="private execution submitted outcome must not include fills",
        expect_recovery_trace=True,
    ),
    CaseSpec(
        name="submit_failed_filled_order_no_fill_malformed",
        submit_path="/submit-failed-filled-order-no-fill",
        expected_outcome="submit_failed",
        expected_lifecycles=("recovery_required", "unwind_in_progress"),
        expected_order_count=0,
        expected_fill_count=0,
        expected_reason="private execution submit_failed outcome missing fills for filled orders",
        expect_recovery_trace=True,
    ),
    CaseSpec(
        name="filled_bad_preview_malformed",
        submit_path="/filled-bad-preview",
        expected_outcome="submit_failed",
        expected_lifecycles=("recovery_required", "unwind_in_progress"),
        expected_order_count=0,
        expected_fill_count=0,
        expected_reason=(
            "private execution lifecycle_preview is inconsistent with outcome: "
            "filled:entry_submitting"
        ),
        expect_recovery_trace=True,
    ),
)


def _run_case(case: CaseSpec, *, health_url: str, submit_base: str) -> None:
    global BASE_URL
    redis_prefix = f"tp_private_http_server_case_{case.name}_{uuid4().hex[:8]}"
    server_port = _allocate_local_port()
    BASE_URL = f"http://127.0.0.1:{server_port}"
    env = os.environ.copy()
    env.update(
        {
            "TP_PORT": str(server_port),
            "TP_REDIS_URL": "redis://127.0.0.1:6379/0",
            "TP_REDIS_KEY_PREFIX": redis_prefix,
            "TP_USE_SAMPLE_READ_MODEL": "true",
            "TP_STRATEGY_RUNTIME_EXECUTION_ENABLED": "true",
            "TP_STRATEGY_RUNTIME_EXECUTION_MODE": "private_http",
            "TP_STRATEGY_PRIVATE_EXECUTION_URL": f"{submit_base}{case.submit_path}",
            "TP_STRATEGY_PRIVATE_EXECUTION_HEALTH_URL": health_url,
            "TP_STRATEGY_RUNTIME_ENABLED": "false",
            "TP_RECOVERY_RUNTIME_ENABLED": "false",
        }
    )
    server = subprocess.Popen(
        [str(PYTHON_BIN), "-m", "trading_platform.main"],
        cwd=str(ROOT_DIR),
        env={**env, "PYTHONPATH": str(ROOT_DIR / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        ready_payload = _wait_ready()
        _assert_ready_metadata(ready_payload)

        _bot_id, run_id = _register_and_start_run(
            f"private-http-server-{case.name}-{uuid4().hex[:6]}"
        )
        status, payload = _http_json(
            "POST",
            f"/api/v1/strategy-runs/{run_id}/evaluate-arbitrage",
            _evaluate_payload(persist_intent=True, execute=True),
        )
        _assert(status == 201, f"{case.name}: evaluate execute failed: {status} {payload}")
        _assert_case_result(case, run_id=run_id, payload=payload)
        print(f"PASS private_http server case {case.name}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def main() -> None:
    _assert(PYTHON_BIN.exists(), f"missing virtualenv python: {PYTHON_BIN}")
    stub, thread = start_private_executor_stub(default_mode="filled")
    try:
        host, port = stub.server_address
        health_url = f"http://{host}:{port}/health"
        submit_base = f"http://{host}:{port}"
        for case in CASES:
            _run_case(case, health_url=health_url, submit_base=submit_base)
    finally:
        stub.shutdown()
        stub.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
