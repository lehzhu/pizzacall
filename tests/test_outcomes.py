from app.agent.policy import PolicyEngine
from app.agent.result import ResultAssembler
from app.models import NormalizedOrderRequest, OrderRequest, Outcome, SessionState, StructuredItem


def test_completed_requires_total_and_order_metadata() -> None:
    result = ResultAssembler().assemble(
        outcome=Outcome.completed,
        pizza=StructuredItem(description="Large pepperoni pizza", price=18.0),
        side=None,
        drink=None,
        special_instructions_delivered=True,
    )
    decision = PolicyEngine().validate_completion(result)
    assert not decision.allowed
    assert decision.reason == "missing total"


def test_completed_result_passes_when_required_facts_present() -> None:
    result = ResultAssembler().assemble(
        outcome=Outcome.completed,
        pizza=StructuredItem(description="Large pepperoni pizza", price=18.0),
        side=StructuredItem(description="Wings", original="Breadsticks", price=6.0, note="backup option"),
        drink=None,
        total=24.0,
        delivery_time="35 minutes",
        order_number="ABC123",
        special_instructions_delivered=True,
    )
    decision = PolicyEngine().validate_completion(result)
    assert decision.allowed


def test_non_completed_outcome_preserves_partial_data_and_drink_skip_note() -> None:
    order = NormalizedOrderRequest.from_order_request(
        OrderRequest(
            customer_name="Jordan Mitchell",
            destination_number="6479165156",
            phone_number="5125550147",
            delivery_address="4821 Elm Street, Apt 3B, Austin, TX 78745",
            budget_max=45.0,
            pizza={"description": "large thin crust pizza", "desired_toppings": ["pepperoni"]},
            side={"first_choice": "wings"},
            drink={"first_choice": "2L Coke", "alternatives": ["2L Sprite"], "skip_if_over_budget": True},
        )
    )
    session = SessionState(session_id=order.session_id, order_request=order)
    session.partial_result.update(
        {
            "pizza_confirmed": True,
            "item_prices": [18.0, 9.0],
            "total": 27.0,
            "delivery_time": "35 minutes",
            "drink_skipped_reason": "Drink skipped because projected total would exceed budget_max",
        }
    )
    result = ResultAssembler().from_session(session=session, outcome=Outcome.over_budget, notes=["Budget exceeded"])
    assert result.pizza is not None
    assert result.total == 27.0
    assert result.drink is None
    assert "Drink skipped because projected total would exceed budget_max" in result.notes
