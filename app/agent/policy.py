from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import DrinkPreferences, NormalizedOrderRequest, OrderResult, Outcome, PizzaPreferences, SidePreferences, StructuredItem


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    item: str | None = None


class PolicyEngine:
    def snapshot(self, order: NormalizedOrderRequest) -> dict[str, Any]:
        return {
            "budget_max": order.budget_max,
            "pizza": order.pizza.model_dump(mode="json"),
            "side": order.side.model_dump(mode="json") if order.side else None,
            "drink": order.drink.model_dump(mode="json") if order.drink else None,
        }

    def choose_pizza_topping(self, pizza: PizzaPreferences, available_toppings: list[str]) -> PolicyDecision:
        no_go = {item.lower() for item in pizza.no_go_toppings}
        available = {item.lower(): item for item in available_toppings}
        for topping in pizza.desired_toppings:
            if topping.lower() in no_go:
                return PolicyDecision(False, f"desired topping {topping} is in no-go list")
            if topping.lower() in available:
                return PolicyDecision(True, "desired topping available", available[topping.lower()])
            for substitute in pizza.acceptable_topping_subs.get(topping, []):
                if substitute.lower() in no_go:
                    continue
                if substitute.lower() in available:
                    return PolicyDecision(True, f"substitute allowed for {topping}", available[substitute.lower()])
        return PolicyDecision(False, "no desired or acceptable topping available")

    def choose_side(self, side: SidePreferences | None, available_items: list[str]) -> PolicyDecision:
        if side is None:
            return PolicyDecision(True, "side not requested")
        available = {item.lower(): item for item in available_items}
        if side.first_choice.lower() in available:
            return PolicyDecision(True, "first choice available", available[side.first_choice.lower()])
        for backup in side.backup_options:
            if backup.lower() in available:
                return PolicyDecision(True, "backup available", available[backup.lower()])
        if side.if_all_unavailable == "skip":
            return PolicyDecision(True, "side skipped")
        return PolicyDecision(False, "no side options available")

    def choose_drink(
        self,
        drink: DrinkPreferences | None,
        available_items: list[str],
        projected_total_before_drink: float,
        budget_max: float,
        candidate_price: float | None = None,
    ) -> PolicyDecision:
        if drink is None:
            return PolicyDecision(True, "drink not requested")
        if drink.skip_if_over_budget and candidate_price is not None and projected_total_before_drink + candidate_price > budget_max:
            return PolicyDecision(True, "drink skipped for budget")
        available = {item.lower(): item for item in available_items}
        if drink.first_choice.lower() in available:
            return PolicyDecision(True, "first choice available", available[drink.first_choice.lower()])
        for alt in drink.alternatives:
            if alt.lower() in available:
                return PolicyDecision(True, "alternative available", available[alt.lower()])
        return PolicyDecision(True, "drink unavailable and skipped") if drink.skip_if_over_budget else PolicyDecision(False, "no drink options available")

    def budget_allows(self, subtotal: float, budget_max: float) -> PolicyDecision:
        if subtotal > budget_max:
            return PolicyDecision(False, "subtotal exceeds budget")
        return PolicyDecision(True, "subtotal within budget")

    def validate_completion(self, result: OrderResult) -> PolicyDecision:
        if result.outcome != Outcome.completed:
            return PolicyDecision(True, "not a completed outcome")
        if result.pizza is None:
            return PolicyDecision(False, "missing pizza")
        if result.total is None:
            return PolicyDecision(False, "missing total")
        if result.delivery_time is None:
            return PolicyDecision(False, "missing delivery time")
        if result.order_number is None:
            return PolicyDecision(False, "missing order number")
        if not result.special_instructions_delivered:
            return PolicyDecision(False, "special instructions not delivered")
        ordered_items = [item for item in [result.pizza, result.side, result.drink] if item is not None]
        if any(item.price is None for item in ordered_items):
            return PolicyDecision(False, "missing ordered item price")
        return PolicyDecision(True, "completed outcome has required facts")

    def build_nothing_available(self, note: str) -> OrderResult:
        return OrderResult(outcome=Outcome.nothing_available, pizza=None, notes=[note])

    def build_over_budget(self, pizza: StructuredItem, side: StructuredItem | None, notes: list[str]) -> OrderResult:
        return OrderResult(outcome=Outcome.over_budget, pizza=pizza, side=side, notes=notes)
