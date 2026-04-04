from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class OrderbookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderbookSnapshot:
    exchange_name: str
    market: str
    observed_at: datetime
    asks: tuple[OrderbookLevel, ...]
    bids: tuple[OrderbookLevel, ...]
    connector_healthy: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))


@dataclass(frozen=True)
class BalanceSnapshot:
    exchange_name: str
    base_asset: str
    quote_asset: str
    available_base: Decimal
    available_quote: Decimal
    observed_at: datetime
    is_fresh: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))


@dataclass(frozen=True)
class RiskConfig:
    min_profit_quote: Decimal
    min_profit_bps: Decimal
    max_clock_skew_ms: int
    max_orderbook_age_ms: int
    max_balance_age_ms: int
    max_notional_per_order: Decimal
    max_total_notional_per_bot: Decimal
    max_spread_bps: Decimal
    slippage_buffer_bps: Decimal = Decimal("0")
    unwind_buffer_quote: Decimal = Decimal("0")
    rebalance_buffer_quote: Decimal = Decimal("0")
    taker_fee_bps_buy: Decimal = Decimal("0")
    taker_fee_bps_sell: Decimal = Decimal("0")
    reentry_cooldown_seconds: int = 0


@dataclass(frozen=True)
class RuntimeState:
    now: datetime
    open_order_count: int = 0
    open_order_cap: int = 0
    unwind_in_progress: bool = False
    connector_private_healthy: bool = True
    duplicate_intent_active: bool = False
    recent_unwind_at: datetime | None = None
    remaining_bot_notional: Decimal | None = None
    bot_id: str | None = None
    strategy_run_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", _ensure_utc(self.now))
        if self.recent_unwind_at is not None:
            object.__setattr__(self, "recent_unwind_at", _ensure_utc(self.recent_unwind_at))


@dataclass(frozen=True)
class ArbitrageInputs:
    bot_id: str
    strategy_run_id: str
    canonical_symbol: str
    market: str
    base_exchange: str
    hedge_exchange: str
    base_orderbook: OrderbookSnapshot
    hedge_orderbook: OrderbookSnapshot
    base_balance: BalanceSnapshot
    hedge_balance: BalanceSnapshot
    risk_config: RiskConfig
    runtime_state: RuntimeState


@dataclass(frozen=True)
class GateCheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CandidateSizeResult:
    target_qty: Decimal
    components: dict[str, str]


@dataclass(frozen=True)
class ExecutableEdgeResult:
    executable_buy_cost_quote: Decimal
    executable_sell_proceeds_quote: Decimal
    gross_profit_quote: Decimal
    executable_profit_quote: Decimal
    executable_profit_bps: Decimal
    buy_vwap: Decimal
    sell_vwap: Decimal
    fee_buy_quote: Decimal
    fee_sell_quote: Decimal
    buy_slippage_buffer_quote: Decimal
    sell_slippage_buffer_quote: Decimal
    unwind_buffer_quote: Decimal
    rebalance_buffer_quote: Decimal
    total_fee_quote: Decimal
    total_cost_adjustment_quote: Decimal
    passed: bool


@dataclass(frozen=True)
class ReservationPlan:
    reservation_passed: bool
    reason_code: str | None
    quote_required: Decimal
    base_required: Decimal
    reserved_notional: Decimal
    details: dict[str, str]


@dataclass(frozen=True)
class OrderIntentPlan:
    market: str
    buy_exchange: str
    sell_exchange: str
    side_pair: str
    target_qty: str
    expected_profit: str
    expected_profit_ratio: str
    decision_context: dict[str, object]


@dataclass(frozen=True)
class ArbitrageDecision:
    accepted: bool
    reason_code: str
    gate_checks: tuple[GateCheckResult, ...] = field(default_factory=tuple)
    candidate_size: CandidateSizeResult | None = None
    executable_edge: ExecutableEdgeResult | None = None
    reservation_plan: ReservationPlan | None = None
    order_intent_plan: OrderIntentPlan | None = None
    decision_context: dict[str, object] = field(default_factory=dict)
