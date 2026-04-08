from __future__ import annotations

from copy import deepcopy
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


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
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
        _wait_json(f"http://127.0.0.1:{port}/api/v1/ready")
        status, payload = _read_json(f"http://127.0.0.1:{port}/api/v1/bots")
        _assert(status == 200, "bots endpoint should succeed")
        bot_id = str(payload["data"]["items"][0]["bot_id"])

        status, payload = _read_json(f"http://127.0.0.1:{port}/api/v1/configs/default/latest")
        _assert(status == 200, "latest config should exist")
        latest_config = payload["data"]

        hot_config_json = deepcopy(latest_config["config_json"])
        hot_config_json["arbitrage_runtime"]["risk_config"]["min_profit_quote"] = "1100"
        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/configs",
            {
                "config_scope": "default",
                "config_json": hot_config_json,
                "checksum": "chk-default-hot-v4",
            },
        )
        _assert(status == 201, "hot config create should succeed")
        hot_version = int(payload["data"]["version_no"])
        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/bots/{bot_id}/assign-config",
            {"config_scope": "default", "version_no": hot_version},
        )
        _assert(status == 202, "assign hot config should succeed")
        assigned = payload["data"]
        _assert(assigned["apply_status"] == "pending", "hot config should start pending")
        _assert(assigned["apply_policy"] == "hot_reload", "hot config policy mismatch")
        _assert(
            assigned["hot_reloadable_sections"] == ["arbitrage_runtime.risk_config"],
            "hot reloadable sections mismatch",
        )

        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/bots/{bot_id}/config-ack",
            {"ack_status": "APPLIED", "ack_message": "risk config hot reloaded"},
        )
        _assert(status == 202, "hot config ack should succeed")
        _assert(payload["data"]["apply_status"] == "applied", "applied ack mismatch")

        status, payload = _read_json(f"http://127.0.0.1:{port}/api/v1/bots/{bot_id}")
        _assert(status == 200, "bot detail should succeed")
        assigned_detail = payload["data"]["assigned_config_version"]
        _assert(assigned_detail["apply_status"] == "applied", "bot detail apply status mismatch")
        _assert(
            assigned_detail["ack_message"] == "risk config hot reloaded",
            "bot detail ack message mismatch",
        )

        restart_config_json = deepcopy(hot_config_json)
        restart_config_json["arbitrage_runtime"]["market"] = "KRW-ETH"
        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/configs",
            {
                "config_scope": "default",
                "config_json": restart_config_json,
                "checksum": "chk-default-restart-v5",
            },
        )
        _assert(status == 201, "restart config create should succeed")
        restart_version = int(payload["data"]["version_no"])
        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/bots/{bot_id}/assign-config",
            {"config_scope": "default", "version_no": restart_version},
        )
        _assert(status == 202, "assign restart config should succeed")
        assigned = payload["data"]
        _assert(
            assigned["apply_policy"] == "restart_required",
            "restart config policy mismatch",
        )
        _assert(
            "arbitrage_runtime.market" in assigned["restart_required_sections"],
            "restart-required section mismatch",
        )

        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/v1/bots/{bot_id}/config-ack",
            {
                "ack_status": "RESTART_REQUIRED",
                "ack_message": "market symbol change requires restart",
            },
        )
        _assert(status == 202, "restart-required ack should succeed")
        _assert(
            payload["data"]["apply_status"] == "restart_required",
            "restart-required ack status mismatch",
        )
        print("PASS hot config assign/ack contract reports pending/applied/restart_required")
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)


if __name__ == "__main__":
    main()
