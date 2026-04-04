from __future__ import annotations

from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from trading_platform.storage.store_factory import sample_read_store
from trading_platform.strategy import (
    build_arbitrage_execution_adapter,
    evaluate_arbitrage,
    load_strategy_inputs,
    persist_order_intent_plan,
)
from trading_platform.strategy.arbitrage_runtime_loader import load_arbitrage_runtime_payload


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DummyConnector:
    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        now = _iso_now()
        prices = {
            ("sample", "KRW-BTC"): ("99900", "100000"),
            ("upbit", "KRW-BTC"): ("100500", "100550"),
        }
        best_bid, best_ask = prices[(exchange, market)]
        return {
            "exchange": exchange,
            "market": market,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_volume": "5",
            "ask_volume": "5",
            "exchange_timestamp": now,
            "received_at": now,
            "exchange_age_ms": 0,
            "stale": False,
            "source_type": "dummy",
        }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fresh_store(bot_key: str) -> tuple[object, str, str]:
    store = sample_read_store()
    latest_default = store.config_versions["default"][0]["config_json"]["arbitrage_runtime"]
    latest_default["hedge_balance"]["available_base"] = "5.0"
    latest_default["base_balance"]["available_quote"] = "150000000"
    for run in store.strategy_runs.values():
        run["status"] = "stopped"
        run["stopped_at"] = "2026-04-04T07:00:00Z"
    registered = store.register_bot(
        bot_key=bot_key,
        strategy_name="arbitrage",
        mode="shadow",
        hostname="private-http-adapter-case",
    )
    outcome, run = store.create_strategy_run(
        bot_id=str(registered["bot_id"]),
        strategy_name="arbitrage",
        mode="shadow",
    )
    _assert(outcome == "created", outcome)
    outcome, run = store.start_strategy_run(str(run["run_id"]))
    _assert(outcome == "started", outcome)
    return store, str(registered["bot_id"]), str(run["run_id"])


def _load_decision_and_intent(store: object, run_id: str) -> tuple[object, dict[str, object]]:
    run = store.get_strategy_run(run_id)
    _assert(run is not None, "strategy run not found")
    load_result = load_arbitrage_runtime_payload(
        store=store,
        connector=DummyConnector(),
        run=run,
    )
    _assert(load_result.payload is not None, f"load failed: {load_result.skip_reason}")
    decision = evaluate_arbitrage(load_strategy_inputs(load_result.payload))
    _assert(decision.accepted, "decision should be accepted")
    outcome, intent = persist_order_intent_plan(
        store=store,
        decision=decision,
        strategy_run_id=run_id,
    )
    _assert(outcome == "created" and intent is not None, "intent persist failed")
    return decision, intent


def _build_response(path: str, body: dict[str, object]) -> dict[str, object]:
    market = str(body.get("market") or "")
    target_qty = str(body.get("target_qty") or "0.2")
    buy_exchange = str(body.get("buy_exchange") or "")
    sell_exchange = str(body.get("sell_exchange") or "")
    if path == "/submitted-with-fill":
        return {
            "outcome": "submitted",
            "orders": [
                {
                    "exchange_name": buy_exchange,
                    "exchange_order_id": "submitted-buy-001",
                    "market": market,
                    "side": "buy",
                    "requested_qty": target_qty,
                    "status": "submitted",
                },
                {
                    "exchange_name": sell_exchange,
                    "exchange_order_id": "submitted-sell-001",
                    "market": market,
                    "side": "sell",
                    "requested_qty": target_qty,
                    "status": "submitted",
                },
            ],
            "fills": [
                {
                    "exchange_name": buy_exchange,
                    "side": "buy",
                    "exchange_trade_id": "submitted-fill-buy-001",
                    "fill_price": "100000",
                    "fill_qty": target_qty,
                    "filled_at": _iso_now(),
                }
            ],
            "details": {"remote_mode": "submitted-with-fill"},
        }
    return {
        "outcome": "submitted",
        "orders": [
            {
                "exchange_name": buy_exchange,
                "exchange_order_id": "submitted-buy-001",
                "market": market,
                "side": "buy",
                "requested_qty": target_qty,
                "status": "submitted",
            },
            {
                "exchange_name": sell_exchange,
                "exchange_order_id": "submitted-sell-001",
                "market": market,
                "side": "sell",
                "requested_qty": target_qty,
                "status": "submitted",
            },
        ],
        "details": {"remote_mode": "submitted"},
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size).decode("utf-8"))
        payload = _build_response(self.path, body)
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _with_server(fn) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fn(server)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def main() -> None:
    def _run(server: ThreadingHTTPServer) -> None:
        base_url = f"http://127.0.0.1:{server.server_port}"

        store, _bot_id, run_id = _fresh_store("private-http-adapter-existing-order-conflict")
        decision, intent = _load_decision_and_intent(store, run_id)
        seed_outcome, seed_run = store.create_strategy_run(
            bot_id=next(iter(store.bot_details)),
            strategy_name="arbitrage",
            mode="shadow",
        )
        _assert(seed_outcome == "created", "seed strategy run create failed")
        seed_intent_outcome, seed_intent = store.create_order_intent(
            strategy_run_id=str(seed_run["run_id"]),
            market="KRW-BTC",
            buy_exchange="sample",
            sell_exchange="upbit",
            side_pair="buy_then_sell",
            target_qty="0.01",
            expected_profit=None,
            expected_profit_ratio=None,
            status="created",
            decision_context={"seed": "existing-order-conflict"},
        )
        _assert(seed_intent_outcome == "created" and seed_intent is not None, "seed intent create failed")
        seed_order_outcome, _seed_order = store.create_order(
            order_intent_id=str(seed_intent["intent_id"]),
            exchange_name="sample",
            exchange_order_id="submitted-buy-001",
            market="KRW-BTC",
            side="buy",
            requested_price=None,
            requested_qty="0.01",
            status="submitted",
            raw_payload={"seed": "existing-order-conflict"},
        )
        _assert(seed_order_outcome == "created", "seed order create failed")
        adapter = build_arbitrage_execution_adapter(
            mode="private_http",
            private_execution_url=f"{base_url}/submitted",
            private_execution_timeout_ms=3000,
        )
        submit_result = adapter.submit(
            store=store,
            decision=decision,
            intent=intent,
            auto_unwind_on_failure=False,
        )
        _assert(submit_result.outcome == "submit_failed", "existing-order-conflict should fail")
        _assert(
            str(submit_result.details.get("reason"))
            == "private execution exchange_order_id conflicts with existing order",
            "existing-order-conflict reason mismatch",
        )
        _assert(
            len(store.list_orders(strategy_run_id=run_id)) == 0,
            "existing-order-conflict should not persist target run orders",
        )

        store, _bot_id, run_id = _fresh_store("private-http-adapter-submitted-with-fill")
        decision, intent = _load_decision_and_intent(store, run_id)
        adapter = build_arbitrage_execution_adapter(
            mode="private_http",
            private_execution_url=f"{base_url}/submitted-with-fill",
            private_execution_timeout_ms=3000,
        )
        submit_result = adapter.submit(
            store=store,
            decision=decision,
            intent=intent,
            auto_unwind_on_failure=False,
        )
        _assert(submit_result.outcome == "submit_failed", "submitted-with-fill should fail")
        _assert(
            str(submit_result.details.get("reason"))
            == "private execution submitted outcome must not include fills",
            "submitted-with-fill reason mismatch",
        )
        _assert(
            len(store.list_orders(strategy_run_id=run_id)) == 0,
            "submitted-with-fill should not persist orders",
        )
        _assert(
            len(store.list_fills(strategy_run_id=run_id)) == 0,
            "submitted-with-fill should not persist fills",
        )

        print("PASS private_http adapter case existing_order_conflict")
        print("PASS private_http adapter case submitted_with_fill_no_persist")

    _with_server(_run)


if __name__ == "__main__":
    main()
