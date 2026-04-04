from __future__ import annotations


STATE_PRIORITY = (
    "manual_handoff",
    "unwind_in_progress",
    "recovery_required",
    "entry_open",
    "entry_submitting",
    "hedge_balanced",
    "intent_created",
    "decision_accepted",
    "decision_rejected",
    "closed",
)


def derive_arbitrage_lifecycle_state(
    *,
    decision_accepted: bool,
    has_order_intents: bool,
    has_submitted_orders: bool,
    has_open_orders: bool,
    hedge_balanced: bool,
    recovery_required: bool,
    unwind_in_progress: bool,
    manual_handoff: bool,
) -> str:
    active_states: list[str] = []
    if manual_handoff:
        active_states.append("manual_handoff")
    if unwind_in_progress:
        active_states.append("unwind_in_progress")
    if recovery_required:
        active_states.append("recovery_required")
    if has_open_orders:
        active_states.append("entry_open")
    if has_submitted_orders:
        active_states.append("entry_submitting")
    if hedge_balanced:
        active_states.append("hedge_balanced")
    if has_order_intents:
        active_states.append("intent_created")
    if decision_accepted:
        active_states.append("decision_accepted")
    if not decision_accepted and not active_states:
        active_states.append("decision_rejected")
    if not active_states:
        active_states.append("closed")

    for state in STATE_PRIORITY:
        if state in active_states:
            return state
    return "closed"


def classify_submit_failure_transition(
    *,
    decision_accepted: bool,
    reservation_passed: bool,
    submit_failed: bool,
    auto_unwind_allowed: bool,
    has_partial_fill: bool = False,
) -> dict[str, object]:
    if not decision_accepted:
        return {
            "decision_outcome": "decision_rejected",
            "next_state": "decision_rejected",
            "recovery_required": False,
            "unwind_in_progress": False,
        }
    if not reservation_passed:
        return {
            "decision_outcome": "invalid_accept_without_reservation",
            "next_state": "recovery_required",
            "recovery_required": True,
            "unwind_in_progress": False,
        }
    if not submit_failed:
        next_state = "entry_open" if has_partial_fill else "entry_submitting"
        return {
            "decision_outcome": "accepted",
            "next_state": next_state,
            "recovery_required": False,
            "unwind_in_progress": False,
        }

    next_state = "unwind_in_progress" if auto_unwind_allowed else "recovery_required"
    return {
        "decision_outcome": "accepted",
        "next_state": next_state,
        "recovery_required": True,
        "unwind_in_progress": auto_unwind_allowed,
    }
