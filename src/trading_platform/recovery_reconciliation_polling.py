from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .private_exchange_connector import PrivateExchangeConnectorProtocol


TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected", "expired", "failed"}


@dataclass(frozen=True)
class AutoReconciliationSnapshot:
    patch: dict[str, object]


def build_auto_reconciliation_snapshot(
    *,
    trace: dict[str, object],
    related_orders: list[dict[str, object]],
    related_fills: list[dict[str, object]],
    private_exchange_connectors: dict[str, "PrivateExchangeConnectorProtocol"],
) -> AutoReconciliationSnapshot | None:
    if not related_orders or not private_exchange_connectors:
        return None
    market = next(
        (
            str(order.get("market") or "").strip().upper()
            for order in related_orders
            if str(order.get("market") or "").strip()
        ),
        "",
    )
    relevant_assets = _relevant_assets_from_market(market)
    relevant_exchanges = {
        str(order.get("exchange_name") or "").strip()
        for order in related_orders
        if str(order.get("exchange_name") or "").strip()
    }
    if not relevant_exchanges:
        return None

    observed_order_ids: list[str] = []
    observed_order_statuses: list[dict[str, str]] = []
    observed_fill_ids = [
        str(fill.get("fill_id") or "").strip()
        for fill in related_fills
        if str(fill.get("fill_id") or "").strip()
    ]
    open_order_count = 0
    net_base_qty = Decimal("0")
    reference_price: Decimal | None = None
    status_query_count = 0

    for order in related_orders:
        exchange_name = str(order.get("exchange_name") or "").strip()
        exchange_order_id = str(order.get("exchange_order_id") or "").strip()
        local_order_id = str(order.get("order_id") or "").strip()
        order_market = str(order.get("market") or market).strip().upper()
        connector = private_exchange_connectors.get(exchange_name)
        if connector is None or not exchange_order_id or not local_order_id or not order_market:
            continue
        response = connector.get_order_status(
            exchange_order_id=exchange_order_id,
            market=order_market,
        )
        payload = response.data if response.outcome == "ok" and isinstance(response.data, dict) else None
        if payload is None:
            continue
        normalized_status = str(payload.get("status") or "").strip().lower()
        if not normalized_status:
            continue
        status_query_count += 1
        observed_order_ids.append(local_order_id)
        observed_order_statuses.append({"order_id": local_order_id, "status": normalized_status})
        if normalized_status not in TERMINAL_ORDER_STATUSES:
            open_order_count += 1
        filled_qty = _parse_decimal(payload.get("filled_qty"))
        if filled_qty is None:
            filled_qty = _parse_decimal(order.get("filled_qty")) or Decimal("0")
        price = (
            _parse_decimal(payload.get("avg_fill_price"))
            or _parse_decimal(payload.get("requested_price"))
            or _parse_decimal(order.get("requested_price"))
        )
        if price is not None and price > 0:
            reference_price = price
        side = str(order.get("side") or payload.get("side") or "").strip().lower()
        if side == "buy":
            net_base_qty += filled_qty
        elif side == "sell":
            net_base_qty -= filled_qty

    if status_query_count == 0:
        return None

    observed_balances: list[dict[str, object]] = []
    balance_seen: set[tuple[str, str]] = set()
    for exchange_name in sorted(relevant_exchanges):
        connector = private_exchange_connectors.get(exchange_name)
        if connector is None:
            continue
        response = connector.get_balances()
        payload = response.data if response.outcome == "ok" and isinstance(response.data, dict) else None
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("currency") or item.get("asset") or "").strip().upper()
            if relevant_assets and asset not in relevant_assets:
                continue
            free = _parse_decimal(item.get("available") or item.get("free") or "0")
            locked = _parse_decimal(item.get("locked") or item.get("in_use") or item.get("limit") or "0")
            if free is None or locked is None or free < 0 or locked < 0:
                continue
            key = (exchange_name, asset)
            if key in balance_seen:
                continue
            balance_seen.add(key)
            observed_balances.append(
                {
                    "exchange_name": exchange_name,
                    "asset": asset,
                    "free": _decimal_text(free),
                    "locked": _decimal_text(locked),
                }
            )

    if net_base_qty == 0:
        residual_exposure_quote = Decimal("0")
    elif reference_price is not None:
        residual_exposure_quote = abs(net_base_qty) * reference_price
    else:
        fallback_residual = _parse_decimal(trace.get("residual_exposure_quote"))
        if fallback_residual is None:
            return None
        residual_exposure_quote = abs(fallback_residual)

    matched = open_order_count == 0 and residual_exposure_quote == Decimal("0")
    return AutoReconciliationSnapshot(
        patch={
            "reconciliation_result": "matched" if matched else "mismatch",
            "reconciliation_open_order_count": open_order_count,
            "reconciliation_residual_exposure_quote": _decimal_text(residual_exposure_quote),
            "reconciliation_observed_at": _iso_now(),
            "reconciliation_source": "auto_private_connectors",
            "reconciliation_summary": (
                "auto reconciliation from private exchange connectors"
            ),
            "reconciliation_reason": (
                "private_connectors_zero_residual"
                if matched
                else "private_connectors_residual_or_open_orders"
            ),
            "reconciliation_observed_order_ids": observed_order_ids,
            "reconciliation_observed_fill_ids": observed_fill_ids,
            "reconciliation_observed_order_statuses": observed_order_statuses,
            "reconciliation_observed_balances": observed_balances,
        }
    )


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal("1")), "f")
    return format(normalized, "f")


def _relevant_assets_from_market(market: str) -> set[str]:
    normalized = str(market or "").strip().upper()
    if not normalized:
        return set()
    for separator in ("-", "/"):
        parts = [part.strip() for part in normalized.split(separator) if part.strip()]
        if len(parts) == 2:
            return {parts[0], parts[1]}
    return set()
