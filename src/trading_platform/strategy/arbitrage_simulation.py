from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from .arbitrage_input_loader import load_strategy_inputs
from .arbitrage_runtime import evaluate_arbitrage


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def normalize_simulation_pairs(pairs: Sequence[str]) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        raw = pair.strip().lower()
        if not raw:
            continue
        left, separator, right = raw.partition(":")
        if separator != ":":
            raise ValueError(f"invalid pair format: {pair}")
        left = left.strip()
        right = right.strip()
        if not left or not right or left == right:
            raise ValueError(f"invalid pair format: {pair}")
        item = (left, right)
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one simulation pair is required")
    return tuple(normalized)


def normalize_exchange_intervals(
    *,
    exchanges: Sequence[str],
    overrides: Sequence[str],
    default_interval_seconds: float,
) -> dict[str, float]:
    normalized = {
        exchange.strip().lower(): max(default_interval_seconds, 0.1)
        for exchange in exchanges
        if exchange.strip()
    }
    for override in overrides:
        raw = override.strip().lower()
        if not raw:
            continue
        exchange, separator, value = raw.partition("=")
        if separator != "=" or not exchange.strip() or not value.strip():
            raise ValueError(f"invalid exchange interval format: {override}")
        try:
            interval_seconds = float(value)
        except ValueError as exc:
            raise ValueError(f"invalid exchange interval format: {override}") from exc
        normalized[exchange.strip()] = max(interval_seconds, 0.1)
    return normalized


class ExchangeFetchScheduler:
    def __init__(self, intervals: dict[str, float]) -> None:
        self.intervals = dict(intervals)
        self._last_attempt_at: dict[str, float] = {}

    def due_exchanges(
        self,
        *,
        exchanges: Sequence[str],
        now_monotonic: float,
    ) -> tuple[str, ...]:
        due: list[str] = []
        for exchange in exchanges:
            normalized = exchange.strip().lower()
            if not normalized:
                continue
            interval_seconds = max(self.intervals.get(normalized, 1.0), 0.1)
            last_attempt_at = self._last_attempt_at.get(normalized)
            if last_attempt_at is None or (now_monotonic - last_attempt_at) >= interval_seconds:
                due.append(normalized)
        return tuple(due)

    def mark_attempt(self, *, exchange: str, now_monotonic: float) -> None:
        self._last_attempt_at[exchange.strip().lower()] = now_monotonic


@dataclass(frozen=True)
class SimulationRiskSettings:
    min_profit_quote: Decimal = Decimal("0")
    min_profit_bps: Decimal = Decimal("0")
    max_clock_skew_ms: int = 1000
    max_orderbook_age_ms: int = 5000
    max_balance_age_ms: int = 60000
    max_notional_per_order: Decimal = Decimal("1000000000")
    max_total_notional_per_bot: Decimal = Decimal("1000000000")
    max_spread_bps: Decimal = Decimal("100000")
    min_orderbook_depth_levels: int = 1
    min_available_depth_quote: Decimal = Decimal("0")
    slippage_buffer_bps: Decimal = Decimal("0")
    unwind_buffer_quote: Decimal = Decimal("0")
    rebalance_buffer_quote: Decimal = Decimal("0")
    taker_fee_bps_buy: Decimal = Decimal("0")
    taker_fee_bps_sell: Decimal = Decimal("0")
    reentry_cooldown_seconds: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "min_profit_quote": _decimal_text(self.min_profit_quote),
            "min_profit_bps": _decimal_text(self.min_profit_bps),
            "max_clock_skew_ms": self.max_clock_skew_ms,
            "max_orderbook_age_ms": self.max_orderbook_age_ms,
            "max_balance_age_ms": self.max_balance_age_ms,
            "max_notional_per_order": _decimal_text(self.max_notional_per_order),
            "max_total_notional_per_bot": _decimal_text(
                self.max_total_notional_per_bot
            ),
            "max_spread_bps": _decimal_text(self.max_spread_bps),
            "min_orderbook_depth_levels": self.min_orderbook_depth_levels,
            "min_available_depth_quote": _decimal_text(
                self.min_available_depth_quote
            ),
            "slippage_buffer_bps": _decimal_text(self.slippage_buffer_bps),
            "unwind_buffer_quote": _decimal_text(self.unwind_buffer_quote),
            "rebalance_buffer_quote": _decimal_text(self.rebalance_buffer_quote),
            "taker_fee_bps_buy": _decimal_text(self.taker_fee_bps_buy),
            "taker_fee_bps_sell": _decimal_text(self.taker_fee_bps_sell),
            "reentry_cooldown_seconds": self.reentry_cooldown_seconds,
        }


@dataclass(frozen=True)
class SimulationBalanceSettings:
    available_quote: Decimal = Decimal("200000000")
    available_base: Decimal = Decimal("3")


@dataclass(frozen=True)
class SimulationObservation:
    market: str
    buy_exchange: str
    sell_exchange: str
    accepted: bool
    reason_code: str
    observed_at: str
    executable_profit_quote: Decimal | None
    executable_profit_bps: Decimal | None
    target_qty: Decimal | None

    @property
    def direction_key(self) -> str:
        return f"{self.buy_exchange}->{self.sell_exchange}"

    def as_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "direction": self.direction_key,
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "observed_at": self.observed_at,
            "executable_profit_quote": (
                _decimal_text(self.executable_profit_quote)
                if self.executable_profit_quote is not None
                else None
            ),
            "executable_profit_bps": (
                _decimal_text(self.executable_profit_bps)
                if self.executable_profit_bps is not None
                else None
            ),
            "target_qty": (
                _decimal_text(self.target_qty) if self.target_qty is not None else None
            ),
        }


@dataclass
class SimulationDirectionStats:
    market: str
    buy_exchange: str
    sell_exchange: str
    observed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    cumulative_profit_quote: Decimal = Decimal("0")
    best_profit_quote: Decimal | None = None
    best_profit_bps: Decimal | None = None
    latest_reason_code: str | None = None
    last_observed_at: str | None = None

    def record(self, observation: SimulationObservation) -> None:
        self.observed_count += 1
        self.last_observed_at = observation.observed_at
        self.latest_reason_code = observation.reason_code
        if observation.accepted:
            self.accepted_count += 1
            if observation.executable_profit_quote is not None:
                self.cumulative_profit_quote += observation.executable_profit_quote
                if (
                    self.best_profit_quote is None
                    or observation.executable_profit_quote > self.best_profit_quote
                ):
                    self.best_profit_quote = observation.executable_profit_quote
            if (
                observation.executable_profit_bps is not None
                and (
                    self.best_profit_bps is None
                    or observation.executable_profit_bps > self.best_profit_bps
                )
            ):
                self.best_profit_bps = observation.executable_profit_bps
        else:
            self.rejected_count += 1

    def as_dict(self, *, elapsed_seconds: float) -> dict[str, object]:
        accepted_rate = (
            float(self.accepted_count / self.observed_count)
            if self.observed_count > 0
            else 0.0
        )
        accepted_per_hour = (
            float(self.accepted_count * 3600 / elapsed_seconds)
            if elapsed_seconds > 0
            else 0.0
        )
        return {
            "market": self.market,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "direction": f"{self.buy_exchange}->{self.sell_exchange}",
            "observed_count": self.observed_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "accepted_rate": round(accepted_rate, 6),
            "accepted_per_hour": round(accepted_per_hour, 6),
            "cumulative_profit_quote": _decimal_text(self.cumulative_profit_quote),
            "best_profit_quote": (
                _decimal_text(self.best_profit_quote)
                if self.best_profit_quote is not None
                else None
            ),
            "best_profit_bps": (
                _decimal_text(self.best_profit_bps)
                if self.best_profit_bps is not None
                else None
            ),
            "latest_reason_code": self.latest_reason_code,
            "last_observed_at": self.last_observed_at,
        }


class SimulationStatsTracker:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self._stats: dict[str, SimulationDirectionStats] = {}

    def record(self, observation: SimulationObservation) -> None:
        key = observation.direction_key
        stats = self._stats.get(key)
        if stats is None:
            stats = SimulationDirectionStats(
                market=observation.market,
                buy_exchange=observation.buy_exchange,
                sell_exchange=observation.sell_exchange,
            )
            self._stats[key] = stats
        stats.record(observation)

    def snapshot(self) -> dict[str, object]:
        elapsed_seconds = max(
            0.0, (datetime.now(UTC) - self.started_at).total_seconds()
        )
        items = [
            stats.as_dict(elapsed_seconds=elapsed_seconds)
            for stats in sorted(
                self._stats.values(),
                key=lambda item: (item.buy_exchange, item.sell_exchange),
            )
        ]
        total_observed = sum(int(item["observed_count"]) for item in items)
        total_accepted = sum(int(item["accepted_count"]) for item in items)
        total_rejected = sum(int(item["rejected_count"]) for item in items)
        total_profit = sum(
            Decimal(str(item["cumulative_profit_quote"])) for item in items
        )
        return {
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "direction_count": len(items),
            "observed_count": total_observed,
            "accepted_count": total_accepted,
            "rejected_count": total_rejected,
            "accepted_rate": round(
                float(total_accepted / total_observed) if total_observed > 0 else 0.0,
                6,
            ),
            "accepted_per_hour": round(
                float(total_accepted * 3600 / elapsed_seconds)
                if elapsed_seconds > 0
                else 0.0,
                6,
            ),
            "cumulative_profit_quote": _decimal_text(total_profit),
            "items": items,
        }


def evaluate_directional_opportunities(
    *,
    market: str,
    canonical_symbol: str,
    first_snapshot: dict[str, object],
    second_snapshot: dict[str, object],
    first_exchange: str,
    second_exchange: str,
    base_asset: str,
    quote_asset: str,
    balances: SimulationBalanceSettings,
    risk: SimulationRiskSettings,
    now: datetime | None = None,
) -> tuple[SimulationObservation, SimulationObservation]:
    observed_at = _parse_iso_datetime(
        first_snapshot.get("exchange_timestamp") or first_snapshot.get("received_at"),
        fallback=_iso_now(),
    )
    current_time = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    buy_first_payload = {
        "bot_id": "sim-bot",
        "strategy_run_id": "sim-run",
        "canonical_symbol": canonical_symbol,
        "market": market,
        "base_exchange": first_exchange,
        "hedge_exchange": second_exchange,
        "base_orderbook": {
            "exchange_name": first_exchange,
            "market": market,
            "observed_at": _parse_iso_datetime(
                first_snapshot.get("exchange_timestamp")
                or first_snapshot.get("received_at"),
                fallback=observed_at,
            ),
            "asks": [
                {
                    "price": str(first_snapshot["best_ask"]),
                    "quantity": str(first_snapshot["ask_volume"]),
                }
            ],
            "bids": [
                {
                    "price": str(first_snapshot["best_bid"]),
                    "quantity": str(first_snapshot["bid_volume"]),
                }
            ],
            "connector_healthy": not bool(first_snapshot.get("stale")),
        },
        "hedge_orderbook": {
            "exchange_name": second_exchange,
            "market": market,
            "observed_at": _parse_iso_datetime(
                second_snapshot.get("exchange_timestamp")
                or second_snapshot.get("received_at"),
                fallback=observed_at,
            ),
            "asks": [
                {
                    "price": str(second_snapshot["best_ask"]),
                    "quantity": str(second_snapshot["ask_volume"]),
                }
            ],
            "bids": [
                {
                    "price": str(second_snapshot["best_bid"]),
                    "quantity": str(second_snapshot["bid_volume"]),
                }
            ],
            "connector_healthy": not bool(second_snapshot.get("stale")),
        },
        "base_balance": {
            "exchange_name": first_exchange,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "available_base": "0",
            "available_quote": _decimal_text(balances.available_quote),
            "observed_at": current_time,
            "is_fresh": True,
        },
        "hedge_balance": {
            "exchange_name": second_exchange,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "available_base": _decimal_text(balances.available_base),
            "available_quote": "0",
            "observed_at": current_time,
            "is_fresh": True,
        },
        "risk_config": risk.as_payload(),
        "runtime_state": {
            "now": current_time,
            "open_order_count": 0,
            "open_order_cap": 0,
            "unwind_in_progress": False,
            "connector_private_healthy": True,
            "duplicate_intent_active": False,
            "recent_unwind_at": None,
            "remaining_bot_notional": _decimal_text(risk.max_total_notional_per_bot),
        },
    }
    reverse_payload = {
        **buy_first_payload,
        "base_exchange": second_exchange,
        "hedge_exchange": first_exchange,
        "base_orderbook": buy_first_payload["hedge_orderbook"],
        "hedge_orderbook": buy_first_payload["base_orderbook"],
        "base_balance": {
            **dict(buy_first_payload["base_balance"]),
            "exchange_name": second_exchange,
        },
        "hedge_balance": {
            **dict(buy_first_payload["hedge_balance"]),
            "exchange_name": first_exchange,
        },
    }
    forward = _evaluate_payload(
        market=market,
        buy_exchange=first_exchange,
        sell_exchange=second_exchange,
        payload=buy_first_payload,
    )
    reverse = _evaluate_payload(
        market=market,
        buy_exchange=second_exchange,
        sell_exchange=first_exchange,
        payload=reverse_payload,
    )
    return forward, reverse


def _evaluate_payload(
    *,
    market: str,
    buy_exchange: str,
    sell_exchange: str,
    payload: dict[str, object],
) -> SimulationObservation:
    decision = evaluate_arbitrage(load_strategy_inputs(payload))
    edge = decision.executable_edge
    candidate = decision.candidate_size
    observed_at = str(
        dict(payload["base_orderbook"]).get("observed_at")  # type: ignore[arg-type]
        or _iso_now()
    )
    return SimulationObservation(
        market=market,
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        accepted=decision.accepted,
        reason_code=str(decision.reason_code),
        observed_at=observed_at,
        executable_profit_quote=(
            edge.executable_profit_quote if edge is not None else None
        ),
        executable_profit_bps=(edge.executable_profit_bps if edge is not None else None),
        target_qty=(candidate.target_qty if candidate is not None else None),
    )
