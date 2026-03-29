from __future__ import annotations

from app.models import CallStatus, ItemStatus, Outcome, Phase, SessionState, utcnow


TERMINAL_PHASES = {
    Phase.completed,
    Phase.nothing_available,
    Phase.over_budget,
    Phase.detected_as_bot,
    Phase.failed,
}

ALLOWED_ACTIONS: dict[Phase, set[str]] = {
    Phase.ivr_menu: {"send_dtmf_1"},
    Phase.ivr_name: {"speak_exact_name"},
    Phase.ivr_callback: {"send_callback_digits"},
    Phase.ivr_zip: {"speak_zip_digits"},
    Phase.ivr_confirm: {"speak_yes_or_no"},
    Phase.transfer_wait: {"silence"},
    Phase.hold: {"silence"},
    Phase.human_greeting: {"brief_greeting"},
    Phase.human_ordering: {"structured_ordering"},
    Phase.human_confirming: {"confirm_missing_required_fields"},
    Phase.closing: {"deliver_instructions_and_close"},
}

TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.idle: {Phase.dialing},
    Phase.dialing: {Phase.ivr_menu, Phase.failed},
    Phase.ivr_menu: {Phase.ivr_name, Phase.failed},
    Phase.ivr_name: {Phase.ivr_callback, Phase.failed},
    Phase.ivr_callback: {Phase.ivr_zip, Phase.failed},
    Phase.ivr_zip: {Phase.ivr_confirm, Phase.failed},
    Phase.ivr_confirm: {Phase.transfer_wait, Phase.ivr_menu, Phase.failed},
    Phase.transfer_wait: {Phase.hold, Phase.human_greeting, Phase.failed},
    Phase.hold: {Phase.human_greeting, Phase.failed},
    Phase.human_greeting: {Phase.human_ordering, Phase.detected_as_bot, Phase.failed},
    Phase.human_ordering: {
        Phase.human_confirming,
        Phase.closing,
        Phase.over_budget,
        Phase.nothing_available,
        Phase.detected_as_bot,
        Phase.failed,
    },
    Phase.human_confirming: {Phase.closing, Phase.over_budget, Phase.detected_as_bot, Phase.failed},
    Phase.closing: {Phase.completed, Phase.detected_as_bot, Phase.failed},
}


class InvalidTransitionError(ValueError):
    pass


def allowed_actions_for_phase(phase: Phase) -> set[str]:
    return ALLOWED_ACTIONS.get(phase, set())


def set_phase(state: SessionState, new_phase: Phase) -> SessionState:
    if state.phase == new_phase:
        return state
    if state.phase in TERMINAL_PHASES:
        raise InvalidTransitionError(f"cannot transition from terminal phase {state.phase}")
    allowed = TRANSITIONS.get(state.phase, set())
    if allowed and new_phase not in allowed and new_phase not in TERMINAL_PHASES:
        raise InvalidTransitionError(f"cannot transition from {state.phase} to {new_phase}")
    state.phase = new_phase
    state.updated_at = utcnow()
    if new_phase in TERMINAL_PHASES:
        if new_phase == Phase.completed:
            state.status = CallStatus.completed
            state.outcome = Outcome.completed
        elif new_phase == Phase.failed:
            state.status = CallStatus.failed
            state.outcome = Outcome.failed
        else:
            state.status = CallStatus.terminal
            state.outcome = Outcome(new_phase.value)
    else:
        state.status = CallStatus.in_progress
    return state


def can_complete(state: SessionState) -> bool:
    if state.pizza.status != ItemStatus.confirmed or state.pizza.price is None:
        return False
    if state.side.status == ItemStatus.confirmed and state.side.price is None:
        return False
    if state.drink.status == ItemStatus.confirmed and state.drink.price is None:
        return False
    if state.pricing.total_known is None:
        return False
    if not state.delivery_time or not state.order_number:
        return False
    return state.special_instructions_delivered
