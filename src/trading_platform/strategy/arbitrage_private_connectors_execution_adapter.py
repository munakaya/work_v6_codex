from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_execution import ArbitrageSubmitResult
from .arbitrage_models import ArbitrageDecision
from .arbitrage_private_execution_adapter import (
    TERMINAL_ORDER_STATUSES,
    _create_orders_from_response,
    _failure_result,
    _json_text,
    _refresh_orders,
    _validate_submitted_order_states,
)

if TYPE_CHECKING:
    from ..private_exchange_connector import PrivateExchangeConnectorProtocol, PrivateExchangeResult


MODE_NAME = "private_connectors"


@dataclass(frozen=True)
class PrivateConnectorsArbitrageExecutionAdapter:
    connectors: dict[str, "PrivateExchangeConnectorProtocol"]

    @property
    def name(self) -> str:
        return MODE_NAME

    def submit(
        self,
        *,
        store: ControlPlaneStoreProtocol,
        decision: ArbitrageDecision,
        intent: dict[str, object],
        auto_unwind_on_failure: bool,
    ) -> ArbitrageSubmitResult:
        if decision.executable_edge is None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason="private connector execution requires executable edge",
                details={"reason": "missing executable edge"},
                mode=MODE_NAME,
            )

        created_orders: list[dict[str, object]] = []
        for side, exchange_name, requested_price in (
            (
                "buy",
                str(intent.get("buy_exchange") or "").strip(),
                str(decision.executable_edge.buy_vwap),
            ),
            (
                "sell",
                str(intent.get("sell_exchange") or "").strip(),
                str(decision.executable_edge.sell_vwap),
            ),
        ):
            connector = self.connectors.get(exchange_name)
            if connector is None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=f"private connector not configured for: {exchange_name or side}",
                    details={"failed_leg": side, "exchange_name": exchange_name},
                    created_orders=tuple(created_orders),
                    mode=MODE_NAME,
                )
            response = connector.place_order(
                self._request_payload(
                    intent=intent,
                    side=side,
                    requested_price=requested_price,
                )
            )
            order_item, response_error = self._order_item_from_response(
                response=response,
                intent=intent,
                side=side,
                exchange_name=exchange_name,
                requested_price=requested_price,
                connector_name=connector.name,
            )
            if order_item is None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=response_error or "private connector place_order failed",
                    details=self._response_details(
                        response=response,
                        failed_leg=side,
                        exchange_name=exchange_name,
                        connector_name=connector.name,
                    ),
                    created_orders=tuple(created_orders),
                    mode=MODE_NAME,
                )
            created_batch, _order_index, order_error = _create_orders_from_response(
                store=store,
                intent=intent,
                orders_payload=[order_item],
                submission_mode=MODE_NAME,
            )
            if order_error is not None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=order_error,
                    details={
                        **self._response_details(
                            response=response,
                            failed_leg=side,
                            exchange_name=exchange_name,
                            connector_name=connector.name,
                        ),
                        "order_payload": order_item,
                    },
                    created_orders=tuple(created_orders),
                    mode=MODE_NAME,
                )
            created_orders.extend(created_batch)

        refreshed_orders = _refresh_orders(
            store=store,
            created_orders=tuple(created_orders),
        )
        submitted_state_error = _validate_submitted_order_states(
            created_orders=refreshed_orders,
            created_fills=(),
        )
        if submitted_state_error is not None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=submitted_state_error,
                details={"submitted_leg_count": len(refreshed_orders)},
                created_orders=refreshed_orders,
                mode=MODE_NAME,
            )
        return ArbitrageSubmitResult(
            outcome="submitted",
            lifecycle_preview="entry_submitting",
            recovery_required=False,
            unwind_in_progress=False,
            created_orders=refreshed_orders,
            details={
                "mode": MODE_NAME,
                "submitted_leg_count": len(refreshed_orders),
            },
        )

    def _request_payload(
        self,
        *,
        intent: dict[str, object],
        side: str,
        requested_price: str,
    ) -> dict[str, object]:
        market = str(intent.get("market") or "")
        target_qty = str(intent.get("target_qty") or "")
        intent_id = str(intent.get("intent_id") or "").strip()
        buy_exchange = str(intent.get("buy_exchange") or "").strip()
        sell_exchange = str(intent.get("sell_exchange") or "").strip()
        client_order_id = ":".join(
            part
            for part in (
                intent_id or None,
                side,
                buy_exchange if side == "buy" else sell_exchange,
            )
            if part
        )
        payload = {
            "market": market,
            "side": side,
            "order_type": "limit",
            "price": requested_price,
            "qty": target_qty,
        }
        if client_order_id:
            payload["client_order_id"] = client_order_id
        return payload

    def _order_item_from_response(
        self,
        *,
        response: "PrivateExchangeResult",
        intent: dict[str, object],
        side: str,
        exchange_name: str,
        requested_price: str,
        connector_name: str,
    ) -> tuple[dict[str, object] | None, str | None]:
        if response.outcome != "ok":
            error_code = _json_text(response.error_code or response.outcome) or "unknown"
            reason = _json_text(response.reason) or "private connector request failed"
            return None, f"{exchange_name} place_order failed: {error_code}: {reason}"
        payload = response.data if isinstance(response.data, dict) else None
        if payload is None:
            return None, f"{exchange_name} place_order returned invalid payload"
        status = (_json_text(payload.get("status")) or "submitted").strip().lower()
        if status in TERMINAL_ORDER_STATUSES:
            return None, f"{exchange_name} place_order returned terminal order status: {status}"
        exchange_order_id = _json_text(payload.get("exchange_order_id"))
        if exchange_order_id is None:
            return None, f"{exchange_name} place_order returned missing exchange_order_id"
        order_item = {
            "exchange_name": exchange_name,
            "side": side,
            "market": str(intent.get("market") or ""),
            "requested_qty": _json_text(payload.get("requested_qty"))
            or str(intent.get("target_qty") or ""),
            "requested_price": _json_text(payload.get("requested_price")) or requested_price,
            "exchange_order_id": exchange_order_id,
            "status": status,
            "raw_payload": {
                "connector_name": connector_name,
                "connector_outcome": response.outcome,
                "connector_order": payload,
            },
        }
        return order_item, None

    def _response_details(
        self,
        *,
        response: "PrivateExchangeResult",
        failed_leg: str,
        exchange_name: str,
        connector_name: str,
    ) -> dict[str, object]:
        return {
            "failed_leg": failed_leg,
            "exchange_name": exchange_name,
            "connector_name": connector_name,
            "connector_outcome": response.outcome,
            "connector_error_code": response.error_code,
            "connector_reason": response.reason,
            "connector_retryable": response.retryable,
            "connector_http_status": response.http_status,
        }
