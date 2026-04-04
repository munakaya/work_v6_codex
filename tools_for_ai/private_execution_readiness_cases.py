from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from trading_platform.storage.dependencies import private_execution_status


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        health_url = f"http://{host}:{port}/health"
        submit_url = f"http://{host}:{port}/submit"

        ok_status = private_execution_status(
            execution_enabled=True,
            execution_mode="private_http",
            submit_url=submit_url,
            health_url=health_url,
            timeout_ms=1000,
        )
        _assert(ok_status.configured, "health probe should be configured")
        _assert(ok_status.reachable, "health probe should be reachable")
        _assert(ok_status.state == "reachable", "health probe state mismatch")

        missing_health = private_execution_status(
            execution_enabled=True,
            execution_mode="private_http",
            submit_url=submit_url,
            health_url=None,
            timeout_ms=1000,
        )
        _assert(not missing_health.configured, "missing health url should be unconfigured")
        _assert(
            missing_health.state == "health_url_missing",
            "missing health url state mismatch",
        )

        not_required = private_execution_status(
            execution_enabled=False,
            execution_mode="private_http",
            submit_url=submit_url,
            health_url=health_url,
            timeout_ms=1000,
        )
        _assert(not_required.state == "not_required", "not_required state mismatch")

        print("PASS private execution health probe reachable")
        print("PASS private execution missing health url detected")
        print("PASS private execution not-required mode skipped")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
