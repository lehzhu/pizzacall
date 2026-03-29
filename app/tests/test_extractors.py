from app.extractors.delivery_time import extract_delivery_time
from app.extractors.money import extract_exact_money
from app.extractors.order_number import extract_order_number


def test_extract_exact_money() -> None:
    assert extract_exact_money("The pizza is $18.50 before tax.") == 18.5


def test_ignore_approximate_money() -> None:
    assert extract_exact_money("It'll be about 30 bucks.") is None


def test_extract_delivery_time() -> None:
    assert extract_delivery_time("Delivery should take about 35 to 40 minutes.") == "35 to 40 minutes"


def test_extract_order_number() -> None:
    assert extract_order_number("Your order number is 4412.") == "4412"

