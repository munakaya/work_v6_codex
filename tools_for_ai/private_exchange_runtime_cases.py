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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
            _wait_json(f"http://127.0.0.1:{port}/api/v1/ready")
            status, payload = _wait_json(
                f"http://127.0.0.1:{port}/api/v1/runtime/private-connectors"
            )
            _assert(status == 200, "private connector runtime endpoint should be reachable")
            data = payload["data"]
            _assert(data["count"] == 3, "private connector count mismatch")
            _assert(data["ready_count"] == 2, "private connector ready count mismatch")
            _assert(data["overall_state"] == "partial", "private connector overall mismatch")
            items = {item["exchange"]: item for item in data["items"]}
            _assert(
                items["upbit"]["state"] == "ready_not_implemented",
                "upbit runtime state mismatch",
            )
            _assert(
                items["coinone"]["state"] == "not_found",
                "coinone runtime state mismatch",
            )
            status, payload = _read_json(
                f"http://127.0.0.1:{port}/api/v1/runtime/private-connectors?exchange=upbit"
            )
            _assert(status == 200, "filtered private connector endpoint should succeed")
            _assert(payload["data"]["count"] == 1, "filtered private connector count mismatch")
            status, payload = _read_json(
                f"http://127.0.0.1:{port}/api/v1/runtime/private-connectors?exchange=sample"
            )
            _assert(status == 404, "unsupported exchange filter should return 404")
            print("PASS runtime private connector endpoint reports connector states")
        finally:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)


if __name__ == "__main__":
    main()
