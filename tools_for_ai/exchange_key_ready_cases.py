from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
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


def _wait_ready(base_url: str) -> tuple[int, dict[str, object]]:
    deadline = time.monotonic() + 10.0
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, payload = _read_json(f"{base_url}/api/v1/ready")
            if status in {200, 503}:
                return status, payload
        except Exception as exc:  # pragma: no cover - polling helper
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"ready endpoint did not respond in time: {last_error}")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT_DIR / ".tmp") as primary_tmp, tempfile.TemporaryDirectory(
        dir=ROOT_DIR / ".tmp"
    ) as fallback_tmp:
        primary_dir = Path(primary_tmp)
        fallback_dir = Path(fallback_tmp)
        _write(
            primary_dir / "upbit_trading.json",
            '{"access_key":"upbit-access","secret_key":"upbit-secret"}',
        )
        _write(
            fallback_dir / "bithumb.json",
            '{"api_key":"bithumb-access","secret_key":"bithumb-secret"}',
        )
        _write(
            fallback_dir / "coinone.json",
            '{"access_key":"coinone-access"}',
        )

        port = _allocate_local_port()
        env = os.environ.copy()
        env.update(
            {
                "TP_PORT": str(port),
                "TP_USE_SAMPLE_READ_MODEL": "true",
                "TP_STRATEGY_RUNTIME_ENABLED": "false",
                "TP_RECOVERY_RUNTIME_ENABLED": "false",
                "TP_EXCHANGE_KEY_PRIMARY_DIR": str(primary_dir),
                "TP_EXCHANGE_KEY_FALLBACK_DIR": str(fallback_dir),
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
            status, payload = _wait_ready(f"http://127.0.0.1:{port}")
            _assert(status == 503, "sample store readiness should remain degraded")
            dependency = payload["data"]["dependencies"]["exchange_trading_keys"]
            _assert(dependency["count"] == 3, "key dependency count mismatch")
            _assert(dependency["configured_count"] == 3, "configured key count mismatch")
            _assert(dependency["ready_count"] == 2, "ready key count mismatch")
            _assert(dependency["overall_state"] == "partial", "overall key state mismatch")
            items = {item["exchange"]: item for item in dependency["items"]}
            _assert(items["upbit"]["state"] == "primary_ready", "upbit key state mismatch")
            _assert(
                items["bithumb"]["access_key_field"] == "api_key",
                "bithumb legacy field mismatch",
            )
            _assert(
                items["coinone"]["state"] == "fallback_missing_secret_key",
                "coinone invalid state mismatch",
            )
            print("PASS ready endpoint reports exchange trading key states")
        finally:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)


if __name__ == "__main__":
    main()
