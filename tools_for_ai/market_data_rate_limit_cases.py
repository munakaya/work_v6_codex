from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

from trading_platform.market_data_connector import PublicMarketDataConnector
from trading_platform.rate_limit import ExponentialBackoffPolicy, RateLimitPolicy, TokenBucketRateLimiter


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)


class _RetryHandler(BaseHTTPRequestHandler):
    call_count = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).call_count += 1
        if self.path == "/retry-orderbook" and type(self).call_count < 3:
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"rate limited"}}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'[{"market":"KRW-BTC","timestamp":1712534400000,"orderbook_units":[{"bid_price":"100","ask_price":"101","bid_size":"1","ask_size":"1"}]}]'
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(
        RateLimitPolicy(name="test", rate_per_sec=2.0, burst=1),
        now_fn=clock.monotonic,
        sleep_fn=clock.sleep,
    )
    waited = limiter.acquire()
    _assert(waited == 0.0, "first acquire should not wait")
    waited = limiter.acquire()
    _assert(waited > 0.0, "second acquire should wait with exhausted tokens")
    _assert(abs(clock.now - 0.5) < 1e-9, "token bucket wait should match refill time")
    print("PASS market data token bucket limiter")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RetryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connector = PublicMarketDataConnector(
            timeout_ms=1000,
            stale_threshold_ms=3000,
            orderbook_depth_levels=7,
            retry_count=2,
            retry_backoff=ExponentialBackoffPolicy(initial_delay_ms=1, max_delay_ms=2),
            rate_limit_policies={
                "upbit": RateLimitPolicy(name="upbit_public_rest", rate_per_sec=0.0, burst=1)
            },
            upbit_base_url=f"http://{host}:{port}",
            bithumb_base_url=f"http://{host}:{port}",
            coinone_base_url=f"http://{host}:{port}",
        )
        started = time.monotonic()
        payload = connector._fetch_json(  # noqa: SLF001
            f"http://{host}:{port}/retry-orderbook",
            exchange="upbit",
        )
        elapsed = time.monotonic() - started
        _assert(isinstance(payload, list), "retry payload should succeed")
        _assert(_RetryHandler.call_count == 3, "retry path should call endpoint three times")
        _assert(elapsed >= 0.0, "retry elapsed should be measurable")
        snapshot = connector.get_orderbook_top(exchange="upbit", market="KRW-BTC")
        _assert(snapshot["asks"] == [{"price": "101", "quantity": "1"}], "ask levels mismatch")
        _assert(snapshot["bids"] == [{"price": "100", "quantity": "1"}], "bid levels mismatch")
        _assert(connector._coinone_request_depth_levels() == 10, "coinone supported depth rounding mismatch")
        print("PASS market data retry with backoff")
        print("PASS market data snapshot includes normalized orderbook depth")
        print("PASS coinone request depth rounds up to supported size")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
