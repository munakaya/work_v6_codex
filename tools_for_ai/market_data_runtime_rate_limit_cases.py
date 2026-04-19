from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_json(url: str) -> tuple[int, dict[str, object]]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _wait_json(url: str) -> tuple[int, dict[str, object]]:
    deadline = time.monotonic() + 10.0
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, payload = _read_json(url)
            if status in {200, 503}:
                return status, payload
        except Exception as exc:  # pragma: no cover - polling helper
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"endpoint did not respond in time: {url} error={last_error}")


def main() -> None:
    port = _allocate_local_port()
    env = os.environ.copy()
    env.update(
        {
            "TP_PORT": str(port),
            "TP_USE_SAMPLE_READ_MODEL": "true",
            "TP_MARKET_DATA_POLL_ENABLED": "false",
            "TP_STRATEGY_RUNTIME_ENABLED": "false",
            "TP_RECOVERY_RUNTIME_ENABLED": "false",
            "TP_UPBIT_PUBLIC_REST_RATE_LIMIT_PER_SEC": "5",
            "TP_UPBIT_PUBLIC_REST_BURST": "2",
            "TP_BITHUMB_PUBLIC_REST_RATE_LIMIT_PER_SEC": "3",
            "TP_BITHUMB_PUBLIC_REST_BURST": "1",
            "TP_COINONE_PUBLIC_REST_RATE_LIMIT_PER_SEC": "0",
            "TP_COINONE_PUBLIC_REST_BURST": "1",
            "TP_MARKET_DATA_RETRY_COUNT": "2",
            "TP_MARKET_DATA_RETRY_BACKOFF_INITIAL_MS": "100",
            "TP_MARKET_DATA_RETRY_BACKOFF_MAX_MS": "800",
            "TP_MARKET_DATA_ORDERBOOK_DEPTH_LEVELS": "7",
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
        _wait_json(f"http://127.0.0.1:{port}/api/v1/ready")
        status, payload = _wait_json(f"http://127.0.0.1:{port}/api/v1/market-data/runtime")
        _assert(status == 200, "market data runtime endpoint should succeed")
        rate_limits = payload["data"]["rate_limits"]
        _assert(rate_limits["count"] == 3, "rate limit count mismatch")
        _assert(rate_limits["retry_count"] == 2, "retry count mismatch")
        _assert(
            rate_limits["retry_backoff"]["initial_delay_ms"] == 100,
            "retry backoff initial mismatch",
        )
        items = {item["name"]: item for item in rate_limits["items"]}
        _assert(items["upbit_public_rest"]["rate_per_sec"] == 5.0, "upbit rps mismatch")
        _assert(items["upbit_public_rest"]["burst"] == 2, "upbit burst mismatch")
        _assert(items["coinone_public_rest"]["enabled"] is False, "coinone enabled mismatch")
        _assert(rate_limits["orderbook_depth_levels"] == 7, "orderbook depth level mismatch")
        print("PASS market data runtime exposes rate limit config")
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)


if __name__ == "__main__":
    main()
