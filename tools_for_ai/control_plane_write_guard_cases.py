from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib import error, request
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = dict(headers or {})
    if body is not None:
        req_headers.setdefault("Content-Type", "application/json")
    req = request.Request(
        base_url + path,
        method=method,
        data=body,
        headers=req_headers,
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return (
                response.status,
                json.loads(response.read().decode("utf-8")),
                dict(response.headers.items()),
            )
    except error.HTTPError as exc:
        return (
            exc.code,
            json.loads(exc.read().decode("utf-8")),
            dict(exc.headers.items()),
        )


def _wait_health(base_url: str, timeout_seconds: float = 10.0) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        try:
            status, _payload, _headers = _http_json(base_url, "GET", "/api/v1/health")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become healthy in time")


def _wait_ready(base_url: str, timeout_seconds: float = 10.0) -> dict[str, object]:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        try:
            status, payload, _headers = _http_json(base_url, "GET", "/api/v1/ready")
            if status in {200, 503}:
                return payload
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become ready in time")


def _start_server(env_overrides: dict[str, str]) -> tuple[subprocess.Popen[str], str]:
    port = _allocate_local_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT_DIR / "src"),
            "TP_PORT": str(port),
            "TP_USE_SAMPLE_READ_MODEL": "true",
            "TP_STRATEGY_RUNTIME_ENABLED": "false",
            "TP_RECOVERY_RUNTIME_ENABLED": "false",
        }
    )
    env.update(env_overrides)
    process = subprocess.Popen(
        [str(PYTHON_BIN), "-m", "trading_platform.main"],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _wait_health(base_url)
    return process, base_url


def _stop_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_bot(
    base_url: str,
    *,
    bot_key: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    return _http_json(
        base_url,
        "POST",
        "/api/v1/bots/register",
        {
            "bot_key": bot_key,
            "strategy_name": "arbitrage",
            "mode": "shadow",
        },
        headers=headers,
    )


def _run_auth_case() -> None:
    token = "guard-secret-token"
    process, base_url = _start_server(
        {
            "TP_ADMIN_TOKEN": token,
            "TP_CONTROL_PLANE_WRITE_RATE_LIMIT_WINDOW_MS": "10000",
            "TP_CONTROL_PLANE_WRITE_RATE_LIMIT_MAX_REQUESTS": "20",
        }
    )
    try:
        ready_payload = _wait_ready(base_url)
        write_guard = ready_payload["data"]["write_api_guard"]
        _assert(write_guard["auth_enabled"] is True, f"auth guard not exposed: {ready_payload}")
        _assert(write_guard["rate_limit_enabled"] is True, f"rate limit not exposed: {ready_payload}")

        status, payload, headers = _register_bot(
            base_url, bot_key=f"guard-auth-missing-{uuid4().hex[:6]}"
        )
        _assert(status == 401, f"missing auth should fail: {status} {payload}")
        _assert(
            payload["error"]["code"] == "ADMIN_AUTH_REQUIRED",
            f"missing auth error mismatch: {payload}",
        )
        _assert(
            headers.get("WWW-Authenticate") == "Bearer",
            f"missing auth header mismatch: {headers}",
        )

        status, payload, _headers = _register_bot(
            base_url,
            bot_key=f"guard-auth-wrong-{uuid4().hex[:6]}",
            headers=_auth_headers("wrong-token"),
        )
        _assert(status == 401, f"wrong auth should fail: {status} {payload}")

        status, payload, _headers = _http_json(base_url, "GET", "/api/v1/health")
        _assert(status == 200, f"GET health should stay open: {status} {payload}")

        status, payload, _headers = _register_bot(
            base_url,
            bot_key=f"guard-auth-ok-{uuid4().hex[:6]}",
            headers=_auth_headers(token),
        )
        _assert(status == 200, f"authorized register failed: {status} {payload}")
        print("PASS write API bearer token guard")
    finally:
        _stop_server(process)


def _run_rate_limit_case() -> None:
    token = "guard-rate-limit-token"
    process, base_url = _start_server(
        {
            "TP_ADMIN_TOKEN": token,
            "TP_CONTROL_PLANE_WRITE_RATE_LIMIT_WINDOW_MS": "1000",
            "TP_CONTROL_PLANE_WRITE_RATE_LIMIT_MAX_REQUESTS": "2",
        }
    )
    try:
        ready_payload = _wait_ready(base_url)
        write_guard = ready_payload["data"]["write_api_guard"]
        _assert(
            write_guard["rate_limit_max_requests"] == 2,
            f"rate limit max_requests mismatch: {ready_payload}",
        )
        _assert(
            write_guard["rate_limit_window_ms"] == 1000,
            f"rate limit window mismatch: {ready_payload}",
        )

        for index in range(2):
            status, payload, _headers = _register_bot(
                base_url,
                bot_key=f"guard-rate-ok-{index}-{uuid4().hex[:6]}",
                headers=_auth_headers(token),
            )
            _assert(status == 200, f"authorized request {index} failed: {status} {payload}")

        status, payload, headers = _register_bot(
            base_url,
            bot_key=f"guard-rate-blocked-{uuid4().hex[:6]}",
            headers=_auth_headers(token),
        )
        _assert(status == 429, f"rate limit should block third write: {status} {payload}")
        _assert(
            payload["error"]["code"] == "WRITE_RATE_LIMITED",
            f"rate limit error mismatch: {payload}",
        )
        retry_after_ms = payload["error"].get("retry_after_ms")
        _assert(
            isinstance(retry_after_ms, int) and retry_after_ms > 0,
            f"retry_after_ms missing: {payload}",
        )
        _assert(
            int(headers.get("Retry-After", "0")) >= 1,
            f"Retry-After header missing: {headers}",
        )
        print("PASS write API rate limit guard")
    finally:
        _stop_server(process)


def main() -> None:
    _run_auth_case()
    _run_rate_limit_case()


if __name__ == "__main__":
    main()
