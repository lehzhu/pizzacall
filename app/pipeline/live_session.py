from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket

from app.agent.conversation import HumanConversationPlanner
from app.agent.interpreter import TranscriptInterpreter
from app.agent.ivr import IVRController
from app.agent.policy import PolicyEngine
from app.agent.result import ResultAssembler
from app.agent.session import SessionStore
from app.agent.state_machine import AgentStateMachine
from app.logging.events import EventLogger
from app.models import IVRSubphase, Outcome, PendingActionType, Phase, SessionState, StructuredItem
from app.pipeline.audio_gate import AudioOutputGate
from app.pipeline.cartesia_tts import CartesiaTTSService
from app.pipeline.deepgram_stt import DeepgramConfig, DeepgramSTTService
from app.pipeline.groq_llm import GroqLLMService
from app.twilio.outbound import CallOrchestrator


@dataclass(slots=True)
class TranscriptEvent:
    transcript: str
    is_final: bool
    confidence: float = 0.0


@dataclass(slots=True)
class LiveSessionContext:
    session: SessionState
    websocket: WebSocket
    transcript_queue: asyncio.Queue[TranscriptEvent] = field(default_factory=asyncio.Queue)
    receiver_task: asyncio.Task[None] | None = None
    keepalive_task: asyncio.Task[None] | None = None
    cartesia_connection: Any | None = None
    speaking_task: asyncio.Task[None] | None = None
    deepgram_ws: websockets.WebSocketClientProtocol | None = None
    playback_marks: set[str] = field(default_factory=set)


class LiveSessionManager:
    def __init__(
        self,
        *,
        store: SessionStore,
        state_machine: AgentStateMachine,
        ivr: IVRController,
        policy: PolicyEngine,
        interpreter: TranscriptInterpreter,
        result_assembler: ResultAssembler,
        planner: HumanConversationPlanner,
        audio_gate: AudioOutputGate,
        orchestrator: CallOrchestrator,
        deepgram: DeepgramSTTService,
        cartesia: CartesiaTTSService,
        groq: GroqLLMService,
        event_logger: EventLogger,
    ) -> None:
        self.store = store
        self.state_machine = state_machine
        self.ivr = ivr
        self.policy = policy
        self.interpreter = interpreter
        self.result_assembler = result_assembler
        self.planner = planner
        self.audio_gate = audio_gate
        self.orchestrator = orchestrator
        self.deepgram = deepgram
        self.cartesia = cartesia
        self.groq = groq
        self.event_logger = event_logger
        self.sessions: dict[str, LiveSessionContext] = {}

    async def connect(self, session: SessionState, websocket: WebSocket) -> LiveSessionContext:
        ctx = LiveSessionContext(session=session, websocket=websocket)
        self.sessions[session.session_id] = ctx
        await self.deepgram.connect(
            ctx,
            on_transcript=lambda event: ctx.transcript_queue.put_nowait(event),
            on_error=lambda message: self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="stt_error",
                payload={"error": message},
            ),
        )
        await self.cartesia.connect(ctx)
        ctx.receiver_task = asyncio.create_task(self._process_transcripts(ctx))
        return ctx

    async def disconnect(self, session_id: str) -> None:
        ctx = self.sessions.pop(session_id, None)
        if ctx is None:
            return
        if ctx.receiver_task:
            ctx.receiver_task.cancel()
        if ctx.speaking_task:
            ctx.speaking_task.cancel()
        await self.deepgram.close(ctx)
        await self.cartesia.close(ctx)

    async def ingest_audio(self, session_id: str, mulaw_audio: bytes) -> None:
        ctx = self.sessions[session_id]
        await self.deepgram.send_audio(ctx, mulaw_audio)

    async def interrupt_output(self, session_id: str) -> None:
        ctx = self.sessions.get(session_id)
        if ctx is None or ctx.session.stream_sid is None:
            return
        if ctx.speaking_task and not ctx.speaking_task.done():
            ctx.speaking_task.cancel()
        await ctx.websocket.send_text(json.dumps({"event": "clear", "streamSid": ctx.session.stream_sid}))
        self.event_logger.log(
            session_id=session_id,
            call_sid=ctx.session.call_sid,
            stream_sid=ctx.session.stream_sid,
            phase=ctx.session.phase,
            event_type="barge_in_stop",
            payload={},
        )

    async def speak(self, session_id: str, text: str) -> None:
        ctx = self.sessions[session_id]
        if not self.audio_gate.allows_output(ctx.session, employee_speaking=ctx.session.employee_speaking, hold_active=ctx.session.phase == Phase.hold):
            return
        if ctx.speaking_task and not ctx.speaking_task.done():
            await self.interrupt_output(session_id)

        async def runner() -> None:
            if ctx.session.stream_sid is None:
                return
            async for chunk in self.cartesia.synthesize(ctx, text):
                payload = {
                    "event": "media",
                    "streamSid": ctx.session.stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
                await ctx.websocket.send_text(json.dumps(payload))
            mark_name = f"tts-{ctx.session.pending_action.id if ctx.session.pending_action else 'human'}"
            await ctx.websocket.send_text(
                json.dumps({"event": "mark", "streamSid": ctx.session.stream_sid, "mark": {"name": mark_name}})
            )
            self.event_logger.log(
                session_id=ctx.session.session_id,
                call_sid=ctx.session.call_sid,
                stream_sid=ctx.session.stream_sid,
                phase=ctx.session.phase,
                event_type="tts_played",
                payload={"text": text},
            )
            if ctx.session.pending_action and ctx.session.pending_action.type == PendingActionType.say:
                ctx.session.pending_action = None

        ctx.speaking_task = asyncio.create_task(runner())
        await ctx.speaking_task

    async def _process_transcripts(self, ctx: LiveSessionContext) -> None:
        while True:
            event = await ctx.transcript_queue.get()
            session = ctx.session
            if not event.transcript.strip():
                continue
            event_type = "stt_final" if event.is_final else "stt_interim"
            self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type=event_type,
                payload={"transcript": event.transcript, "confidence": event.confidence},
            )
            if not event.is_final:
                session.employee_speaking = True
                if ctx.speaking_task and not ctx.speaking_task.done():
                    await self.interrupt_output(session.session_id)
                continue

            session.employee_speaking = False
            session.transcript_buffer.append(event.transcript)
            session.transcript_buffer = session.transcript_buffer[-6:]

            if session.phase == Phase.dialing:
                await self._handle_pre_human(ctx, event.transcript)
            elif session.phase == Phase.hold:
                await self._handle_hold(ctx)
            elif session.phase == Phase.human:
                await self._handle_human(ctx, event.transcript)

    async def _handle_pre_human(self, ctx: LiveSessionContext, transcript: str) -> None:
        session = ctx.session
        current = IVRSubphase(session.subphase)
        classification = self.ivr.classify_prompt(transcript, current)
        if classification is None:
            outcome = self.state_machine.on_uncertain_transcript(session, session.transcript_buffer, seconds_without_ivr=3.0)
            if outcome.reason != "insufficient evidence to leave current phase":
                self.event_logger.log(
                    session_id=session.session_id,
                    call_sid=session.call_sid,
                    stream_sid=session.stream_sid,
                    phase=outcome.phase,
                    event_type="phase_transition_inference",
                    payload={"reason": outcome.reason, "transcript": transcript},
                )
            return
        outcome = self.state_machine.apply_ivr_classification(session, classification)
        self.event_logger.log(
            session_id=session.session_id,
            call_sid=session.call_sid,
            stream_sid=session.stream_sid,
                phase=outcome.phase,
                event_type="ivr_prompt_classified",
                payload={"subphase": classification.subphase.value, "repeated": classification.repeated, "terminal_failure": classification.terminal_failure},
            )
        if session.phase == Phase.failed:
            return
        if outcome.phase == Phase.hold:
            return
        action = self.ivr.next_action(classification.subphase, session.order_request, confirm_matches=True)
        session.pending_action = action
        session.audio_output_enabled = action.type == PendingActionType.say
        if action.type == PendingActionType.dtmf:
            await self.orchestrator.redirect_call_for_dtmf(session, action.value or "")
            self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="dtmf_sent",
                payload={"digits": action.value, "reason": action.reason},
            )
        elif action.type == PendingActionType.say and action.value:
            self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="tts_planned",
                payload={"text": action.value, "reason": action.reason},
            )
            await self.speak(session.session_id, action.value)

    async def _handle_hold(self, ctx: LiveSessionContext) -> None:
        session = ctx.session
        outcome = self.state_machine.on_hold_transcript(session, session.transcript_buffer, seconds_without_ivr=3.0)
        self.event_logger.log(
            session_id=session.session_id,
            call_sid=session.call_sid,
            stream_sid=session.stream_sid,
            phase=outcome.phase,
            event_type="hold_human_classification",
            payload={"reason": outcome.reason, "confidence": session.human_confidence},
        )

    async def _handle_human(self, ctx: LiveSessionContext, transcript: str) -> None:
        session = ctx.session
        if self.state_machine.hold_detector.classify(transcript):
            session.phase = Phase.hold
            session.subphase = "waiting_for_human"
            session.audio_output_enabled = False
            self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="phase_transition_inference",
                payload={"reason": "employee_put_on_hold", "transcript": transcript},
            )
            return
        facts = self.interpreter.extract_facts(transcript)
        if facts.prices:
            session.partial_result["item_prices"] = facts.prices
            session.partial_result["item_prices_collected"] = True
        if facts.total is not None:
            session.partial_result["total"] = facts.total
            session.partial_result["total_collected"] = True
        if facts.delivery_time:
            session.partial_result["delivery_time"] = facts.delivery_time
            session.partial_result["delivery_time_collected"] = True
        if facts.order_number:
            session.partial_result["order_number"] = facts.order_number
            session.partial_result["order_number_collected"] = True
        step = self.planner.next_step(session, transcript)
        if step.note == "bot_suspected":
            result = self.result_assembler.assemble(
                outcome=Outcome.detected_as_bot,
                pizza=None,
                special_instructions_delivered=session.partial_result.get("special_instructions_delivered", False),
                notes=["Employee suspected a bot"],
            )
            await self.store.set_final_result(session.session_id, result)
            await self.speak(session.session_id, step.text or "Sorry about that.")
            return
        if step.text:
            spoken = await self.groq.generate_human_reply(
                transcript=transcript,
                draft=step.text,
                missing_fields=[],
            )
            self.event_logger.log(
                session_id=session.session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="tts_planned",
                payload={"text": spoken},
            )
            await self.speak(session.session_id, spoken)
        if step.done and session.partial_result.get("total_collected") and session.partial_result.get("delivery_time_collected") and session.partial_result.get("order_number_collected"):
            pizza_price = session.partial_result.get("item_prices", [0.0])[0] if session.partial_result.get("item_prices") else 0.0
            result = self.result_assembler.assemble(
                outcome=Outcome.completed,
                pizza=StructuredItem(description=session.order_request.pizza.description or "pizza", price=pizza_price),
                side=None,
                drink=None,
                total=session.partial_result.get("total"),
                delivery_time=session.partial_result.get("delivery_time"),
                order_number=session.partial_result.get("order_number"),
                special_instructions_delivered=session.partial_result.get("special_instructions_delivered", True),
            )
            validation = self.policy.validate_completion(result)
            if validation.allowed:
                await self.store.set_final_result(session.session_id, result)
