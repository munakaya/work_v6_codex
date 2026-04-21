from __future__ import annotations

from http import HTTPStatus
import os
from uuid import uuid4

from trading_platform.private_exchange_connector import PrivateExchangeResult
from trading_platform.redis_runtime import RedisRuntime
from trading_platform.request_utils import response_payload
from trading_platform.route_handlers_recovery_write import ControlPlaneRecoveryWriteRouteMixin
from trading_platform.storage.store_factory import sample_read_store



class _FakeRecoveryRuntime:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.run_once_calls = 0

    def run_once(self) -> None:
        self.run_once_calls += 1


class _FakeCancelConnector:
    def __init__(
        self,
        *,
        exchange: str,
        status_by_exchange_order_id: dict[str, str] | None = None,
    ) -> None:
        self.exchange = exchange
        self.status_by_exchange_order_id = dict(status_by_exchange_order_id or {})
        self.cancel_calls: list[tuple[str, str]] = []

    def get_balances(self) -> PrivateExchangeResult:
        return PrivateExchangeResult(outcome="ok", data={"items": [], "count": 0})

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        raise AssertionError("place_order should not be called")

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        raise AssertionError("get_order_status should not be called")

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        self.cancel_calls.append((exchange_order_id, market))
        return PrivateExchangeResult(
            outcome="ok",
            data={
                "exchange_order_id": exchange_order_id,
                "market": market,
                "status": self.status_by_exchange_order_id.get(exchange_order_id, "cancelled"),
            },
        )

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        raise AssertionError("list_open_orders should not be called")


class _DummyServer:
    def __init__(
        self,
        redis_runtime: RedisRuntime,
        private_exchange_connectors: dict[str, _FakeCancelConnector] | None = None,
    ) -> None:
        self.read_store = sample_read_store()
        self.redis_runtime = redis_runtime
        self.private_exchange_connectors = private_exchange_connectors or {
            "upbit": _FakeCancelConnector(exchange="upbit"),
            "bithumb": _FakeCancelConnector(exchange="bithumb"),
        }
        self.recovery_runtime = _FakeRecoveryRuntime(enabled=True)


class _DummyHandler(ControlPlaneRecoveryWriteRouteMixin):
    def __init__(self, server: _DummyServer, body: dict[str, object] | None = None) -> None:
        self.server = server
        self._body = dict(body or {})
        self.headers = {}
        if body is not None:
            self.headers["Content-Length"] = "1"

    def _response(
        self,
        data: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return response_payload(
            request_id_factory=lambda: str(uuid4()),
            data=data,
            error=error,
        )

    def _read_json_body(self):
        return dict(self._body), None

    def _ensure_mutation_supported(self):
        if self.server.read_store.supports_mutation:
            return None
        return (
            HTTPStatus.NOT_IMPLEMENTED,
            self._response(
                error={
                    "code": "STORE_MUTATION_UNAVAILABLE",
                    "message": "write operations are disabled",
                }
            ),
        )

    def _publish_order_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.server.redis_runtime.publish_order_event(event_type=event_type, payload=payload)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _seed_cancel_trace(server: _DummyServer) -> tuple[str, list[str], list[dict[str, object]]]:
    run = server.read_store.list_strategy_runs()[0]
    run_id = str(run["run_id"])
    bot_id = str(run["bot_id"])

    intent_outcome, intent = server.read_store.create_order_intent(
        strategy_run_id=run_id,
        market="BTC/KRW",
        buy_exchange="upbit",
        sell_exchange="bithumb",
        side_pair="buy_upbit_sell_bithumb",
        target_qty="0.02",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "recovery_cancel_case"},
    )
    _assert(intent_outcome == "created" and intent is not None, "failed to create primary intent")

    primary_order_ids: list[str] = []
    created_orders: list[dict[str, object]] = []
    for exchange_name, side in (("upbit", "buy"), ("bithumb", "sell")):
        order_outcome, order = server.read_store.create_order(
            order_intent_id=str(intent["intent_id"]),
            exchange_name=exchange_name,
            exchange_order_id=f"{exchange_name}-entry-{uuid4().hex[:8]}",
            market="BTC/KRW",
            side=side,
            requested_price="100000000",
            requested_qty="0.02",
            status="new",
            raw_payload={"source": "entry"},
        )
        _assert(order_outcome == "created" and order is not None, f"failed to create {exchange_name} entry order")
        primary_order_ids.append(str(order["order_id"]))
        created_orders.append(order)

    unwind_outcome, unwind_intent = server.read_store.create_order_intent(
        strategy_run_id=run_id,
        market="BTC/KRW",
        buy_exchange="upbit",
        sell_exchange="bithumb",
        side_pair="sell_upbit_buy_bithumb",
        target_qty="0.02",
        expected_profit=None,
        expected_profit_ratio=None,
        status="submitted",
        decision_context={"source": "recovery_cancel_case", "kind": "unwind"},
    )
    _assert(
        unwind_outcome == "created" and unwind_intent is not None,
        "failed to create unwind intent",
    )
    unwind_order_outcome, unwind_order = server.read_store.create_order(
        order_intent_id=str(unwind_intent["intent_id"]),
        exchange_name="upbit",
        exchange_order_id=f"upbit-unwind-{uuid4().hex[:8]}",
        market="BTC/KRW",
        side="sell",
        requested_price="100100000",
        requested_qty="0.02",
        status="new",
        raw_payload={"source": "unwind"},
    )
    _assert(
        unwind_order_outcome == "created" and unwind_order is not None,
        "failed to create unwind order",
    )
    created_orders.append(unwind_order)

    recovery_trace_id = f"rt_{uuid4().hex[:12]}"
    server.redis_runtime.sync_recovery_trace(
        recovery_trace_id=recovery_trace_id,
        payload={
            "recovery_trace_id": recovery_trace_id,
            "run_id": run_id,
            "bot_id": bot_id,
            "intent_id": str(intent["intent_id"]),
            "status": "active",
            "lifecycle_state": "unwind_in_progress",
            "linked_unwind_action_id": str(unwind_intent["intent_id"]),
            "linked_unwind_order_id": str(unwind_order["order_id"]),
            "residual_exposure_quote": "1000",
        },
    )
    return recovery_trace_id, primary_order_ids + [str(unwind_order["order_id"])], created_orders


def main() -> None:
    redis_url = os.getenv("TP_REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_runtime = RedisRuntime(
        redis_url,
        f"tp_recovery_cancel_case_{uuid4().hex[:8]}",
        "recovery-cancel-flow-case",
    )
    if not redis_runtime.info.enabled:
        raise SystemExit("redis runtime is not enabled for recovery cancel flow cases")

    server = _DummyServer(redis_runtime)
    handler = _DummyHandler(
        server,
        body={"verified_by": "operator-a", "summary": "cancel open orders"},
    )
    recovery_trace_id, expected_order_ids, _created_orders = _seed_cancel_trace(server)

    status, payload = handler._cancel_open_orders_response(recovery_trace_id)
    _assert(status == HTTPStatus.OK, f"cancel-open-orders status mismatch: {status} {payload}")
    data = payload["data"]
    _assert(data is not None, "cancel-open-orders payload missing data")
    cancel_results = data["cancel_results"]
    _assert(len(cancel_results) == 3, f"cancel result count mismatch: {cancel_results}")
    _assert(
        {item["order_id"] for item in cancel_results} == set(expected_order_ids),
        f"cancel result order ids mismatch: {cancel_results}",
    )
    _assert(
        all(item["result"] == "cancelled" for item in cancel_results),
        f"cancel result kind mismatch: {cancel_results}",
    )
    _assert(
        set(data["cancelled_order_ids"]) == set(expected_order_ids),
        f"trace cancelled ids mismatch: {data}",
    )
    _assert(data["cancel_remaining_open_order_ids"] == [], f"remaining open orders mismatch: {data}")
    _assert(server.recovery_runtime.run_once_calls == 1, "recovery runtime should run once")
    for order_id in expected_order_ids:
        detail = server.read_store.get_order_detail(order_id)
        _assert(detail is not None, f"missing order detail: {order_id}")
        _assert(detail["status"] == "cancelled", f"local order status mismatch: {detail}")
    upbit_calls = server.private_exchange_connectors["upbit"].cancel_calls
    bithumb_calls = server.private_exchange_connectors["bithumb"].cancel_calls
    _assert(len(upbit_calls) == 2, f"upbit cancel call count mismatch: {upbit_calls}")
    _assert(len(bithumb_calls) == 1, f"bithumb cancel call count mismatch: {bithumb_calls}")

    second_status, second_payload = handler._cancel_open_orders_response(recovery_trace_id)
    _assert(
        second_status == HTTPStatus.CONFLICT,
        f"second cancel-open-orders should conflict: {second_status} {second_payload}",
    )
    _assert(
        second_payload["error"]["code"] == "RECOVERY_TRACE_OPEN_ORDER_MISSING",
        f"second cancel error mismatch: {second_payload}",
    )

    partial_connectors = {
        "upbit": _FakeCancelConnector(exchange="upbit"),
        "bithumb": _FakeCancelConnector(exchange="bithumb"),
    }
    partial_server = _DummyServer(redis_runtime, private_exchange_connectors=partial_connectors)
    partial_handler = _DummyHandler(partial_server)
    partial_trace_id, _partial_order_ids, partial_orders = _seed_cancel_trace(partial_server)
    partial_upbit_order = next(
        order for order in partial_orders if str(order.get("exchange_name")) == "upbit"
    )
    partial_upbit_exchange_order_id = str(partial_upbit_order["exchange_order_id"])
    partial_connectors["upbit"].status_by_exchange_order_id[partial_upbit_exchange_order_id] = "filled"

    partial_status, partial_payload = partial_handler._cancel_open_orders_response(partial_trace_id)
    _assert(
        partial_status == HTTPStatus.OK,
        f"partial cancel-open-orders status mismatch: {partial_status} {partial_payload}",
    )
    partial_data = partial_payload["data"]
    _assert(partial_data is not None, "partial cancel payload missing data")
    failed_item = next(
        item for item in partial_data["cancel_results"] if item["order_id"] == str(partial_upbit_order["order_id"])
    )
    _assert(
        failed_item["error_code"] == "CANCEL_REQUIRES_RECONCILIATION",
        f"partial cancel failure code mismatch: {failed_item}",
    )
    unchanged_order = partial_server.read_store.get_order_detail(str(partial_upbit_order["order_id"]))
    _assert(unchanged_order is not None, "unchanged order detail missing")
    _assert(
        unchanged_order["status"] == "new",
        f"filled cancel response should not mutate local order: {unchanged_order}",
    )
    _assert(
        str(partial_upbit_order["order_id"]) in partial_data["cancel_remaining_open_order_ids"],
        f"reconciliation-required order should remain open locally: {partial_data}",
    )
    print("PASS recovery cancel flow cases")


if __name__ == "__main__":
    main()
