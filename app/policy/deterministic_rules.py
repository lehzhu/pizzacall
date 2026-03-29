from __future__ import annotations

from collections.abc import Iterable

from app.models import ItemStatus, SessionState


GREETING_PATTERNS = (
    "hello",
    "hi",
    "thanks for calling",
    "what can i get you",
    "what can i get started",
    "can i help you",
    "pickup or delivery",
    "name for the order",
)

IVR_PATTERNS = (
    "press 1 for delivery",
    "press 2 for carryout",
    "say the name for the order",
    "please enter your 10-digit callback number",
    "please say your delivery zip code",
    "please hold while we connect you",
)

BOT_PATTERNS = (
    "are you a robot",
    "are you ai",
    "is this a bot",
    "i can't understand you",
    "hang up",
    "cannot continue",
)

EXTRA_PATTERNS = (
    "sauce",
    "extra cheese",
    "upgrade",
    "dessert",
    "combo",
    "meal deal",
)


def normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def render_pizza_description(state: SessionState) -> str:
    toppings: list[str] = []
    for topping in state.input_order.pizza.toppings:
        toppings.append(state.pizza.substitutions.get(topping, topping))
    joined = ", ".join(toppings)
    return f"{state.input_order.pizza.size} {state.input_order.pizza.crust} pizza with {joined}"


def choose_allowed_topping_substitution(
    offered_options: Iterable[str],
    acceptable_topping_subs: list[str],
    no_go_toppings: list[str],
) -> str | None:
    acceptable = {normalize(item): item for item in acceptable_topping_subs}
    forbidden = {normalize(item) for item in no_go_toppings}
    for option in offered_options:
        key = normalize(option)
        if key in forbidden:
            continue
        if key in acceptable:
            return acceptable[key]
    return None


def next_side_candidate(state: SessionState) -> str | None:
    candidates = [state.input_order.side.first_choice, *state.input_order.side.backup_options]
    for candidate in candidates:
        if candidate not in state.conversation.side_attempts:
            return candidate
    return None


def next_drink_candidate(state: SessionState) -> str | None:
    candidates = [state.input_order.drink.first_choice, *state.input_order.drink.alternatives]
    for candidate in candidates:
        if candidate not in state.conversation.drink_attempts:
            return candidate
    return None


def should_decline_extra(text: str) -> bool:
    lowered = normalize(text)
    return any(pattern in lowered for pattern in EXTRA_PATTERNS)


def is_known_ivr_phrase(text: str) -> bool:
    lowered = normalize(text)
    return any(pattern in lowered for pattern in IVR_PATTERNS)


def classify_human_turn(text: str) -> bool:
    lowered = normalize(text)
    if is_known_ivr_phrase(lowered):
        return False
    return len(lowered.split()) > 1 and any(pattern in lowered for pattern in GREETING_PATTERNS)


def detect_bot_accusation(text: str) -> bool:
    lowered = normalize(text)
    return any(pattern in lowered for pattern in BOT_PATTERNS)


def required_items_subtotal(state: SessionState) -> float | None:
    if state.pizza.price is None:
        return None
    total = state.pizza.price
    if state.side.status == ItemStatus.confirmed:
        if state.side.price is None:
            return None
        total += state.side.price
    return round(total, 2)


def is_over_budget(state: SessionState) -> bool:
    subtotal = required_items_subtotal(state)
    return subtotal is not None and subtotal > state.pricing.budget_max


def should_skip_drink(state: SessionState) -> bool:
    if not state.input_order.drink.skip_if_over_budget:
        return False
    subtotal = required_items_subtotal(state)
    if subtotal is None:
        return True
    if state.drink.price is None:
        return True
    return subtotal + state.drink.price > state.pricing.budget_max

