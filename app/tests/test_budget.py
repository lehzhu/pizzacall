from app.extractors.address import extract_zip_code
from app.models import ItemStatus, OrderPayload, SessionState
from app.policy.deterministic_rules import is_over_budget, should_skip_drink


def make_state() -> SessionState:
    order = OrderPayload.model_validate(
        {
            "customer_name": "Jordan Smith",
            "phone_number": "5125550147",
            "delivery_address": "123 Main St Austin TX 78745",
            "pizza": {
                "size": "large",
                "crust": "thin crust",
                "toppings": ["pepperoni"],
                "acceptable_topping_subs": [],
                "no_go_toppings": [],
            },
            "side": {"first_choice": "wings", "backup_options": ["garlic bread"], "if_all_unavailable": "skip"},
            "drink": {"first_choice": "2L Coke", "alternatives": [], "skip_if_over_budget": True},
            "budget_max": 20,
            "special_instructions": "Leave at the door",
        }
    )
    return SessionState.from_order("+15125550199", order, extract_zip_code(order.delivery_address))


def test_over_budget_after_required_items() -> None:
    state = make_state()
    state.pizza.price = 14
    state.pizza.status = ItemStatus.confirmed
    state.side.status = ItemStatus.confirmed
    state.side.price = 8
    assert is_over_budget(state) is True


def test_skip_drink_if_price_unknown() -> None:
    state = make_state()
    state.pizza.price = 14
    state.pizza.status = ItemStatus.confirmed
    state.side.status = ItemStatus.skipped
    assert should_skip_drink(state) is True

