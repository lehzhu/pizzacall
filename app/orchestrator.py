from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from app.config import get_settings
from app.errors import ProviderRequestError
from app.extractors.address import extract_zip_code
from app.extractors.delivery_time import extract_delivery_time
from app.extractors.money import extract_exact_money, extract_money_values
from app.extractors.order_number import extract_order_number
from app.logger import JsonlLogger
from app.models import (
    CallCreateRequest,
    CallCreateResponse,
    CallStatus,
    CallStatusResponse,
    LLMIntent,
    ItemStatus,
    LLMDecision,
    Phase,
    SessionState,
    TranscriptTurn,
)
from app.policy.deterministic_rules import (
    classify_human_turn,
    detect_bot_accusation,
    is_over_budget,
    next_drink_candidate,
    next_side_candidate,
    normalize,
    render_pizza_description,
    should_decline_extra,
    should_skip_drink,
)
from app.policy.llm_policy import LLMPolicy
from app.result_builder import build_final_result, build_snapshot
from app.speech.cartesia_tts import CartesiaTTS
from app.speech.deepgram_stt import DeepgramStreamingSTT
from app.state_machine import can_complete, set_phase
from app.store import InMemoryCallStore
from app.telephony.twilio_adapter import TwilioAdapter


class CallOrchestrator:
    def __init__(
        self,
        store: InMemoryCallStore,
        logger: JsonlLogger,
        twilio: TwilioAdapter,
        stt: DeepgramStreamingSTT,
        tts: CartesiaTTS,
        policy: LLMPolicy,
    ) -> None:
        self.store = store
        self.logger = logger
        self.twilio = twilio
        self.stt = stt
        self.tts = tts
        self.policy = policy
        self.settings = get_settings()

    async def create_call(self, request: CallCreateRequest) -> CallCreateResponse:
        zip_code = extract_zip_code(request.order.delivery_address)
        session = SessionState.from_order(request.store_phone_number, request.order, zip_code)
        session.phase = Phase.dialing
        session.status = CallStatus.queued
        await self.store.create(session)
        await self.ensure_ivr_audio(session)
        session.twilio_call_sid = await self.twilio.start_outbound_call(session)
        await self.store.update(session)
        self.logger.log_state(session, "call_created", {"store_phone_number": session.store_phone_number})
        return CallCreateResponse(call_id=session.call_id, status=CallStatus.queued)

    async def ensure_ivr_audio(self, session: SessionState) -> None:
        artifact_dir = self.settings.artifact_dir / session.call_id
        assets = {
            "name.wav": session.input_order.customer_name,
            "zip.wav": " ".join(session.zip_code),
            "yes.wav": "yes",
            "no.wav": "no",
        }
        for filename, text in assets.items():
            path = artifact_dir / filename
            await self.tts.synthesize_to_file(text, path)
            session.ivr_audio_files[filename] = str(path)
        await self.store.update(session)

    async def get_status(self, call_id: str) -> CallStatusResponse:
        session = await self.store.get(call_id)
        return CallStatusResponse(
            call_id=call_id,
            status=session.status,
            phase=session.phase,
            result_so_far=build_snapshot(session),
        )

    async def get_result(self, call_id: str):
        session = await self.store.get(call_id)
        if session.outcome is None:
            raise RuntimeError("call result is not available until the call reaches a terminal outcome")
        return build_final_result(session)

    async def artifact_path(self, call_id: str, filename: str) -> Path:
        session = await self.store.get(call_id)
        path = session.ivr_audio_files.get(filename)
        if not path:
            raise FileNotFoundError(filename)
        return Path(path)

    async def advance_ivr(self, call_id: str) -> SessionState:
        session = await self.store.get(call_id)
        transition_order = {
            Phase.dialing: Phase.ivr_menu,
            Phase.ivr_menu: Phase.ivr_name,
            Phase.ivr_name: Phase.ivr_callback,
            Phase.ivr_callback: Phase.ivr_zip,
            Phase.ivr_zip: Phase.ivr_confirm,
            Phase.ivr_confirm: Phase.transfer_wait,
            Phase.transfer_wait: Phase.hold,
        }
        next_phase = transition_order.get(session.phase, session.phase)
        set_phase(session, next_phase)
        await self.store.update(session)
        self.logger.log_state(session, "phase_transition")
        return session

    async def handle_twilio_status(self, call_id: str, payload: dict[str, Any]) -> None:
        session = await self.store.get(call_id)
        session.twilio_call_sid = payload.get("CallSid", session.twilio_call_sid)
        status = payload.get("CallStatus", "")
        self.logger.log(session.call_id, "twilio_status", payload)
        if status in {"busy", "no-answer", "failed", "canceled"}:
            set_phase(session, Phase.failed)
            session.notes.append(f"Twilio status {status}.")
        elif status == "completed" and session.outcome is None:
            set_phase(session, Phase.failed)
            session.notes.append("Call completed before a terminal ordering outcome was reached.")
        await self.store.update(session)
        if session.outcome is not None:
            self.logger.write_result(session)

    async def handle_transcript(self, call_id: str, speaker: str, text: str, is_final: bool = True, confidence: float | None = None) -> LLMDecision | None:
        session = await self.store.get(call_id)
        turn = TranscriptTurn(speaker=speaker, text=text, is_final=is_final, confidence=confidence)
        session.transcript.append(turn)
        self.logger.log(
            session.call_id,
            "transcript_turn",
            {"speaker": speaker, "text": text, "is_final": is_final, "confidence": confidence},
        )
        if speaker != "employee" or not is_final:
            await self.store.update(session)
            return None
        self._apply_transcript_updates(session, text)
        if detect_bot_accusation(text):
            session.detected_bot_risk = True
            session.notes.append("Employee indicated bot discomfort or refused service.")
            set_phase(session, Phase.detected_as_bot)
            await self.store.update(session)
            self.logger.write_result(session)
            return LLMDecision(intent=LLMIntent.clarify_repeat, say="Sorry about that. I'll disconnect now.")
        if session.phase in {Phase.transfer_wait, Phase.hold} and classify_human_turn(text):
            set_phase(session, Phase.human_greeting)
        if should_decline_extra(text):
            decision = LLMDecision(intent=LLMIntent.reject_extra, say="No thank you.")
            await self.store.update(session)
            return decision
        try:
            decision = await self.policy.decide(session, text)
        except ProviderRequestError as exc:
            session.notes.append(str(exc))
            set_phase(session, Phase.failed)
            await self.store.update(session)
            self.logger.write_result(session)
            raise
        self._apply_decision_effects(session, decision)
        if is_over_budget(session):
            session.notes.append("Pizza and required items exceeded pre-tax budget maximum.")
            set_phase(session, Phase.over_budget)
        elif can_complete(session):
            set_phase(session, Phase.completed)
        await self.store.update(session)
        if session.outcome is not None:
            self.logger.write_result(session)
        return decision

    def _apply_transcript_updates(self, session: SessionState, text: str) -> None:
        lowered = normalize(text)
        if "no pizza" in lowered or "we don't have pizza" in lowered:
            session.notes.append("Store reported no viable pizza available.")
            set_phase(session, Phase.nothing_available)
            return
        if "mushroom" in lowered and ("out" in lowered or "don't have" in lowered):
            replacement = None
            for candidate in session.input_order.pizza.acceptable_topping_subs:
                if normalize(candidate) in lowered:
                    replacement = candidate
                    break
            if replacement:
                session.pizza.substitutions["mushroom"] = replacement
        money = extract_money_values(text)
        exact = extract_exact_money(text)
        if "total" in lowered and exact is not None:
            session.pricing.total_known = exact
        elif "subtotal" in lowered and exact is not None:
            session.pricing.subtotal_known = exact
        elif "pizza" in lowered and exact is not None:
            session.pizza.price = exact
        elif "side" in lowered or any(normalize(option) in lowered for option in session.input_order.side.backup_options + [session.side.original]):
            if exact is not None:
                session.side.price = exact
        elif "drink" in lowered or any(normalize(option) in lowered for option in session.input_order.drink.alternatives + [session.drink.requested]):
            if exact is not None:
                session.drink.price = exact
        elif len(money) == 1 and exact is not None:
            if session.pizza.price is None:
                session.pizza.price = exact
            elif session.side.status == ItemStatus.confirmed and session.side.price is None:
                session.side.price = exact
            elif session.drink.status == ItemStatus.confirmed and session.drink.price is None:
                session.drink.price = exact
            elif session.pricing.total_known is None:
                session.pricing.total_known = exact
        delivery_time = extract_delivery_time(text)
        if delivery_time:
            session.delivery_time = delivery_time
        order_number = extract_order_number(text)
        if order_number:
            session.order_number = order_number
        self._apply_availability_updates(session, lowered)

    def _apply_availability_updates(self, session: SessionState, lowered: str) -> None:
        positive = any(token in lowered for token in ("yes", "sure", "okay", "can do", "have that", "got it"))
        negative = any(token in lowered for token in ("don't have", "do not have", "out of", "unavailable", "sold out", "no"))
        if negative and session.side.status == ItemStatus.pending:
            attempted = next_side_candidate(session)
            if attempted:
                session.conversation.side_attempts.append(attempted)
                next_candidate = next_side_candidate(session)
                if next_candidate is None:
                    session.side.status = ItemStatus.skipped
                    session.notes.append("Side skipped because all listed options were unavailable.")
        elif positive and session.side.status == ItemStatus.pending and session.conversation.side_attempts:
            confirmed = session.conversation.side_attempts[-1]
            session.side.requested = confirmed
            session.side.confirmed_description = confirmed
            session.side.status = ItemStatus.confirmed
        if negative and session.drink.status == ItemStatus.pending:
            attempted = next_drink_candidate(session)
            if attempted:
                session.conversation.drink_attempts.append(attempted)
                next_candidate = next_drink_candidate(session)
                if next_candidate is None or session.input_order.drink.skip_if_over_budget:
                    session.drink.status = ItemStatus.skipped
                    session.notes.append("Drink skipped conservatively to avoid exceeding budget.")
        elif positive and session.drink.status == ItemStatus.pending and session.conversation.drink_attempts:
            confirmed = session.conversation.drink_attempts[-1]
            session.drink.requested = confirmed
            session.drink.confirmed_description = confirmed
            session.drink.status = ItemStatus.confirmed

    def _apply_decision_effects(self, session: SessionState, decision: LLMDecision) -> None:
        if decision.intent.value == "greet_and_start_order":
            session.conversation.greeted = True
            set_phase(session, Phase.human_ordering)
            return
        if decision.intent.value == "provide_name":
            session.conversation.provided_name = True
            return
        if decision.intent.value == "provide_phone":
            session.conversation.provided_phone = True
            return
        if decision.intent.value == "provide_address":
            session.conversation.provided_address = True
            return
        if decision.intent.value == "order_pizza":
            session.conversation.pizza_requested = True
            session.pizza.confirmed_description = render_pizza_description(session)
            session.pizza.status = ItemStatus.confirmed
            return
        if decision.intent.value == "ask_side_availability":
            candidate = next_side_candidate(session)
            if candidate:
                session.conversation.side_attempts.append(candidate)
            return
        if decision.intent.value == "ask_drink_availability":
            candidate = next_drink_candidate(session)
            if candidate:
                session.conversation.drink_attempts.append(candidate)
            return
        if decision.intent.value == "ask_total":
            session.conversation.asked_total = True
            set_phase(session, Phase.human_confirming)
            return
        if decision.intent.value == "ask_delivery_time":
            session.conversation.asked_delivery_time = True
            return
        if decision.intent.value == "ask_order_number":
            session.conversation.asked_order_number = True
            return
        if decision.intent.value == "deliver_special_instructions":
            session.special_instructions_delivered = True
            session.conversation.special_instructions_delivered = True
            set_phase(session, Phase.closing)
            return
        if decision.intent.value == "thank_and_close":
            session.conversation.thanked = True
            if can_complete(session):
                set_phase(session, Phase.completed)

    async def stream_media(self, call_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        session = await self.store.get(call_id)
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        stream_sid: str | None = None

        async def on_transcript(transcript: str, is_final: bool, confidence: float | None) -> None:
            decision = await self.handle_transcript(call_id, "employee", transcript, is_final=is_final, confidence=confidence)
            if not decision or not decision.say or not stream_sid:
                return
            frames = await self.tts.synthesize_mulaw_frames(decision.say)
            self.logger.log(call_id, "tts_utterance", {"text": decision.say, "intent": decision.intent.value})
            for frame in frames:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(frame).decode("ascii")},
                        }
                    )
                )
                await asyncio.sleep(0.02)

        stt_task = asyncio.create_task(self.stt.consume_queue(audio_queue, on_transcript))
        try:
            while True:
                message = await websocket.receive_text()
                payload = json.loads(message)
                event = payload.get("event")
                if event == "start":
                    stream_sid = payload.get("start", {}).get("streamSid")
                    session.twilio_stream_sid = stream_sid
                    if session.phase == Phase.transfer_wait:
                        set_phase(session, Phase.hold)
                    await self.store.update(session)
                    self.logger.log(call_id, "media_start", payload.get("start", {}))
                elif event == "media":
                    media = payload.get("media", {})
                    raw = media.get("payload")
                    if raw:
                        await audio_queue.put(base64.b64decode(raw))
                elif event == "stop":
                    self.logger.log(call_id, "media_stop", payload.get("stop", {}))
                    break
        finally:
            await audio_queue.put(None)
            try:
                await stt_task
            except ProviderRequestError:
                session = await self.store.get(call_id)
                session.notes.append("Streaming speech pipeline failed.")
                set_phase(session, Phase.failed)
                await self.store.update(session)
                self.logger.write_result(session)
            await websocket.close()
