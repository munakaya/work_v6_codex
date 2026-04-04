from __future__ import annotations

from decimal import Decimal

from .arbitrage_models import (
    ArbitrageInputs,
    CandidateSizeResult,
    ExecutableEdgeResult,
    ReservationPlan,
)


def reserve_capacity(
    inputs: ArbitrageInputs,
    candidate_size: CandidateSizeResult,
    executable_edge: ExecutableEdgeResult,
) -> ReservationPlan:
    quote_required = executable_edge.executable_buy_cost_quote
    base_required = candidate_size.target_qty
    reserved_notional = executable_edge.executable_buy_cost_quote

    failures: list[str] = []
    if quote_required > inputs.base_balance.available_quote:
        failures.append("buy_quote_insufficient")
    if base_required > inputs.hedge_balance.available_base:
        failures.append("sell_base_insufficient")

    return ReservationPlan(
        reservation_passed=not failures,
        reason_code=None if not failures else "RESERVATION_FAILED",
        quote_required=quote_required,
        base_required=base_required,
        reserved_notional=reserved_notional,
        details={
            "buy_quote_available": str(inputs.base_balance.available_quote),
            "sell_base_available": str(inputs.hedge_balance.available_base),
            "failures": ",".join(failures) if failures else "",
        },
    )
