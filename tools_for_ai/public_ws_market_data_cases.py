from __future__ import annotations

import base64
import hashlib
import json
import socket
import socketserver
import threading
from urllib.parse import urlparse

from trading_platform.market_data_connector import MarketDataError
from trading_platform.public_ws_market_data import PublicWebSocketMarketDataConnector
from trading_platform.rate_limit import ExponentialBackoffPolicy


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _SingleShotWebSocketHandler(socketserver.BaseRequestHandler):
    callback = None

    def handle(self) -> None:
        callback = type(self).callback
        if callback is None:
            raise RuntimeError("websocket callback is not configured")
        request = self._read_http_request()
        key = self._sec_websocket_key(request)
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.request.sendall(response.encode("ascii"))
        message = self._recv_text()
        for payload in callback(json.loads(message)):
            self._send_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))

    def _read_http_request(self) -> str:
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            payload.extend(chunk)
        return payload.decode("utf-8", errors="replace")

    def _sec_websocket_key(self, request: str) -> str:
        for line in request.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                return line.split(":", 1)[1].strip()
        raise RuntimeError("websocket key header is missing")

    def _recv_text(self) -> str:
        header = self._read_exact(2)
        first, second = header[0], header[1]
        payload_length = second & 0x7F
        if payload_length == 126:
            payload_length = int.from_bytes(self._read_exact(2), "big")
        elif payload_length == 127:
            payload_length = int.from_bytes(self._read_exact(8), "big")
        mask_key = self._read_exact(4)
        payload = self._read_exact(payload_length) if payload_length else b""
        unmasked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        opcode = first & 0x0F
        _assert(opcode == 0x1, f"expected text frame opcode, got {opcode}")
        return unmasked.decode("utf-8")

    def _send_text(self, payload: str) -> None:
        encoded = payload.encode("utf-8")
        header = bytes([0x81])
        payload_length = len(encoded)
        if payload_length < 126:
            header += bytes([payload_length])
        elif payload_length <= 0xFFFF:
            header += bytes([126]) + payload_length.to_bytes(2, "big")
        else:
            header += bytes([127]) + payload_length.to_bytes(8, "big")
        self.request.sendall(header + encoded)

    def _read_exact(self, size: int) -> bytes:
        payload = bytearray()
        while len(payload) < size:
            chunk = self.request.recv(size - len(payload))
            if not chunk:
                raise RuntimeError("unexpected websocket eof")
            payload.extend(chunk)
        return bytes(payload)


class _ThreadingWebSocketServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class _ServerContext:
    def __init__(self, callback) -> None:
        handler = type(
            "ConfiguredWebSocketHandler",
            (_SingleShotWebSocketHandler,),
            {"callback": staticmethod(callback)},
        )
        self._server = _ThreadingWebSocketServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"ws://{host}:{port}"

    def __enter__(self) -> _ServerContext:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def _build_connector(*, upbit_ws_url: str, coinone_ws_url: str) -> PublicWebSocketMarketDataConnector:
    return PublicWebSocketMarketDataConnector(
        timeout_ms=1000,
        stale_threshold_ms=3000,
        orderbook_depth_levels=2,
        retry_count=0,
        retry_backoff=ExponentialBackoffPolicy(initial_delay_ms=100, max_delay_ms=100),
        rate_limit_policies=None,
        upbit_base_url="https://api.upbit.com",
        bithumb_base_url="https://api.bithumb.com",
        coinone_base_url="https://api.coinone.co.kr",
        upbit_ws_url=upbit_ws_url,
        coinone_ws_url=coinone_ws_url,
    )


def _case_upbit_snapshot() -> None:
    def callback(payload: object) -> list[dict[str, object]]:
        _assert(isinstance(payload, list), f"upbit request must be list: {payload}")
        type_fields = [item for item in payload if isinstance(item, dict) and item.get("type") == "orderbook"]
        _assert(type_fields, f"upbit type field missing: {payload}")
        request = type_fields[0]
        _assert(request.get("is_only_snapshot") is True, f"upbit snapshot flag missing: {payload}")
        _assert(request.get("codes") == ["KRW-BTC.5"], f"upbit market depth request mismatch: {payload}")
        return [
            {
                "type": "orderbook",
                "code": "KRW-BTC",
                "timestamp": 1746601573804,
                "orderbook_units": [
                    {"ask_price": 101, "bid_price": 100, "ask_size": 1.5, "bid_size": 2.5},
                    {"ask_price": 102, "bid_price": 99, "ask_size": 1.0, "bid_size": 2.0},
                ],
            }
        ]

    with _ServerContext(callback) as upbit_server:
        connector = _build_connector(upbit_ws_url=upbit_server.url, coinone_ws_url="ws://127.0.0.1:9")
        snapshot = connector.get_orderbook_top(exchange="upbit", market="KRW-BTC")
    _assert(snapshot["exchange"] == "upbit", f"upbit exchange mismatch: {snapshot}")
    _assert(snapshot["best_bid"] == "100", f"upbit best bid mismatch: {snapshot}")
    _assert(snapshot["best_ask"] == "101", f"upbit best ask mismatch: {snapshot}")
    _assert(snapshot["source_type"] == "public_ws", f"upbit source_type mismatch: {snapshot}")


def _case_coinone_snapshot() -> None:
    def callback(payload: object) -> list[dict[str, object]]:
        _assert(isinstance(payload, dict), f"coinone request must be object: {payload}")
        _assert(payload.get("request_type") == "SUBSCRIBE", f"coinone request type mismatch: {payload}")
        _assert(payload.get("channel") == "ORDERBOOK", f"coinone channel mismatch: {payload}")
        topic = payload.get("topic")
        _assert(topic == {"quote_currency": "KRW", "target_currency": "BTC"}, f"coinone topic mismatch: {payload}")
        return [
            {"response_type": "CONNECTED", "data": {"session_id": "test-session"}},
            {"response_type": "SUBSCRIBED", "channel": "ORDERBOOK", "data": topic},
            {
                "response_type": "DATA",
                "channel": "ORDERBOOK",
                "data": {
                    "quote_currency": "KRW",
                    "target_currency": "BTC",
                    "timestamp": 1746601573804,
                    "asks": [
                        {"price": "101", "qty": "1.5"},
                        {"price": "102", "qty": "1.0"},
                    ],
                    "bids": [
                        {"price": "100", "qty": "2.5"},
                        {"price": "99", "qty": "2.0"},
                    ],
                },
            },
        ]

    with _ServerContext(callback) as coinone_server:
        connector = _build_connector(upbit_ws_url="ws://127.0.0.1:9", coinone_ws_url=coinone_server.url)
        snapshot = connector.get_orderbook_top(exchange="coinone", market="KRW-BTC")
    _assert(snapshot["exchange"] == "coinone", f"coinone exchange mismatch: {snapshot}")
    _assert(snapshot["best_bid"] == "100", f"coinone best bid mismatch: {snapshot}")
    _assert(snapshot["best_ask"] == "101", f"coinone best ask mismatch: {snapshot}")
    _assert(snapshot["source_type"] == "public_ws", f"coinone source_type mismatch: {snapshot}")


def _case_unsupported_exchange() -> None:
    connector = _build_connector(upbit_ws_url="ws://127.0.0.1:9", coinone_ws_url="ws://127.0.0.1:9")
    try:
        connector.get_orderbook_top(exchange="bithumb", market="KRW-BTC")
    except MarketDataError as exc:
        _assert(exc.code == "EXCHANGE_NOT_SUPPORTED", f"unsupported exchange code mismatch: {exc}")
        return
    raise AssertionError("unsupported websocket exchange should fail")


def main() -> None:
    _case_upbit_snapshot()
    _case_coinone_snapshot()
    _case_unsupported_exchange()
    print("PASS public websocket connector parses upbit orderbook snapshots")
    print("PASS public websocket connector parses coinone orderbook snapshots")
    print("PASS public websocket connector rejects unsupported exchanges")


if __name__ == "__main__":
    main()
