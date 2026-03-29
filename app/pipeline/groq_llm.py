from __future__ import annotations

from dataclasses import dataclass

try:
    from groq import AsyncGroq
except ModuleNotFoundError:  # pragma: no cover - optional dependency in tests
    AsyncGroq = None


@dataclass(slots=True)
class GroqConfig:
    model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.1
    max_tokens: int = 120


class GroqLLMService:
    def __init__(self, api_key: str, config: GroqConfig | None = None) -> None:
        self.api_key = api_key
        self.config = config or GroqConfig()
        self.client = AsyncGroq(api_key=api_key) if api_key and AsyncGroq is not None else None

    async def generate_human_reply(self, *, transcript: str, draft: str, missing_fields: list[str]) -> str:
        # Phone-order replies must preserve exact slot values. Rewriting the
        # planner's draft caused the model to invent items and confirmation
        # details, so the draft itself is the authoritative utterance.
        return draft
