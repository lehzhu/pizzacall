import asyncio

from app.pipeline.groq_llm import GroqLLMService


def test_groq_service_returns_authoritative_draft() -> None:
    service = GroqLLMService("test-key")
    reply = asyncio.run(
        service.generate_human_reply(
            transcript="What's the name for the order?",
            draft="Jordan Mitchell",
            missing_fields=[],
        )
    )
    assert reply == "Jordan Mitchell"
