from __future__ import annotations

from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib import error, request
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:38765"
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


class _PrivateExecHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        payload = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size).decode("utf-8"))
        target_qty = str(body.get("target_qty") or "0.2")
        mode = self.path.lstrip("/") or "filled"
        orders = [
            {
                "exchange_name": str(body["buy_exchange"]),
                "exchange_order_id": f"{mode}-buy-001",
                "market": str(body["market"]),
                "side": "buy",
                "requested_qty": target_qty,
                "status": "submitted",
                "raw_payload": {"remote_mode": mode},
            },
            {
                "exchange_name": str(body["sell_exchange"]),
                "exchange_order_id": f"{mode}-sell-001",
                "market": str(body["market"]),
                "side": "sell",
                "requested_qty": target_qty,
                "status": "submitted",
                "raw_payload": {"remote_mode": mode},
            },
        ]
        if mode == "failed":
            payload = {
                "outcome": "submit_failed",
                "orders": [],
                "details": {"reason": "remote private submit rejected", "remote_mode": mode},
            }
        elif mode == "submitted":
            payload = {
                "outcome": "submitted",
                "orders": orders,
                "details": {"remote_mode": mode},
            }
        else:
            payload = {
                "outcome": "filled",
                "orders": orders,
                "fills": [
                    {
                        "exchange_name": str(body["buy_exchange"]),
                        "side": "buy",
                        "exchange_trade_id": f"{mode}-buy-fill-001",
                        "fill_price": "100000",
                        "fill_qty": target_qty,
                        "filled_at": _iso_now(),
                    },
                    {
                        "exchange_name": str(body["sell_exchange"]),
                        "side": "sell",
                        "exchange_trade_id": f"{mode}-sell-fill-001",
                        "fill_price": "100500",
                        "fill_qty": target_qty,
                        "filled_at": _iso_now(),
                    },
                ],
                "details": {"remote_mode": mode},
            }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _run_case(mode: str, *, submit_url: str, health_url: str) -> None:
    redis_prefix = f"tp_private_http_server_case_{mode}_{uuid4().hex[:8]}"
    env = os.environ.copy()
    env.update(
        {
            "TP_REDIS_URL": "redis://127.0.0.1:6379/0",
            "TP_REDIS_KEY_PREFIX": redis_prefix,
            "TP_STRATEGY_RUNTIME_EXECUTION_ENABLED": "true",
            "TP_STRATEGY_RUNTIME_EXECUTION_MODE": "private_http",
            "TP_STRATEGY_PRIVATE_EXECUTION_URL": submit_url,
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
        private_dep = ready_payload["data"]["dependencies"]["private_execution"]
        _assert(private_dep["configured"] is True, f"{mode}: private execution not configured")
        _assert(private_dep["reachable"] is True, f"{mode}: private execution not reachable")

        bot_id, run_id = _register_and_start_run(f"private-http-server-{mode}-{uuid4().hex[:6]}")
        status, payload = _http_json(
            "POST",
            f"/api/v1/strategy-runs/{run_id}/evaluate-arbitrage",
            _evaluate_payload(persist_intent=True, execute=True),
        )
        _assert(status == 201, f"{mode}: evaluate execute failed: {status} {payload}")
        data = payload["data"]
        if mode == "filled":
            _assert(data["submit_result"]["outcome"] == "filled", f"{mode}: submit result mismatch")
            _assert(data["lifecycle_preview"] == "closed", f"{mode}: lifecycle mismatch")
            latest_status, latest_payload = _http_json(
                "GET", f"/api/v1/strategy-runs/{run_id}/latest-evaluation"
            )
            _assert(latest_status == 200, f"{mode}: latest evaluation fetch failed")
            _assert(
                latest_payload["data"]["lifecycle_preview"] == "closed",
                f"{mode}: latest evaluation lifecycle mismatch: {latest_payload}",
            )
        elif mode == "submitted":
            _assert(
                data["submit_result"]["outcome"] == "submitted",
                f"{mode}: submit result mismatch",
            )
            _assert(
                data["lifecycle_preview"] == "entry_submitting",
                f"{mode}: lifecycle mismatch",
            )
            orders_status, orders_payload = _http_json(
                "GET", f"/api/v1/orders?strategy_run_id={run_id}"
            )
            _assert(orders_status == 200, f"{mode}: orders fetch failed")
            _assert(len(orders_payload["data"]) == 2, f"{mode}: expected 2 orders")
        else:
            _assert(
                data["submit_result"]["outcome"] == "submit_failed",
                f"{mode}: submit result mismatch",
            )
            _assert(
                data["lifecycle_preview"] in {"recovery_required", "unwind_in_progress"},
                f"{mode}: lifecycle mismatch",
            )
            traces_status, traces_payload = _http_json(
                "GET", f"/api/v1/recovery-traces?run_id={run_id}"
            )
            _assert(traces_status == 200, f"{mode}: traces fetch failed")
            _assert(traces_payload["data"]["count"] >= 1, f"{mode}: recovery trace missing")
        print(f"PASS private_http server case {mode}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def main() -> None:
    _assert(PYTHON_BIN.exists(), f"missing virtualenv python: {PYTHON_BIN}")
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _PrivateExecHandler)
    thread = threading.Thread(target=stub.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = stub.server_address
        health_url = f"http://{host}:{port}/health"
        base_submit = f"http://{host}:{port}"
        for mode in ("filled", "submitted", "failed"):
            _run_case(
                mode,
                submit_url=f"{base_submit}/{mode}",
                health_url=health_url,
            )
    finally:
        stub.shutdown()
        stub.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
