from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.policy import PolicyEngine
from app.models import NormalizedOrderRequest, SessionState


@dataclass(slots=True)
class PlannerStep:
    text: str | None
    done: bool = False
    note: str | None = None


class HumanConversationPlanner:
    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def next_step(self, session: SessionState, transcript: str) -> PlannerStep:
        facts = session.partial_result
        order = session.order_request
        lowered = transcript.lower()

        if any(term in lowered for term in ["bot", "robot", "automated"]):
            return PlannerStep(text="Sorry about that. I'll call back later.", done=True, note="bot_suspected")
        if any(term in lowered for term in ["dumb bitch", "fuck you", "go away"]):
            return PlannerStep(text="Sorry. Never mind. Thanks.", done=True, note="bot_suspected")

        if self._asks_customer_name(lowered):
            return self._remember(facts, "customer_name", order.customer_name)

        if self._asks_delivery_or_pickup(lowered):
            return self._remember(facts, "fulfillment_type", "Delivery.")

        if not facts.get("delivery_opening_sent"):
            facts["delivery_opening_sent"] = True
            return PlannerStep(text=self._opening(order))

        if self._is_order_prompt(lowered):
            facts["pizza_requested"] = True
            return self._remember(facts, "pizza_request", self._pizza_request(order))

        if self._mentions_unavailable(lowered):
            return PlannerStep(text=self._substitution_prompt(session, lowered))

        offered_no_go = self._offered_no_go_topping(order, lowered)
        if offered_no_go:
            return PlannerStep(text=f"No {offered_no_go}.")

        if "you want the pizza or not" in lowered:
            return PlannerStep(text="Yes, the pizza.")

        if self._pizza_confirmed(lowered, order):
            facts["pizza_confirmed"] = True

        if facts.get("pizza_confirmed") and order.side and not facts.get("side_requested"):
            facts["side_requested"] = True
            return self._remember(facts, "side_request", self._side_request(order))

        if order.side and self._side_confirmed(lowered, order):
            facts["side_resolved"] = True

        if facts.get("side_resolved") and order.drink and not facts.get("drink_requested"):
            facts["drink_requested"] = True
            return self._remember(facts, "drink_request", self._drink_request(order))

        if order.drink and self._drink_confirmed(lowered, order):
            facts["drink_resolved"] = True

        if self._employee_is_recapping(lowered):
            facts["pizza_confirmed"] = True
            if order.side:
                facts["side_resolved"] = True

        if self._asks_if_anything_else(lowered):
            if order.drink and not facts.get("drink_resolved"):
                facts["drink_requested"] = True
                return self._remember(facts, "drink_request", self._drink_request(order))
            if order.special_instructions and not facts.get("special_instructions_delivered"):
                facts["special_instructions_delivered"] = True
                return self._remember(facts, "instructions", f"Please add this note: {order.special_instructions}.")
            missing = self._missing_confirmation_fields(facts)
            if missing:
                return self._remember(facts, "confirmation", self._confirmation_prompt(missing))
            return PlannerStep(text="That's everything. Thank you.", done=True)

        if self._employee_is_wrapping_up(lowered):
            missing = self._missing_confirmation_fields(facts)
            if missing:
                return self._remember(facts, "confirmation", self._confirmation_prompt(missing))
            return PlannerStep(text="Thank you.", done=True)

        return PlannerStep(text=None)

    def _opening(self, order: NormalizedOrderRequest) -> str:
        return f"Delivery for {order.customer_name}."

    def _pizza_request(self, order: NormalizedOrderRequest) -> str:
        if order.pizza.description:
            return order.pizza.description[0].upper() + order.pizza.description[1:]
        toppings = ", ".join(order.pizza.desired_toppings)
        if toppings:
            return f"A pizza with {toppings}."
        return "A pizza for delivery."

    def _substitution_prompt(self, session: SessionState, transcript: str) -> str:
        order = session.order_request
        facts = session.partial_result
        for desired, subs in order.pizza.acceptable_topping_subs.items():
            if desired.lower() in transcript:
                for sub in subs:
                    if sub.lower() not in {item.lower() for item in order.pizza.no_go_toppings}:
                        facts.setdefault("pizza_substitutions", {})[desired] = sub
                        return f"{sub.title()} instead of {desired} is fine."
        return "What topping can replace that?"

    def _side_request(self, order: NormalizedOrderRequest) -> str:
        assert order.side is not None
        return f"{order.side.first_choice}, please."

    def _drink_request(self, order: NormalizedOrderRequest) -> str:
        assert order.drink is not None
        return f"{order.drink.first_choice}, please."

    def _missing_confirmation_fields(self, facts: dict[str, Any]) -> list[str]:
        required = {
            "item_prices_collected": "item prices",
            "total_collected": "total",
            "delivery_time_collected": "delivery time",
            "order_number_collected": "order number",
        }
        return [label for key, label in required.items() if not facts.get(key)]

    def _confirmation_prompt(self, missing: list[str]) -> str:
        if len(missing) == 1:
            if missing[0] == "order number":
                return "What's the order number?"
            if missing[0] == "delivery time":
                return "What's the delivery time?"
            if missing[0] == "total":
                return "What's the total?"
            return f"What's the {missing[0]}?"
        joined = ", ".join(missing[:-1]) + f", and {missing[-1]}"
        return f"What's the {joined}?"

    def _remember(self, facts: dict[str, Any], key: str, text: str) -> PlannerStep:
        if facts.get(f"last_{key}") == text:
            return PlannerStep(text=None)
        facts[f"last_{key}"] = text
        facts["last_agent_text"] = text
        return PlannerStep(text=text)

    def _is_order_prompt(self, lowered: str) -> bool:
        return any(
            term in lowered
            for term in [
                "how may i take your order",
                "what can i get",
                "go ahead",
                "started for you",
                "what are you trying to order",
                "what do you want to order",
                "what would you like to order",
            ]
        )

    def _asks_customer_name(self, lowered: str) -> bool:
        return "what is your name" in lowered or "what's your name" in lowered or "name for the order" in lowered or "name on the order" in lowered

    def _asks_delivery_or_pickup(self, lowered: str) -> bool:
        return ("delivery" in lowered and "pickup" in lowered) or "pick up or delivery" in lowered

    def _mentions_unavailable(self, lowered: str) -> bool:
        return any(term in lowered for term in ["out of", "don't have", "unavailable", "sold out"])

    def _offered_no_go_topping(self, order: NormalizedOrderRequest, lowered: str) -> str | None:
        for topping in order.pizza.no_go_toppings:
            if topping.lower() in lowered:
                return topping
        return None

    def _pizza_confirmed(self, lowered: str, order: NormalizedOrderRequest) -> bool:
        signals = ["i got your pizza", "you want the pizza", "pizza", "thin crust"]
        topping_hits = sum(1 for topping in order.pizza.desired_toppings if topping.lower() in lowered)
        return any(signal in lowered for signal in signals) and topping_hits >= 0

    def _side_confirmed(self, lowered: str, order: NormalizedOrderRequest) -> bool:
        assert order.side is not None
        return order.side.first_choice.lower() in lowered or "wings" in lowered

    def _drink_confirmed(self, lowered: str, order: NormalizedOrderRequest) -> bool:
        assert order.drink is not None
        choices = [order.drink.first_choice, *order.drink.alternatives]
        return any(choice.lower() in lowered for choice in choices)

    def _employee_is_recapping(self, lowered: str) -> bool:
        return any(term in lowered for term in ["i got your", "your order is", "so you want", "you want twelve count"])

    def _asks_if_anything_else(self, lowered: str) -> bool:
        return any(term in lowered for term in ["anything else", "is that everything", "do you want anything else"])

    def _employee_is_wrapping_up(self, lowered: str) -> bool:
        return any(term in lowered for term in ["have a good day", "all set", "that'll be", "your order is"])
