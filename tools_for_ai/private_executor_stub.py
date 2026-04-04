from __future__ import annotations

from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import threading


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _build_payload(*, mode: str, body: dict[str, object]) -> dict[str, object]:
    target_qty = str(body.get("target_qty") or "0.2")
    buy_exchange = str(body.get("buy_exchange") or "")
    sell_exchange = str(body.get("sell_exchange") or "")
    market = str(body.get("market") or "")
    orders = [
        {
            "exchange_name": buy_exchange,
            "exchange_order_id": f"{mode}-buy-001",
            "market": market,
            "side": "buy",
            "requested_qty": target_qty,
            "status": "submitted",
            "raw_payload": {"remote_mode": mode},
        },
        {
            "exchange_name": sell_exchange,
            "exchange_order_id": f"{mode}-sell-001",
            "market": market,
            "side": "sell",
            "requested_qty": target_qty,
            "status": "submitted",
            "raw_payload": {"remote_mode": mode},
        },
    ]
    if mode == "failed":
        return {
            "outcome": "submit_failed",
            "orders": [],
            "details": {"reason": "remote private submit rejected", "remote_mode": mode},
        }
    if mode == "submitted":
        return {
            "outcome": "submitted",
            "orders": orders,
            "details": {"remote_mode": mode},
        }
    filled_orders = [
        {**order, "status": "filled"}
        for order in orders
    ]
    return {
        "outcome": "filled",
        "lifecycle_preview": "closed",
        "orders": filled_orders,
        "fills": [
            {
                "exchange_name": buy_exchange,
                "side": "buy",
                "exchange_trade_id": f"{mode}-buy-fill-001",
                "fill_price": "100000",
                "fill_qty": target_qty,
                "filled_at": _iso_now(),
            },
            {
                "exchange_name": sell_exchange,
                "side": "sell",
                "exchange_trade_id": f"{mode}-sell-fill-001",
                "fill_price": "100500",
                "fill_qty": target_qty,
                "filled_at": _iso_now(),
            },
        ],
        "details": {"remote_mode": mode},
    }


def build_private_executor_handler(default_mode: str = "filled") -> type[BaseHTTPRequestHandler]:
    normalized_default_mode = default_mode.strip() or "filled"

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
            mode = self.path.lstrip("/") or normalized_default_mode
            payload = _build_payload(mode=mode, body=body)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return _PrivateExecHandler


def start_private_executor_stub(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    default_mode: str = "filled",
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), build_private_executor_handler(default_mode))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a local private_http executor stub for arbitrage testing.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--default-mode", default="filled")
    args = parser.parse_args()

    server, thread = start_private_executor_stub(
        host=args.host,
        port=args.port,
        default_mode=args.default_mode,
    )
    try:
        host, port = server.server_address
        print(f"stub_submit_base=http://{host}:{port}")
        print(f"stub_health_url=http://{host}:{port}/health")
        print(f"stub_default_mode={args.default_mode}")
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
