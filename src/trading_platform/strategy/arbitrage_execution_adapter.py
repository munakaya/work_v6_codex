from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_execution import ArbitrageSubmitResult, submit_arbitrage_orders
from .arbitrage_models import ArbitrageDecision
from .arbitrage_state_machine import classify_submit_failure_transition


class ArbitrageExecutionAdapterProtocol(Protocol):
    name: str

    def submit(
        self,
        *,
        store: ControlPlaneStoreProtocol,
        decision: ArbitrageDecision,
        intent: dict[str, object],
        auto_unwind_on_failure: bool,
    ) -> ArbitrageSubmitResult: ...


@dataclass(frozen=True)
class SimulatedArbitrageExecutionAdapter:
    mode: str

    @property
    def name(self) -> str:
        return f"simulated:{self.mode}"

    def submit(
        self,
        *,
        store: ControlPlaneStoreProtocol,
        decision: ArbitrageDecision,
        intent: dict[str, object],
        auto_unwind_on_failure: bool,
    ) -> ArbitrageSubmitResult:
        return submit_arbitrage_orders(
            store=store,
            decision=decision,
            intent=intent,
            execution_mode=self.mode,
            auto_unwind_on_failure=auto_unwind_on_failure,
        )


@dataclass(frozen=True)
class PrivateStubArbitrageExecutionAdapter:
    @property
    def name(self) -> str:
        return "private_stub"

    def submit(
        self,
        *,
        store: ControlPlaneStoreProtocol,
        decision: ArbitrageDecision,
        intent: dict[str, object],
        auto_unwind_on_failure: bool,
    ) -> ArbitrageSubmitResult:
        transition = classify_submit_failure_transition(
            decision_accepted=True,
            reservation_passed=True,
            submit_failed=True,
            auto_unwind_allowed=auto_unwind_on_failure,
        )
        return ArbitrageSubmitResult(
            outcome="submit_failed",
            lifecycle_preview=str(transition["next_state"]),
            recovery_required=bool(transition["recovery_required"]),
            unwind_in_progress=bool(transition["unwind_in_progress"]),
            details={
                "mode": "private_stub",
                "reason": "private execution adapter not implemented",
                "adapter_name": self.name,
            },
        )


def build_arbitrage_execution_adapter(mode: str) -> ArbitrageExecutionAdapterProtocol:
    normalized = mode.strip().lower() or "simulate_success"
    if normalized == "private_stub":
        return PrivateStubArbitrageExecutionAdapter()
    return SimulatedArbitrageExecutionAdapter(mode=normalized)
