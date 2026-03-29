from app.policy.deterministic_rules import choose_allowed_topping_substitution


def test_choose_first_allowed_substitution() -> None:
    result = choose_allowed_topping_substitution(
        ["olive", "onion", "sausage"],
        acceptable_topping_subs=["onion", "sausage"],
        no_go_toppings=["olive"],
    )
    assert result == "onion"


def test_reject_only_no_go_substitution() -> None:
    result = choose_allowed_topping_substitution(
        ["olive"],
        acceptable_topping_subs=["onion"],
        no_go_toppings=["olive"],
    )
    assert result is None

