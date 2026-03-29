from __future__ import annotations

from app.models import LLMIntent, SessionState
from app.policy.deterministic_rules import render_pizza_description
from app.state_machine import allowed_actions_for_phase


def build_system_prompt(state: SessionState, missing_required_fields: list[str]) -> str:
    intents = ", ".join(intent.value for intent in LLMIntent)
    allowed = ", ".join(sorted(allowed_actions_for_phase(state.phase)))
    return (
        "You are a narrow pizza-ordering phone agent. "
        "Return JSON only with keys intent, say, state_updates. "
        f"Allowed intents: {intents}. "
        f"Current phase: {state.phase.value}. "
        f"Allowed actions: {allowed or 'none'}. "
        f"Missing required fields: {', '.join(missing_required_fields) or 'none'}. "
        "Forbidden behaviors: inventing menu items, accepting unlisted substitutions, "
        "accepting no-go toppings, exceeding budget, ending the call early, chatting casually."
    )


def build_user_prompt(state: SessionState, last_transcript: str, missing_required_fields: list[str]) -> str:
    return (
        "Last employee transcript:\n"
        f"{last_transcript}\n\n"
        "Order snapshot:\n"
        f"- pizza: {render_pizza_description(state)}\n"
        f"- side requested: {state.side.requested} ({state.side.status.value})\n"
        f"- drink requested: {state.drink.requested} ({state.drink.status.value})\n"
        f"- budget max: {state.pricing.budget_max}\n"
        f"- notes: {state.notes}\n"
        f"- missing: {missing_required_fields}\n"
    )

