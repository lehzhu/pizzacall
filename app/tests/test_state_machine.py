import pytest

from app.extractors.address import extract_zip_code
from app.models import OrderPayload, Phase, SessionState
from app.state_machine import InvalidTransitionError, set_phase


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
            "side": {"first_choice": "wings", "backup_options": [], "if_all_unavailable": "skip"},
            "drink": {"first_choice": "2L Coke", "alternatives": [], "skip_if_over_budget": True},
            "budget_max": 45,
            "special_instructions": "Leave at door",
        }
    )
    return SessionState.from_order("+15125550199", order, extract_zip_code(order.delivery_address))


def test_valid_transition_sequence() -> None:
    state = make_state()
    set_phase(state, Phase.dialing)
    set_phase(state, Phase.ivr_menu)
    set_phase(state, Phase.ivr_name)
    assert state.phase == Phase.ivr_name


def test_invalid_transition_raises() -> None:
    state = make_state()
    with pytest.raises(InvalidTransitionError):
        set_phase(state, Phase.human_ordering)

