from __future__ import annotations

from app.models import OrderResult, Outcome, SessionState, StructuredItem


class ResultAssembler:
    def assemble(
        self,
        *,
        outcome: Outcome,
        pizza: StructuredItem | None,
        side: StructuredItem | None = None,
        drink: StructuredItem | None = None,
        total: float | None = None,
        delivery_time: str | None = None,
        order_number: str | None = None,
        special_instructions_delivered: bool = False,
        notes: list[str] | None = None,
    ) -> OrderResult:
        return OrderResult(
            outcome=outcome,
            pizza=pizza,
            side=side,
            drink=drink,
            total=total,
            delivery_time=delivery_time,
            order_number=order_number,
            special_instructions_delivered=special_instructions_delivered,
            notes=notes or [],
        )

    def from_session(
        self,
        *,
        session: SessionState,
        outcome: Outcome,
        notes: list[str] | None = None,
    ) -> OrderResult:
        partial = session.partial_result
        item_prices = partial.get("item_prices", [])

        pizza = StructuredItem(
            description=session.order_request.pizza.description or "pizza",
            price=float(item_prices[0]) if len(item_prices) > 0 else 0.0,
            substitutions=partial.get("pizza_substitutions", {}),
        )

        side = None
        if session.order_request.side is not None and not partial.get("side_skipped", False):
            side = StructuredItem(
                description=partial.get("side_description", session.order_request.side.first_choice),
                original=session.order_request.side.first_choice,
                price=float(item_prices[1]) if len(item_prices) > 1 else 0.0,
                note=partial.get("side_note"),
            )

        drink = None
        drink_skip_reason = partial.get("drink_skipped_reason")
        if session.order_request.drink is not None and not drink_skip_reason:
            drink_index = 2 if side is not None else 1
            drink = StructuredItem(
                description=partial.get("drink_description", session.order_request.drink.first_choice),
                price=float(item_prices[drink_index]) if len(item_prices) > drink_index else 0.0,
                note=partial.get("drink_note"),
            )

        combined_notes = list(notes or [])
        if drink_skip_reason:
            combined_notes.append(drink_skip_reason)

        return self.assemble(
            outcome=outcome,
            pizza=pizza if partial.get("pizza_confirmed", True) or outcome != Outcome.nothing_available else None,
            side=side,
            drink=drink,
            total=partial.get("total"),
            delivery_time=partial.get("delivery_time"),
            order_number=partial.get("order_number"),
            special_instructions_delivered=partial.get("special_instructions_delivered", False),
            notes=combined_notes,
        )
