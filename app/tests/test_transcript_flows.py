import asyncio
import io
import wave

from app.logger import JsonlLogger
from app.models import CallCreateRequest, LLMDecision, LLMIntent
from app.orchestrator import CallOrchestrator
from app.store import InMemoryCallStore


class FakeTwilioAdapter:
    async def start_outbound_call(self, session):
        return f"CA{session.call_id}"

    def build_voice_response(self, session) -> str:
        return "<Response />"


class FakeDeepgramSTT:
    async def consume_queue(self, audio_queue, on_transcript) -> None:
        while await audio_queue.get() is not None:
            continue


class FakeCartesiaTTS:
    async def synthesize_to_file(self, text: str, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_tiny_wav())
        return path

    async def synthesize_mulaw_frames(self, text: str, frame_ms: int = 20) -> list[bytes]:
        return [b"\xff" * 160]


class ScriptedPolicy:
    async def decide(self, state, last_employee_text: str) -> LLMDecision:
        lowered = last_employee_text.lower()
        if "hello" in lowered:
            return LLMDecision(intent=LLMIntent.greet_and_start_order, say="Hi, I'd like to place a delivery order.")
        if "garlic bread" in lowered:
            return LLMDecision(intent=LLMIntent.ask_item_price, say="What is the price for the pizza?")
        if "pizza is" in lowered:
            return LLMDecision(intent=LLMIntent.ask_total, say="What is the total?")
        if "total is" in lowered:
            return LLMDecision(intent=LLMIntent.ask_delivery_time, say="What is the estimated delivery time?")
        if "order number" in lowered:
            return LLMDecision(
                intent=LLMIntent.deliver_special_instructions,
                say=f"One more thing: {state.input_order.special_instructions}",
            )
        return LLMDecision(intent=LLMIntent.clarify_repeat, say="Could you repeat that?")


def make_orchestrator() -> CallOrchestrator:
    return CallOrchestrator(
        store=InMemoryCallStore(),
        logger=JsonlLogger(),
        twilio=FakeTwilioAdapter(),
        stt=FakeDeepgramSTT(),
        tts=FakeCartesiaTTS(),
        policy=ScriptedPolicy(),
    )


def make_request() -> CallCreateRequest:
    return CallCreateRequest.model_validate(
        {
            "store_phone_number": "+15125550199",
            "order": {
                "customer_name": "Jordan Smith",
                "phone_number": "5125550147",
                "delivery_address": "123 Main Street Apt 4B, Austin, TX 78745",
                "pizza": {
                    "size": "large",
                    "crust": "thin crust",
                    "toppings": ["pepperoni", "mushroom", "green pepper"],
                    "acceptable_topping_subs": ["onion"],
                    "no_go_toppings": ["olive"],
                },
                "side": {
                    "first_choice": "buffalo wings, 12 count",
                    "backup_options": ["garlic bread"],
                    "if_all_unavailable": "skip",
                },
                "drink": {
                    "first_choice": "2L Coke",
                    "alternatives": ["2L Diet Coke"],
                    "skip_if_over_budget": True,
                },
                "budget_max": 45.0,
                "special_instructions": "Please leave the order at the front door.",
            },
        }
    )


def test_transcript_happy_path() -> None:
    orchestrator = make_orchestrator()

    async def run() -> None:
        created = await orchestrator.create_call(make_request())
        for _ in range(7):
            await orchestrator.advance_ivr(created.call_id)
        await orchestrator.handle_transcript(created.call_id, "employee", "Hello, thanks for calling, what can I get you?", True, 0.99)
        await orchestrator.handle_transcript(created.call_id, "employee", "Yes, we have garlic bread. The side is 6.99.", True, 0.99)
        await orchestrator.handle_transcript(created.call_id, "employee", "The pizza is 18.50 and the drink is 3.49.", True, 0.99)
        await orchestrator.handle_transcript(created.call_id, "employee", "The total is 28.98.", True, 0.99)
        await orchestrator.handle_transcript(created.call_id, "employee", "Delivery should take about 35 minutes and your order number is 4412.", True, 0.99)
        status = await orchestrator.get_status(created.call_id)
        assert status.result_so_far.total == 28.98
        assert status.result_so_far.delivery_time == "35 minutes"
        assert status.result_so_far.order_number == "4412"

    asyncio.run(run())


def test_bot_detection() -> None:
    orchestrator = make_orchestrator()

    async def run() -> None:
        created = await orchestrator.create_call(make_request())
        for _ in range(7):
            await orchestrator.advance_ivr(created.call_id)
        decision = await orchestrator.handle_transcript(created.call_id, "employee", "Are you a robot? I can't continue this call.", True, 0.99)
        status = await orchestrator.get_status(created.call_id)
        assert decision is not None
        assert status.phase.value == "detected_as_bot"

    asyncio.run(run())


def _tiny_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_handle:
        wav_handle.setnchannels(1)
        wav_handle.setsampwidth(2)
        wav_handle.setframerate(8000)
        wav_handle.writeframes(b"\x00\x00" * 160)
    return buffer.getvalue()
