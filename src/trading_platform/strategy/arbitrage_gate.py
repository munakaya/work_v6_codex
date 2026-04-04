from __future__ import annotations

from datetime import datetime

from .arbitrage_models import ArbitrageInputs, GateCheckResult


def _age_ms(now: datetime, observed_at: datetime) -> int:
    return max(0, int((now - observed_at).total_seconds() * 1000))


def validate_gate_conditions(inputs: ArbitrageInputs) -> tuple[list[GateCheckResult], str | None]:
    checks: list[GateCheckResult] = []
    now = inputs.runtime_state.now
    config = inputs.risk_config
    state = inputs.runtime_state

    public_connectors_ok = (
        inputs.base_orderbook.connector_healthy and inputs.hedge_orderbook.connector_healthy
    )
    checks.append(
        GateCheckResult(
            name="connector_health",
            passed=public_connectors_ok and state.connector_private_healthy,
            detail=(
                "all connectors healthy"
                if public_connectors_ok and state.connector_private_healthy
                else "public/private connector degraded"
            ),
        )
    )

    base_orderbook_age_ms = _age_ms(now, inputs.base_orderbook.observed_at)
    hedge_orderbook_age_ms = _age_ms(now, inputs.hedge_orderbook.observed_at)
    orderbook_fresh = (
        base_orderbook_age_ms <= config.max_orderbook_age_ms
        and hedge_orderbook_age_ms <= config.max_orderbook_age_ms
    )
    checks.append(
        GateCheckResult(
            name="orderbook_freshness",
            passed=orderbook_fresh,
            detail=(
                f"ages={base_orderbook_age_ms}/{hedge_orderbook_age_ms}ms"
                if orderbook_fresh
                else f"stale ages={base_orderbook_age_ms}/{hedge_orderbook_age_ms}ms"
            ),
        )
    )

    base_balance_age_ms = _age_ms(now, inputs.base_balance.observed_at)
    hedge_balance_age_ms = _age_ms(now, inputs.hedge_balance.observed_at)
    balance_fresh = (
        inputs.base_balance.is_fresh
        and inputs.hedge_balance.is_fresh
        and base_balance_age_ms <= config.max_balance_age_ms
        and hedge_balance_age_ms <= config.max_balance_age_ms
    )
    checks.append(
        GateCheckResult(
            name="balance_freshness",
            passed=balance_fresh,
            detail=(
                f"ages={base_balance_age_ms}/{hedge_balance_age_ms}ms"
                if balance_fresh
                else f"stale ages={base_balance_age_ms}/{hedge_balance_age_ms}ms"
            ),
        )
    )

    skew_ms = abs(int((inputs.base_orderbook.observed_at - inputs.hedge_orderbook.observed_at).total_seconds() * 1000))
    checks.append(
        GateCheckResult(
            name="quote_pair_lock",
            passed=skew_ms <= config.max_clock_skew_ms,
            detail=f"skew_ms={skew_ms}",
        )
    )

    checks.append(
        GateCheckResult(
            name="unwind_block",
            passed=not state.unwind_in_progress,
            detail="unwind not active" if not state.unwind_in_progress else "recovery required",
        )
    )

    open_order_ok = state.open_order_cap <= 0 or state.open_order_count < state.open_order_cap
    checks.append(
        GateCheckResult(
            name="open_order_cap",
            passed=open_order_ok,
            detail=f"{state.open_order_count}/{state.open_order_cap}",
        )
    )

    checks.append(
        GateCheckResult(
            name="duplicate_intent",
            passed=not state.duplicate_intent_active,
            detail=(
                "no active duplicate intent"
                if not state.duplicate_intent_active
                else "same symbol intent already active"
            ),
        )
    )

    cooldown_ok = True
    if state.recent_unwind_at is not None and config.reentry_cooldown_seconds > 0:
        elapsed = int((state.now - state.recent_unwind_at).total_seconds())
        cooldown_ok = elapsed >= config.reentry_cooldown_seconds
    checks.append(
        GateCheckResult(
            name="reentry_cooldown",
            passed=cooldown_ok,
            detail="cooldown ok" if cooldown_ok else "cooldown active",
        )
    )

    for check in checks:
        if check.passed:
            continue
        if check.name == "orderbook_freshness":
            return checks, "ORDERBOOK_STALE"
        if check.name == "balance_freshness":
            return checks, "BALANCE_STALE"
        if check.name == "quote_pair_lock":
            return checks, "QUOTE_PAIR_SKEW_TOO_HIGH"
        if check.name == "reentry_cooldown":
            return checks, "REENTRY_COOLDOWN_ACTIVE"
        if check.name == "duplicate_intent":
            return checks, "DUPLICATE_INTENT_BLOCKED"
        if check.name == "connector_health":
            return checks, "HEDGE_CONFIDENCE_TOO_LOW"
        return checks, "RISK_LIMIT_BLOCKED"
    return checks, None
