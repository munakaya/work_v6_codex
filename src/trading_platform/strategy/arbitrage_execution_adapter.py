from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..storage.store_protocol import ControlPlaneStoreProtocol
from .arbitrage_execution import ArbitrageSubmitResult, submit_arbitrage_orders
from .arbitrage_models import ArbitrageDecision


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


def build_arbitrage_execution_adapter(mode: str) -> ArbitrageExecutionAdapterProtocol:
    normalized = mode.strip().lower() or "simulate_success"
    return SimulatedArbitrageExecutionAdapter(mode=normalized)
