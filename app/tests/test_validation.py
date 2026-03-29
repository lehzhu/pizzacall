from pydantic import ValidationError

from app.extractors.address import extract_zip_code
from app.models import CallCreateRequest


def test_extract_zip_code_uses_final_match() -> None:
    assert extract_zip_code("Austin, TX 78744 and corrected 78745") == "78745"


def test_invalid_phone_number_is_rejected() -> None:
    payload = {
        "store_phone_number": "+15125550199",
        "order": {
            "customer_name": "A",
            "phone_number": "123",
            "delivery_address": "123 Main St Austin TX 78745",
            "pizza": {
                "size": "large",
                "crust": "thin",
                "toppings": ["pepperoni"],
                "acceptable_topping_subs": [],
                "no_go_toppings": [],
            },
            "side": {"first_choice": "wings", "backup_options": [], "if_all_unavailable": "skip"},
            "drink": {"first_choice": "2L Coke", "alternatives": [], "skip_if_over_budget": True},
            "budget_max": 45,
            "special_instructions": "Leave at the door",
        },
    }
    try:
        CallCreateRequest.model_validate(payload)
    except ValidationError:
        return
    raise AssertionError("validation should have failed")

