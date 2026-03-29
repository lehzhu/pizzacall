from __future__ import annotations

from app.models import (
    DrinkResult,
    FinalResult,
    ItemStatus,
    Outcome,
    PizzaResult,
    SessionState,
    SideResult,
    SnapshotResult,
)
from app.policy.deterministic_rules import render_pizza_description


def build_snapshot(state: SessionState) -> SnapshotResult:
    return SnapshotResult(
        outcome=state.outcome,
        pizza={
            "description": state.pizza.confirmed_description or render_pizza_description(state),
            "substitutions": state.pizza.substitutions,
            "price": state.pizza.price,
            "status": state.pizza.status,
        },
        side=None
        if state.side.status == ItemStatus.skipped
        else {
            "description": state.side.confirmed_description or state.side.requested,
            "original": state.side.original,
            "price": state.side.price,
            "status": state.side.status,
        },
        drink=None
        if state.drink.status == ItemStatus.skipped
        else {
            "description": state.drink.confirmed_description or state.drink.requested,
            "price": state.drink.price,
            "status": state.drink.status,
        },
        total=state.pricing.total_known,
        delivery_time=state.delivery_time,
        order_number=state.order_number,
        special_instructions_delivered=state.special_instructions_delivered,
        notes=list(state.notes),
    )


def build_final_result(state: SessionState) -> FinalResult:
    outcome = state.outcome or Outcome.failed
    pizza = PizzaResult(
        description=state.pizza.confirmed_description or render_pizza_description(state),
        substitutions=state.pizza.substitutions,
        price=state.pizza.price,
    )
    side = None
    if state.side.status == ItemStatus.confirmed:
        side = SideResult(
            description=state.side.confirmed_description or state.side.requested,
            original=state.side.original,
            price=state.side.price,
        )
    drink = None
    if state.drink.status == ItemStatus.confirmed:
        drink = DrinkResult(
            description=state.drink.confirmed_description or state.drink.requested,
            price=state.drink.price,
        )
    return FinalResult(
        outcome=outcome,
        pizza=pizza,
        side=side,
        drink=drink,
        total=state.pricing.total_known,
        delivery_time=state.delivery_time,
        order_number=state.order_number,
        special_instructions_delivered=state.special_instructions_delivered,
        notes=list(state.notes),
    )

