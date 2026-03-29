from app.agent.policy import PolicyEngine
from app.models import DrinkPreferences, PizzaPreferences, SidePreferences


def test_rejects_no_go_topping() -> None:
    engine = PolicyEngine()
    pizza = PizzaPreferences(
        desired_toppings=["anchovies"],
        acceptable_topping_subs={"anchovies": ["mushrooms"]},
        no_go_toppings=["anchovies", "olives"],
    )
    decision = engine.choose_pizza_topping(pizza, ["Mushrooms"])
    assert not decision.allowed


def test_side_uses_backup_in_order() -> None:
    engine = PolicyEngine()
    side = SidePreferences(first_choice="breadsticks", backup_options=["wings", "salad"], if_all_unavailable="skip")
    decision = engine.choose_side(side, ["Salad", "Wings"])
    assert decision.allowed
    assert decision.item == "Wings"


def test_drink_skipped_when_budget_exceeded() -> None:
    engine = PolicyEngine()
    drink = DrinkPreferences(first_choice="cola", alternatives=["water"], skip_if_over_budget=True)
    decision = engine.choose_drink(drink, ["Cola"], projected_total_before_drink=25.0, budget_max=26.0, candidate_price=2.0)
    assert decision.allowed
    assert decision.reason == "drink skipped for budget"
