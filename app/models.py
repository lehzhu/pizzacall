from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
PHONE_RE = re.compile(r"\D")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone_digits(phone_number: str) -> str:
    return PHONE_RE.sub("", phone_number)


def normalize_e164(phone_number: str) -> str:
    digits = normalize_phone_digits(phone_number)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    raise ValueError("phone_number must normalize to 10 US digits")


def extract_zip_code(address: str) -> str:
    match = ZIP_RE.search(address)
    if not match:
        raise ValueError("delivery_address must contain a ZIP code")
    return match.group(1)


class Phase(str, Enum):
    dialing = "dialing"
    hold = "hold"
    human = "human"
    completed = "completed"
    failed = "failed"


class IVRSubphase(str, Enum):
    menu = "menu"
    name = "name"
    callback = "callback"
    zip = "zip"
    confirm = "confirm"
    transfer = "transfer"


class HumanSubphase(str, Enum):
    greeting = "greeting"
    identity_collection = "identity_collection"
    pizza_order = "pizza_order"
    substitution_handling = "substitution_handling"
    side_handling = "side_handling"
    drink_handling = "drink_handling"
    total_time_order_number_collection = "total_time_order_number_collection"
    instructions = "instructions"
    close = "close"


class Outcome(str, Enum):
    completed = "completed"
    nothing_available = "nothing_available"
    over_budget = "over_budget"
    detected_as_bot = "detected_as_bot"
    failed = "failed"


class PendingActionType(str, Enum):
    wait = "wait"
    dtmf = "dtmf"
    say = "say"


class PizzaPreferences(BaseModel):
    description: str = ""
    desired_toppings: list[str] = Field(default_factory=list)
    acceptable_topping_subs: dict[str, list[str]] = Field(default_factory=dict)
    no_go_toppings: list[str] = Field(default_factory=list)


class SidePreferences(BaseModel):
    first_choice: str
    backup_options: list[str] = Field(default_factory=list)
    if_all_unavailable: str = "skip"


class DrinkPreferences(BaseModel):
    first_choice: str
    alternatives: list[str] = Field(default_factory=list)
    skip_if_over_budget: bool = False


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    customer_name: str
    destination_number: str
    phone_number: str
    delivery_address: str
    budget_max: float
    pizza: PizzaPreferences | dict[str, Any]
    side: SidePreferences | dict[str, Any] | None = None
    drink: DrinkPreferences | dict[str, Any] | None = None
    special_instructions: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("customer_name", "delivery_address")
    @classmethod
    def require_non_empty_string(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("destination_number", "phone_number")
    @classmethod
    def require_ten_digits(cls, value: str) -> str:
        digits = normalize_phone_digits(value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise ValueError("phone number must contain exactly 10 US digits")
        return digits

    @field_validator("budget_max")
    @classmethod
    def require_positive_budget(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("budget_max must be positive")
        return float(value)

    @field_validator("pizza", mode="before")
    @classmethod
    def require_pizza_object(cls, value: Any) -> Any:
        if not value or not isinstance(value, dict | PizzaPreferences):
            raise ValueError("pizza object must exist")
        return value


class NormalizedOrderRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    customer_name: str
    destination_number: str
    destination_number_e164: str
    phone_number: str
    phone_number_e164: str
    delivery_address: str
    zip_code: str
    budget_max: float
    pizza: PizzaPreferences
    side: SidePreferences | None = None
    drink: DrinkPreferences | None = None
    special_instructions: str = ""
    raw_payload: dict[str, Any]

    @classmethod
    def from_order_request(cls, payload: OrderRequest) -> "NormalizedOrderRequest":
        pizza = payload.pizza if isinstance(payload.pizza, PizzaPreferences) else PizzaPreferences.model_validate(payload.pizza)
        side = None
        if payload.side is not None:
            side = payload.side if isinstance(payload.side, SidePreferences) else SidePreferences.model_validate(payload.side)
        drink = None
        if payload.drink is not None:
            drink = payload.drink if isinstance(payload.drink, DrinkPreferences) else DrinkPreferences.model_validate(payload.drink)
        return cls(
            customer_name=payload.customer_name,
            destination_number=payload.destination_number,
            destination_number_e164=normalize_e164(payload.destination_number),
            phone_number=payload.phone_number,
            phone_number_e164=normalize_e164(payload.phone_number),
            delivery_address=payload.delivery_address,
            zip_code=extract_zip_code(payload.delivery_address),
            budget_max=payload.budget_max,
            pizza=pizza,
            side=side,
            drink=drink,
            special_instructions=payload.special_instructions.strip(),
            raw_payload=payload.model_dump(mode="json"),
        )


class RestaurantProfile(BaseModel):
    prompt_patterns: dict[str, list[str]] = Field(default_factory=dict)
    failure_patterns: list[str] = Field(default_factory=list)
    hold_patterns: list[str] = Field(default_factory=list)
    human_patterns: list[str] = Field(default_factory=list)
    bot_suspected_patterns: list[str] = Field(default_factory=list)
    ivr_targets: dict[str, str] = Field(
        default_factory=lambda: {
            "menu": "1",
            "confirm_yes": "yes",
            "confirm_no": "no",
        }
    )
    max_substate_retries: int = 2
    max_terminal_failures: int = 3
    human_grace_seconds: float = 2.0


class PendingAction(BaseModel):
    type: PendingActionType
    value: str | None = None
    reason: str = ""
    id: str = Field(default_factory=lambda: str(uuid4()))


class StructuredItem(BaseModel):
    description: str
    price: float
    original: str | None = None
    note: str | None = None
    substitutions: dict[str, str] = Field(default_factory=dict)


class OrderResult(BaseModel):
    outcome: Outcome
    pizza: StructuredItem | None
    side: StructuredItem | None = None
    drink: StructuredItem | None = None
    total: float | None = None
    delivery_time: str | None = None
    order_number: str | None = None
    special_instructions_delivered: bool = False
    notes: list[str] = Field(default_factory=list)


class SessionState(BaseModel):
    session_id: str
    call_sid: str | None = None
    stream_sid: str | None = None
    phase: Phase = Phase.dialing
    subphase: str = IVRSubphase.menu.value
    ivr_retry_count: int = 0
    terminal_failure_count: int = 0
    human_confidence: float = 0.0
    pending_action: PendingAction | None = None
    audio_output_enabled: bool = False
    partial_result: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    timestamps: dict[str, str] = Field(default_factory=dict)
    order_request: NormalizedOrderRequest
    final_result: OrderResult | None = None
    events_seen: set[str] = Field(default_factory=set)
    transcript_buffer: list[str] = Field(default_factory=list)
    employee_speaking: bool = False

    @model_validator(mode="after")
    def ensure_initial_timestamp(self) -> "SessionState":
        if "created_at" not in self.timestamps:
            self.timestamps["created_at"] = utc_now().isoformat()
        return self
