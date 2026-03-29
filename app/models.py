from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Phase(str, Enum):
    idle = "idle"
    dialing = "dialing"
    ivr_menu = "ivr_menu"
    ivr_name = "ivr_name"
    ivr_callback = "ivr_callback"
    ivr_zip = "ivr_zip"
    ivr_confirm = "ivr_confirm"
    transfer_wait = "transfer_wait"
    hold = "hold"
    human_greeting = "human_greeting"
    human_ordering = "human_ordering"
    human_confirming = "human_confirming"
    closing = "closing"
    completed = "completed"
    nothing_available = "nothing_available"
    over_budget = "over_budget"
    detected_as_bot = "detected_as_bot"
    failed = "failed"


class CallStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    terminal = "terminal"


class Outcome(str, Enum):
    completed = "completed"
    nothing_available = "nothing_available"
    over_budget = "over_budget"
    detected_as_bot = "detected_as_bot"
    failed = "failed"


class ItemStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    skipped = "skipped"
    unavailable = "unavailable"
    rejected = "rejected"


class LLMIntent(str, Enum):
    greet_and_start_order = "greet_and_start_order"
    provide_name = "provide_name"
    provide_phone = "provide_phone"
    provide_address = "provide_address"
    order_pizza = "order_pizza"
    ask_side_availability = "ask_side_availability"
    accept_side = "accept_side"
    reject_side = "reject_side"
    ask_drink_availability = "ask_drink_availability"
    accept_drink = "accept_drink"
    reject_drink = "reject_drink"
    reject_extra = "reject_extra"
    ask_item_price = "ask_item_price"
    ask_total = "ask_total"
    ask_delivery_time = "ask_delivery_time"
    ask_order_number = "ask_order_number"
    deliver_special_instructions = "deliver_special_instructions"
    thank_and_close = "thank_and_close"
    clarify_repeat = "clarify_repeat"


class PizzaRequest(BaseModel):
    size: str
    crust: str
    toppings: list[str] = Field(min_length=1)
    acceptable_topping_subs: list[str] = Field(default_factory=list)
    no_go_toppings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lists(self) -> "PizzaRequest":
        overlap = set(self.acceptable_topping_subs) & set(self.no_go_toppings)
        if overlap:
            raise ValueError(f"acceptable_topping_subs and no_go_toppings overlap: {sorted(overlap)}")
        return self


class SideRequest(BaseModel):
    first_choice: str
    backup_options: list[str] = Field(default_factory=list)
    if_all_unavailable: str = "skip"

    @field_validator("if_all_unavailable")
    @classmethod
    def validate_side_policy(cls, value: str) -> str:
        if value != "skip":
            raise ValueError("if_all_unavailable must be 'skip' for MVP")
        return value


class DrinkRequest(BaseModel):
    first_choice: str
    alternatives: list[str] = Field(default_factory=list)
    skip_if_over_budget: bool = True


class OrderPayload(BaseModel):
    customer_name: str
    phone_number: str
    delivery_address: str
    pizza: PizzaRequest
    side: SideRequest
    drink: DrinkRequest
    budget_max: float
    special_instructions: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("phone_number must be a 10-digit string")
        return value

    @field_validator("budget_max")
    @classmethod
    def validate_budget(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("budget_max must be positive")
        return round(float(value), 2)


class CallCreateRequest(BaseModel):
    store_phone_number: str
    order: OrderPayload

    @field_validator("store_phone_number")
    @classmethod
    def validate_store_number(cls, value: str) -> str:
        if not value.startswith("+") or not value[1:].isdigit():
            raise ValueError("store_phone_number must be E.164-like, e.g. +15125550199")
        return value


class CallCreateResponse(BaseModel):
    call_id: str
    status: CallStatus


class TranscriptTurn(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    speaker: str
    text: str
    confidence: float | None = None
    is_final: bool = True


class IvrRetries(BaseModel):
    menu: int = 0
    name: int = 0
    callback: int = 0
    zip: int = 0
    confirm: int = 0


class PricingState(BaseModel):
    subtotal_known: float | None = None
    total_known: float | None = None
    budget_max: float


class PizzaState(BaseModel):
    requested: PizzaRequest
    confirmed_description: str | None = None
    price: float | None = None
    substitutions: dict[str, str] = Field(default_factory=dict)
    status: ItemStatus = ItemStatus.pending


class SideState(BaseModel):
    requested: str
    confirmed_description: str | None = None
    original: str
    price: float | None = None
    status: ItemStatus = ItemStatus.pending


class DrinkState(BaseModel):
    requested: str
    confirmed_description: str | None = None
    price: float | None = None
    status: ItemStatus = ItemStatus.pending


class ConversationProgress(BaseModel):
    greeted: bool = False
    provided_name: bool = False
    provided_phone: bool = False
    provided_address: bool = False
    pizza_requested: bool = False
    side_option_index: int = 0
    side_attempts: list[str] = Field(default_factory=list)
    drink_option_index: int = 0
    drink_attempts: list[str] = Field(default_factory=list)
    asked_total: bool = False
    asked_delivery_time: bool = False
    asked_order_number: bool = False
    asked_item_prices: list[str] = Field(default_factory=list)
    special_instructions_delivered: bool = False
    thanked: bool = False


class SessionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    call_id: str = Field(default_factory=lambda: f"call_{uuid4().hex[:10]}")
    store_phone_number: str
    input_order: OrderPayload
    zip_code: str
    phase: Phase = Phase.idle
    status: CallStatus = CallStatus.queued
    outcome: Outcome | None = None
    twilio_call_sid: str | None = None
    twilio_stream_sid: str | None = None
    ivr_retries: IvrRetries = Field(default_factory=IvrRetries)
    pizza: PizzaState
    side: SideState
    drink: DrinkState
    pricing: PricingState
    delivery_time: str | None = None
    order_number: str | None = None
    special_instructions_delivered: bool = False
    detected_bot_risk: bool = False
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    conversation: ConversationProgress = Field(default_factory=ConversationProgress)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    ivr_audio_files: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_order(cls, store_phone_number: str, order: OrderPayload, zip_code: str) -> "SessionState":
        return cls(
            store_phone_number=store_phone_number,
            input_order=order,
            zip_code=zip_code,
            pizza=PizzaState(requested=order.pizza),
            side=SideState(requested=order.side.first_choice, original=order.side.first_choice),
            drink=DrinkState(requested=order.drink.first_choice),
            pricing=PricingState(budget_max=order.budget_max),
        )


class SnapshotResult(BaseModel):
    outcome: Outcome | None = None
    pizza: dict[str, Any] | None = None
    side: dict[str, Any] | None = None
    drink: dict[str, Any] | None = None
    total: float | None = None
    delivery_time: str | None = None
    order_number: str | None = None
    special_instructions_delivered: bool = False
    notes: list[str] = Field(default_factory=list)


class CallStatusResponse(BaseModel):
    call_id: str
    status: CallStatus
    phase: Phase
    result_so_far: SnapshotResult


class PizzaResult(BaseModel):
    description: str
    substitutions: dict[str, str] = Field(default_factory=dict)
    price: float | None = None


class SideResult(BaseModel):
    description: str
    original: str
    price: float | None = None


class DrinkResult(BaseModel):
    description: str
    price: float | None = None


class FinalResult(BaseModel):
    outcome: Outcome
    pizza: PizzaResult | None = None
    side: SideResult | None = None
    drink: DrinkResult | None = None
    total: float | None = None
    delivery_time: str | None = None
    order_number: str | None = None
    special_instructions_delivered: bool = False
    notes: list[str] = Field(default_factory=list)


class LLMDecision(BaseModel):
    intent: LLMIntent
    say: str
    state_updates: list[dict[str, Any]] = Field(default_factory=list)

