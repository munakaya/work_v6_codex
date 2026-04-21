from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from trading_platform.config import load_config
from trading_platform.private_exchange_connector import (
    RestPrivateExchangeConnector,
    UpbitPrivateExchangeConnector,
    build_private_exchange_connector,
    build_private_exchange_connectors,
)
from trading_platform.strategy.exchange_key_loader import ExchangeTradingCredentials


ROOT_DIR = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT_DIR / ".tmp"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _SlowHandler(BaseHTTPRequestHandler):
    delay_seconds = 0.3

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/v1/accounts":
            self.send_response(404)
            self.end_headers()
            return
        time.sleep(type(self).delay_seconds)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(b"[]")
        except BrokenPipeError:
            return

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as primary_tmp, tempfile.TemporaryDirectory(
        dir=TMP_ROOT
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

        previous_primary = os.environ.get("TP_EXCHANGE_KEY_PRIMARY_DIR")
        previous_fallback = os.environ.get("TP_EXCHANGE_KEY_FALLBACK_DIR")
        try:
            os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = str(primary_dir)
            os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = str(fallback_dir)
            config = load_config()

            upbit = build_private_exchange_connector("upbit", config=config)
            _assert(upbit.info.ready is True, "upbit connector should be ready")
            _assert(upbit.info.state == "ready_rest", "upbit connector state mismatch")
            _assert(
                isinstance(upbit, RestPrivateExchangeConnector),
                "upbit connector should be REST-backed",
            )

            bithumb = build_private_exchange_connector("bithumb", config=config)
            _assert(bithumb.info.ready is True, "bithumb connector should be ready")
            _assert(
                bithumb.info.state == "ready_rest",
                "bithumb connector state mismatch",
            )
            _assert(
                "bithumb.json" in str(bithumb.info.credential_source_path),
                "bithumb fallback path mismatch",
            )

            coinone = build_private_exchange_connector("coinone", config=config)
            _assert(coinone.info.ready is False, "coinone connector should be unavailable")
            _assert(coinone.get_balances().outcome == "unavailable", "coinone outcome mismatch")
            _assert(
                coinone.get_balances().error_code == "AUTH_CONFIG_MISSING",
                "coinone unavailable error_code mismatch",
            )

            bundle = build_private_exchange_connectors(config=config)
            _assert(set(bundle) == {"upbit", "bithumb", "coinone"}, "bundle keys mismatch")
            print("PASS private exchange connector readiness")

            credentials = ExchangeTradingCredentials(
                exchange="upbit",
                access_key="upbit-access",
                secret_key="upbit-secret",
                source_path=primary_dir / "upbit_trading.json",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                timeout_connector = UpbitPrivateExchangeConnector(
                    exchange="upbit",
                    credentials=credentials,
                    base_url=f"http://{host}:{port}",
                    timeout_ms=100,
                    timeout_ms_by_operation={"get_balances": 100},
                )
                result = timeout_connector.get_balances()
                _assert(result.outcome == "error", "timeout result should be error")
                _assert(result.error_code == "NETWORK_ERROR", "timeout error code mismatch")
                _assert(result.retryable is True, "timeout should be retryable")
                _assert(
                    "get_balances request timed out after" in str(result.reason),
                    "timeout reason should include operation and timeout",
                )
                print("PASS private exchange connector applies operation timeout budget")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1.0)
        finally:
            if previous_primary is None:
                os.environ.pop("TP_EXCHANGE_KEY_PRIMARY_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = previous_primary
            if previous_fallback is None:
                os.environ.pop("TP_EXCHANGE_KEY_FALLBACK_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = previous_fallback


if __name__ == "__main__":
    main()
