from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_state_machine import classify_submit_failure_transition


@dataclass(frozen=True)
class ArbitrageSubmitResult:
    outcome: str
    lifecycle_preview: str
    recovery_required: bool
    unwind_in_progress: bool
    created_orders: tuple[dict[str, object], ...] = ()
    details: dict[str, object] = field(default_factory=dict)

    def as_payload(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "lifecycle_preview": self.lifecycle_preview,
            "recovery_required": self.recovery_required,
            "unwind_in_progress": self.unwind_in_progress,
            "created_orders": [
                {
                    "order_id": item.get("order_id"),
                    "exchange_name": item.get("exchange_name"),
                    "side": item.get("side"),
                    "status": item.get("status"),
                }
                for item in self.created_orders
            ],
            "details": self.details,
        }


def _submit_failure_result(
    *,
    auto_unwind_allowed: bool,
    details: dict[str, object] | None = None,
    created_orders: tuple[dict[str, object], ...] = (),
) -> ArbitrageSubmitResult:
    transition = classify_submit_failure_transition(
        decision_accepted=True,
        reservation_passed=True,
        submit_failed=True,
        auto_unwind_allowed=auto_unwind_allowed,
    )
    return ArbitrageSubmitResult(
        outcome="submit_failed",
        lifecycle_preview=str(transition["next_state"]),
        recovery_required=bool(transition["recovery_required"]),
        unwind_in_progress=bool(transition["unwind_in_progress"]),
        created_orders=created_orders,
        details=details or {},
    )


def _create_simulated_order(
    *,
    store: ControlPlaneStoreProtocol,
    intent: dict[str, object],
    exchange_name: str,
    side: str,
) -> tuple[str, dict[str, object] | None]:
    return store.create_order(
        order_intent_id=str(intent["intent_id"]),
        exchange_name=exchange_name,
        exchange_order_id=f"sim-{side}-{uuid4().hex[:10]}",
        market=str(intent["market"]),
        side=side,
        requested_price=None,
        requested_qty=str(intent["target_qty"]),
        status="new",
        raw_payload={
            "submission_mode": "simulated",
            "side": side,
            "intent_id": intent["intent_id"],
        },
    )


def submit_arbitrage_orders(
    *,
    store: ControlPlaneStoreProtocol,
    intent: dict[str, object],
    execution_mode: str,
    auto_unwind_on_failure: bool,
) -> ArbitrageSubmitResult:
    normalized_mode = execution_mode.strip().lower()
    if normalized_mode == "simulate_failure":
        return _submit_failure_result(
            auto_unwind_allowed=auto_unwind_on_failure,
            details={
                "mode": normalized_mode,
                "failed_leg": "pre_submit",
                "reason": "simulated submit failure",
            },
        )

    created_orders: list[dict[str, object]] = []
    for exchange_name, side in (
        (str(intent["buy_exchange"]), "buy"),
        (str(intent["sell_exchange"]), "sell"),
    ):
        outcome, order = _create_simulated_order(
            store=store,
            intent=intent,
            exchange_name=exchange_name,
            side=side,
        )
        if outcome != "created" or order is None:
            return _submit_failure_result(
                auto_unwind_allowed=auto_unwind_on_failure,
                details={
                    "mode": normalized_mode or "simulate_success",
                    "failed_leg": side,
                    "store_outcome": outcome,
                },
                created_orders=tuple(created_orders),
            )
        created_orders.append(order)

    return ArbitrageSubmitResult(
        outcome="submitted",
        lifecycle_preview="entry_submitting",
        recovery_required=False,
        unwind_in_progress=False,
        created_orders=tuple(created_orders),
        details={
            "mode": normalized_mode or "simulate_success",
            "submitted_leg_count": len(created_orders),
        },
    )
