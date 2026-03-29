from __future__ import annotations

import json

import httpx

from app.config import get_settings
from app.errors import ProviderConfigurationError, ProviderRequestError
from app.models import ItemStatus, LLMDecision, LLMIntent, SessionState
from app.policy.prompts import build_system_prompt, build_user_prompt


def _missing_required_fields(state: SessionState) -> list[str]:
    missing: list[str] = []
    if state.pizza.price is None:
        missing.append("pizza_price")
    if state.side.status == ItemStatus.confirmed and state.side.price is None:
        missing.append("side_price")
    if state.drink.status == ItemStatus.confirmed and state.drink.price is None:
        missing.append("drink_price")
    if state.pricing.total_known is None:
        missing.append("total")
    if state.delivery_time is None:
        missing.append("delivery_time")
    if state.order_number is None:
        missing.append("order_number")
    if not state.special_instructions_delivered:
        missing.append("special_instructions")
    return missing


class LLMPolicy:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def decide(self, state: SessionState, last_employee_text: str) -> LLMDecision:
        if not self.settings.groq_api_key:
            raise ProviderConfigurationError("GROQ_API_KEY is required for human conversation policy.")

        payload = {
            "model": self.settings.groq_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": build_system_prompt(state, _missing_required_fields(state)),
                },
                {
                    "role": "user",
                    "content": build_user_prompt(state, last_employee_text, _missing_required_fields(state)),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderRequestError(f"Groq request failed: {exc}") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return LLMDecision.model_validate(data)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderRequestError("Groq returned an invalid response payload.") from exc
