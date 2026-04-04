from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from urllib import error, request

from ..request_utils import (
    is_nonnegative_number_text,
    is_positive_number_text,
    json_datetime_text,
    json_number_text,
)
from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_execution import ArbitrageSubmitResult
from .arbitrage_models import ArbitrageDecision
from .arbitrage_state_machine import classify_submit_failure_transition


ALLOWED_ORDER_STATUSES = {
    "new",
    "submitted",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "expired",
    "failed",
}
TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected", "expired", "failed"}
ALLOWED_LIFECYCLE_PREVIEWS_BY_OUTCOME = {
    "submitted": {"entry_submitting", "entry_open"},
    "filled": {"hedge_balanced", "closed"},
}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _failure_result(
    *,
    auto_unwind_on_failure: bool,
    reason: str,
    details: dict[str, object] | None = None,
    created_orders: tuple[dict[str, object], ...] = (),
    created_fills: tuple[dict[str, object], ...] = (),
) -> ArbitrageSubmitResult:
    transition = classify_submit_failure_transition(
        decision_accepted=True,
        reservation_passed=True,
        submit_failed=True,
        auto_unwind_allowed=auto_unwind_on_failure,
    )
    payload = {"mode": "private_http", "reason": reason}
    if isinstance(details, dict):
        details_to_merge = dict(details)
        detail_reason = _json_text(details_to_merge.get("reason"))
        if detail_reason is not None and detail_reason != reason:
            details_to_merge["remote_reason"] = detail_reason
            details_to_merge.pop("reason", None)
        payload.update(details_to_merge)
    return ArbitrageSubmitResult(
        outcome="submit_failed",
        lifecycle_preview=str(transition["next_state"]),
        recovery_required=bool(transition["recovery_required"]),
        unwind_in_progress=bool(transition["unwind_in_progress"]),
        created_orders=created_orders,
        created_fills=created_fills,
        details=payload,
    )


def _json_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _response_details(payload: dict[str, object]) -> dict[str, object]:
    details = payload.get("details")
    if isinstance(details, dict):
        return dict(details)
    return {}


def _build_request_payload(
    *,
    decision: ArbitrageDecision,
    intent: dict[str, object],
    auto_unwind_on_failure: bool,
) -> dict[str, object]:
    return {
        "intent_id": intent.get("intent_id"),
        "bot_id": intent.get("bot_id"),
        "strategy_run_id": intent.get("strategy_run_id"),
        "market": intent.get("market"),
        "buy_exchange": intent.get("buy_exchange"),
        "sell_exchange": intent.get("sell_exchange"),
        "side_pair": intent.get("side_pair"),
        "target_qty": intent.get("target_qty"),
        "expected_profit": intent.get("expected_profit"),
        "expected_profit_ratio": intent.get("expected_profit_ratio"),
        "decision": {
            "accepted": decision.accepted,
            "reason_code": decision.reason_code,
            "decision_context": decision.decision_context,
            "reservation_passed": (
                decision.reservation_plan.reservation_passed
                if decision.reservation_plan is not None
                else None
            ),
            "executable_profit_quote": (
                str(decision.executable_edge.executable_profit_quote)
                if decision.executable_edge is not None
                else None
            ),
            "executable_profit_bps": (
                str(decision.executable_edge.executable_profit_bps)
                if decision.executable_edge is not None
                else None
            ),
        },
        "auto_unwind_on_failure": auto_unwind_on_failure,
    }


def _post_json(
    *,
    url: str,
    token: str | None,
    timeout_ms: int,
    payload: dict[str, object],
) -> tuple[dict[str, object] | None, str | None]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=max(timeout_ms, 250) / 1000.0) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8").strip()
        except Exception:
            detail = ""
        reason = f"private execution http {exc.code}"
        if detail:
            reason = f"{reason}: {detail[:200]}"
        return None, reason
    except error.URLError as exc:
        return None, f"private execution transport failed: {exc.reason}"
    except TimeoutError:
        return None, "private execution request timed out"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "private execution response was not valid JSON"
    if not isinstance(parsed, dict):
        return None, "private execution response must be a JSON object"
    return parsed, None


def _create_orders_from_response(
    *,
    store: ControlPlaneStoreProtocol,
    intent: dict[str, object],
    orders_payload: object,
) -> tuple[tuple[dict[str, object], ...], dict[tuple[str, str], dict[str, object]], str | None]:
    if not isinstance(orders_payload, list) or not orders_payload:
        return (), {}, "private execution response missing orders"

    validated_items: list[dict[str, object]] = []
    expected_market = str(intent.get("market") or "")
    expected_legs = {
        ("buy", str(intent.get("buy_exchange") or "")),
        ("sell", str(intent.get("sell_exchange") or "")),
    }
    seen_order_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(orders_payload, start=1):
        if not isinstance(item, dict):
            return (), {}, "private execution order item must be an object"
        exchange_name = _json_text(item.get("exchange_name"))
        side = (_json_text(item.get("side")) or "").lower()
        market = _json_text(item.get("market")) or expected_market
        requested_qty = json_number_text(item.get("requested_qty")) or str(
            intent.get("target_qty") or ""
        )
        requested_price = json_number_text(item.get("requested_price"))
        exchange_order_id = _json_text(item.get("exchange_order_id"))
        status = (_json_text(item.get("status")) or "submitted").lower()
        if not exchange_name or side not in {"buy", "sell"} or not requested_qty:
            return (), {}, "private execution order item missing exchange_name, side, or requested_qty"
        if expected_market and market != expected_market:
            return (), {}, "private execution order market mismatches intent market"
        if (side, exchange_name) not in expected_legs:
            return (), {}, (
                "private execution response returned unexpected arbitrage order legs: "
                f"{side}:{exchange_name}"
            )
        if not is_positive_number_text(requested_qty):
            return (), {}, "private execution order requested_qty must be a positive number"
        if requested_price is not None and not is_positive_number_text(requested_price):
            return (), {}, "private execution order requested_price must be a positive number"
        if status not in ALLOWED_ORDER_STATUSES:
            return (), {}, f"private execution order status not allowed: {status}"
        order_key = (side, exchange_name)
        if order_key in seen_order_keys:
            return (), {}, "private execution response duplicated arbitrage order leg"
        seen_order_keys.add(order_key)
        raw_payload = item.get("raw_payload")
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        validated_items.append(
            {
                "exchange_name": exchange_name,
                "side": side,
                "market": market,
                "requested_qty": requested_qty,
                "requested_price": requested_price,
                "exchange_order_id": exchange_order_id,
                "status": status,
                "raw_payload": {
                    **raw_payload,
                    "submission_mode": "private_http",
                    "adapter_response_order_index": index,
                },
            }
        )

    created_orders: list[dict[str, object]] = []
    order_index: dict[tuple[str, str], dict[str, object]] = {}
    for item in validated_items:
        outcome, order = store.create_order(
            order_intent_id=str(intent["intent_id"]),
            exchange_name=str(item["exchange_name"]),
            exchange_order_id=_json_text(item["exchange_order_id"]),
            market=str(item["market"]),
            side=str(item["side"]),
            requested_price=_json_text(item["requested_price"]),
            requested_qty=str(item["requested_qty"]),
            status=str(item["status"]),
            raw_payload=item["raw_payload"] if isinstance(item["raw_payload"], dict) else {},
        )
        if outcome != "created" or order is None:
            return (
                tuple(created_orders),
                order_index,
                f"private execution order create failed: {outcome}",
            )
        created_orders.append(order)
        order_index[(str(item["side"]), str(item["exchange_name"]))] = order
    return tuple(created_orders), order_index, None


def _refresh_orders(
    *,
    store: ControlPlaneStoreProtocol,
    created_orders: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    refreshed_orders: list[dict[str, object]] = []
    for order in created_orders:
        order_id = _json_text(order.get("order_id"))
        latest = store.get_order_detail(order_id) if order_id else None
        refreshed_orders.append(latest if latest is not None else order)
    return tuple(refreshed_orders)


def _validate_required_arbitrage_legs(
    *,
    created_orders: tuple[dict[str, object], ...],
    order_index: dict[tuple[str, str], dict[str, object]],
    intent: dict[str, object],
    require_complete: bool = True,
) -> str | None:
    expected_legs = {
        ("buy", str(intent.get("buy_exchange") or "")),
        ("sell", str(intent.get("sell_exchange") or "")),
    }
    if "" in {exchange_name for _, exchange_name in expected_legs}:
        return "private execution response missing arbitrage exchange context"
    missing_legs = [
        f"{side}:{exchange_name}"
        for side, exchange_name in sorted(expected_legs)
        if (side, exchange_name) not in order_index
    ]
    if require_complete and missing_legs:
        return (
            "private execution response missing required arbitrage order legs: "
            + ", ".join(missing_legs)
        )
    unexpected_legs = [
        f"{side}:{exchange_name}"
        for side, exchange_name in sorted(order_index)
        if (side, exchange_name) not in expected_legs
    ]
    if unexpected_legs:
        return (
            "private execution response returned unexpected arbitrage order legs: "
            + ", ".join(unexpected_legs)
        )
    if len(created_orders) != len(expected_legs):
        return "private execution response returned unexpected arbitrage order count"
    return None


def _validate_filled_order_states(
    *,
    created_orders: tuple[dict[str, object], ...],
) -> str | None:
    non_filled_orders = [
        f"{order.get('order_id')}:{order.get('status')}"
        for order in created_orders
        if str(order.get("status") or "").strip().lower() != "filled"
    ]
    if non_filled_orders:
        return (
            "private execution filled outcome left orders non-terminal: "
            + ", ".join(non_filled_orders)
        )
    return None


def _validate_filled_leg_coverage(
    *,
    created_fills: tuple[dict[str, object], ...],
    intent: dict[str, object],
) -> str | None:
    expected_legs = {
        ("buy", str(intent.get("buy_exchange") or "")),
        ("sell", str(intent.get("sell_exchange") or "")),
    }
    if "" in {exchange_name for _, exchange_name in expected_legs}:
        return "private execution response missing arbitrage exchange context"
    observed_legs = {
        (
            str(fill.get("side") or "").strip().lower(),
            str(fill.get("exchange_name") or "").strip(),
        )
        for fill in created_fills
    }
    missing_legs = [
        f"{side}:{exchange_name}"
        for side, exchange_name in sorted(expected_legs)
        if (side, exchange_name) not in observed_legs
    ]
    if missing_legs:
        return (
            "private execution filled outcome missing required fill legs: "
            + ", ".join(missing_legs)
        )
    return None


def _validate_response_fill_leg_coverage(
    *,
    fills_payload: object,
    intent: dict[str, object],
) -> str | None:
    if not isinstance(fills_payload, list):
        return None
    expected_legs = {
        ("buy", str(intent.get("buy_exchange") or "")),
        ("sell", str(intent.get("sell_exchange") or "")),
    }
    if "" in {exchange_name for _, exchange_name in expected_legs}:
        return "private execution response missing arbitrage exchange context"
    observed_legs: set[tuple[str, str]] = set()
    for item in fills_payload:
        if not isinstance(item, dict):
            continue
        side = (_json_text(item.get("side")) or "").lower()
        exchange_name = _json_text(item.get("exchange_name")) or ""
        if side in {"buy", "sell"} and exchange_name:
            observed_legs.add((side, exchange_name))
    missing_legs = [
        f"{side}:{exchange_name}"
        for side, exchange_name in sorted(expected_legs)
        if (side, exchange_name) not in observed_legs
    ]
    if missing_legs:
        return (
            "private execution filled outcome missing required fill legs: "
            + ", ".join(missing_legs)
        )
    return None


def _validate_submitted_order_states(
    *,
    created_orders: tuple[dict[str, object], ...],
    created_fills: tuple[dict[str, object], ...],
) -> str | None:
    if created_fills:
        return "private execution submitted outcome must not include fills"
    terminal_orders = [
        f"{order.get('order_id')}:{order.get('status')}"
        for order in created_orders
        if str(order.get("status") or "").strip().lower() in TERMINAL_ORDER_STATUSES
    ]
    if terminal_orders:
        return (
            "private execution submitted outcome returned terminal orders: "
            + ", ".join(terminal_orders)
        )
    return None


def _validate_lifecycle_preview(
    *,
    outcome: str,
    lifecycle_preview: str | None,
) -> str | None:
    if not lifecycle_preview:
        return None
    allowed = ALLOWED_LIFECYCLE_PREVIEWS_BY_OUTCOME.get(outcome)
    if allowed is None:
        return None
    if lifecycle_preview not in allowed:
        return (
            "private execution lifecycle_preview is inconsistent with outcome: "
            f"{outcome}:{lifecycle_preview}"
        )
    return None


def _match_order_for_fill(
    *,
    order_index: dict[tuple[str, str], dict[str, object]],
    side: str,
    exchange_name: str | None,
) -> dict[str, object] | None:
    if exchange_name:
        return order_index.get((side, exchange_name))
    matches = [order for (order_side, _), order in order_index.items() if order_side == side]
    if len(matches) == 1:
        return matches[0]
    return None


def _create_fills_from_response(
    *,
    store: ControlPlaneStoreProtocol,
    order_index: dict[tuple[str, str], dict[str, object]],
    fills_payload: object,
) -> tuple[tuple[dict[str, object], ...], str | None]:
    if fills_payload is None:
        return (), None
    if not isinstance(fills_payload, list):
        return (), "private execution fills must be a list"

    created_fills: list[dict[str, object]] = []
    for item in fills_payload:
        if not isinstance(item, dict):
            return tuple(created_fills), "private execution fill item must be an object"
        side = (_json_text(item.get("side")) or "").lower()
        exchange_name = _json_text(item.get("exchange_name"))
        order = _match_order_for_fill(
            order_index=order_index,
            side=side,
            exchange_name=exchange_name,
        )
        if order is None:
            return tuple(created_fills), "private execution fill could not be matched to order"
        fill_price = json_number_text(item.get("fill_price"))
        fill_qty = json_number_text(item.get("fill_qty"))
        if not fill_price or not fill_qty:
            return tuple(created_fills), "private execution fill missing fill_price or fill_qty"
        if not is_positive_number_text(fill_price):
            return tuple(created_fills), "private execution fill_price must be a positive number"
        if not is_positive_number_text(fill_qty):
            return tuple(created_fills), "private execution fill_qty must be a positive number"
        fee_amount = json_number_text(item.get("fee_amount")) or "0"
        if not is_nonnegative_number_text(fee_amount):
            return tuple(created_fills), "private execution fee_amount must be nonnegative"
        filled_at = json_datetime_text(item.get("filled_at")) or _iso_now()
        outcome, fill = store.create_fill(
            order_id=str(order["order_id"]),
            exchange_trade_id=_json_text(item.get("exchange_trade_id")),
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee_asset=_json_text(item.get("fee_asset")),
            fee_amount=fee_amount,
            filled_at=filled_at,
        )
        if outcome != "created" or fill is None:
            return tuple(created_fills), f"private execution fill create failed: {outcome}"
        created_fills.append(fill)
    return tuple(created_fills), None


@dataclass(frozen=True)
class PrivateHttpArbitrageExecutionAdapter:
    url: str | None
    timeout_ms: int = 3000
    token: str | None = None

    @property
    def name(self) -> str:
        return "private_http"

    def submit(
        self,
        *,
        store: ControlPlaneStoreProtocol,
        decision: ArbitrageDecision,
        intent: dict[str, object],
        auto_unwind_on_failure: bool,
    ) -> ArbitrageSubmitResult:
        if not self.url:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason="private execution url not configured",
            )
        response_payload, error_message = _post_json(
            url=self.url,
            token=self.token,
            timeout_ms=self.timeout_ms,
            payload=_build_request_payload(
                decision=decision,
                intent=intent,
                auto_unwind_on_failure=auto_unwind_on_failure,
            ),
        )
        if response_payload is None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=error_message or "private execution request failed",
            )

        outcome = (_json_text(response_payload.get("outcome")) or "submitted").lower()
        if outcome not in {"submitted", "filled", "submit_failed"}:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=f"private execution returned unsupported outcome: {outcome}",
                details=_response_details(response_payload),
            )

        if outcome == "submit_failed":
            orders_payload = response_payload.get("orders")
            fills_payload = response_payload.get("fills")
            if isinstance(orders_payload, list) and orders_payload:
                created_orders, order_index, order_error = _create_orders_from_response(
                    store=store,
                    intent=intent,
                    orders_payload=orders_payload,
                )
                if order_error is not None:
                    return _failure_result(
                        auto_unwind_on_failure=auto_unwind_on_failure,
                        reason=order_error,
                        details=_response_details(response_payload),
                        created_orders=created_orders,
                    )
                leg_error = _validate_required_arbitrage_legs(
                    created_orders=created_orders,
                    order_index=order_index,
                    intent=intent,
                    require_complete=False,
                )
                if leg_error is not None:
                    return _failure_result(
                        auto_unwind_on_failure=auto_unwind_on_failure,
                        reason=leg_error,
                        details=_response_details(response_payload),
                        created_orders=created_orders,
                    )
                created_fills, fill_error = _create_fills_from_response(
                    store=store,
                    order_index=order_index,
                    fills_payload=fills_payload,
                )
                refreshed_orders = _refresh_orders(
                    store=store,
                    created_orders=created_orders,
                )
                if fill_error is not None:
                    return _failure_result(
                        auto_unwind_on_failure=auto_unwind_on_failure,
                        reason=fill_error,
                        details=_response_details(response_payload),
                        created_orders=refreshed_orders,
                        created_fills=created_fills,
                    )
            else:
                if fills_payload is not None:
                    return _failure_result(
                        auto_unwind_on_failure=auto_unwind_on_failure,
                        reason=(
                            "private execution submit_failed outcome must not include "
                            "fills without orders"
                        ),
                        details=_response_details(response_payload),
                    )
                created_orders = ()
                created_fills = ()
                refreshed_orders = ()
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=(
                    _json_text(_response_details(response_payload).get("reason"))
                    or "private execution submit failed"
                ),
                details=_response_details(response_payload),
                created_orders=refreshed_orders,
                created_fills=created_fills,
            )
        created_orders, order_index, order_error = _create_orders_from_response(
            store=store,
            intent=intent,
            orders_payload=response_payload.get("orders"),
        )
        if order_error is not None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=order_error,
                details=_response_details(response_payload),
                created_orders=created_orders,
            )
        leg_error = _validate_required_arbitrage_legs(
            created_orders=created_orders,
            order_index=order_index,
            intent=intent,
        )
        if leg_error is not None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=leg_error,
                details=_response_details(response_payload),
                created_orders=created_orders,
            )
        if outcome == "filled":
            fill_leg_payload_error = _validate_response_fill_leg_coverage(
                fills_payload=response_payload.get("fills"),
                intent=intent,
            )
            if fill_leg_payload_error is not None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=fill_leg_payload_error,
                    details=_response_details(response_payload),
                    created_orders=created_orders,
                )
        created_fills, fill_error = _create_fills_from_response(
            store=store,
            order_index=order_index,
            fills_payload=response_payload.get("fills"),
        )
        refreshed_orders = _refresh_orders(
            store=store,
            created_orders=created_orders,
        )
        if fill_error is not None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=fill_error,
                details=_response_details(response_payload),
                created_orders=refreshed_orders,
                created_fills=created_fills,
            )
        if outcome == "filled" and not created_fills:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason="private execution filled outcome missing fills",
                details=_response_details(response_payload),
                created_orders=refreshed_orders,
            )
        if outcome == "submitted":
            submitted_state_error = _validate_submitted_order_states(
                created_orders=refreshed_orders,
                created_fills=created_fills,
            )
            if submitted_state_error is not None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=submitted_state_error,
                    details=_response_details(response_payload),
                    created_orders=refreshed_orders,
                    created_fills=created_fills,
                )
        if outcome == "filled":
            filled_state_error = _validate_filled_order_states(created_orders=refreshed_orders)
            if filled_state_error is not None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=filled_state_error,
                    details=_response_details(response_payload),
                    created_orders=refreshed_orders,
                    created_fills=created_fills,
                )
            filled_leg_error = _validate_filled_leg_coverage(
                created_fills=created_fills,
                intent=intent,
            )
            if filled_leg_error is not None:
                return _failure_result(
                    auto_unwind_on_failure=auto_unwind_on_failure,
                    reason=filled_leg_error,
                    details=_response_details(response_payload),
                    created_orders=refreshed_orders,
                    created_fills=created_fills,
                )
        lifecycle_preview = _json_text(response_payload.get("lifecycle_preview"))
        lifecycle_error = _validate_lifecycle_preview(
            outcome=outcome,
            lifecycle_preview=lifecycle_preview,
        )
        if lifecycle_error is not None:
            return _failure_result(
                auto_unwind_on_failure=auto_unwind_on_failure,
                reason=lifecycle_error,
                details=_response_details(response_payload),
                created_orders=refreshed_orders,
                created_fills=created_fills,
            )
        if not lifecycle_preview:
            lifecycle_preview = "hedge_balanced" if outcome == "filled" else "entry_submitting"
        details = {"mode": "private_http", **_response_details(response_payload)}
        return ArbitrageSubmitResult(
            outcome=outcome,
            lifecycle_preview=lifecycle_preview,
            recovery_required=False,
            unwind_in_progress=False,
            created_orders=refreshed_orders,
            created_fills=created_fills,
            details=details,
        )
