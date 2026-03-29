from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse

from app.agent.conversation import HumanConversationPlanner
from app.agent.hold import HoldDetector
from app.agent.human_detection import HumanDetector
from app.agent.interpreter import TranscriptInterpreter
from app.agent.ivr import IVRController
from app.agent.policy import PolicyEngine
from app.agent.result import ResultAssembler
from app.agent.session import SessionStore
from app.agent.state_machine import AgentStateMachine
from app.config import Settings, get_settings
from app.logging.events import EventLogger
from app.logging.jsonl import JsonlWriter
from app.models import NormalizedOrderRequest, OrderRequest, RestaurantProfile
from app.pipeline.audio_gate import AudioOutputGate
from app.pipeline.cartesia_tts import CartesiaConfig, CartesiaTTSService
from app.pipeline.deepgram_stt import DeepgramConfig, DeepgramSTTService
from app.pipeline.groq_llm import GroqLLMService
from app.pipeline.live_session import LiveSessionManager
from app.twilio.callbacks import TwilioCallbackHandler
from app.twilio.media_ws import MediaWebSocketHandler
from app.twilio.outbound import CallOrchestrator
from app.twilio.twiml import build_dtmf_redirect_twiml, build_stream_twiml


def load_restaurant_profile(settings: Settings) -> RestaurantProfile:
    if settings.restaurant_profile_path.exists():
        return RestaurantProfile.model_validate_json(settings.restaurant_profile_path.read_text(encoding="utf-8"))
    return RestaurantProfile(
        prompt_patterns={
            "menu": ["press 1", "for delivery press 1", "press one for delivery", "press one for english", "for english press 1"],
            "name": ["say your name", "name for the order", "who is this order for", "please say your name"],
            "callback": ["phone number", "callback number", "telephone number", "call back number", "enter your phone number"],
            "zip": ["zip code", "postal code", "postcode", "please say your zip code"],
            "confirm": ["is that correct", "if this is correct", "if correct say yes", "if this is right say yes"],
            "transfer": ["please hold", "transfer you", "connecting you", "one moment while i connect you"],
        },
        failure_patterns=["goodbye", "unable to process", "try again later"],
        hold_patterns=["please continue to hold", "please stay on hold", "your call is important", "music", "brief hold", "one moment while"],
        human_patterns=["what can i get started", "thanks for calling", "name for the order", "can i put you on hold", "how may i take your order", "how can i help you", "this is manager", "welcome to"],
        bot_suspected_patterns=["press 1", "press 2", "for delivery", "for pickup", "main menu", "option"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    event_logger = EventLogger(JsonlWriter(settings.log_dir / "events.jsonl"))
    profile = load_restaurant_profile(settings)
    ivr = IVRController(profile)
    hold_detector = HoldDetector(profile.hold_patterns)
    human_detector = HumanDetector(profile.human_patterns, profile.bot_suspected_patterns, profile.human_grace_seconds)
    state_machine = AgentStateMachine(ivr, hold_detector, human_detector)
    store = SessionStore(event_logger, settings.results_dir)
    policy = PolicyEngine()
    planner = HumanConversationPlanner(policy)
    app.state.settings = settings
    app.state.profile = profile
    app.state.event_logger = event_logger
    app.state.store = store
    app.state.policy = policy
    app.state.interpreter = TranscriptInterpreter()
    app.state.result_assembler = ResultAssembler()
    app.state.orchestrator = CallOrchestrator(settings, event_logger)
    app.state.twilio_callbacks = TwilioCallbackHandler(store, event_logger, settings, app.state.result_assembler)
    app.state.audio_gate = AudioOutputGate(state_machine)
    app.state.groq = GroqLLMService(settings.groq_api_key)
    app.state.deepgram = DeepgramSTTService(
        settings.deepgram_api_key,
        DeepgramConfig(model=settings.deepgram_model, language=settings.deepgram_language),
    )
    app.state.cartesia = CartesiaTTSService(
        settings.cartesia_api_key,
        CartesiaConfig(voice_id=settings.cartesia_voice_id, model_id=settings.cartesia_model_id),
    )
    app.state.live_sessions = LiveSessionManager(
        store=store,
        state_machine=state_machine,
        ivr=ivr,
        policy=policy,
        interpreter=app.state.interpreter,
        result_assembler=app.state.result_assembler,
        planner=planner,
        audio_gate=app.state.audio_gate,
        orchestrator=app.state.orchestrator,
        deepgram=app.state.deepgram,
        cartesia=app.state.cartesia,
        groq=app.state.groq,
        event_logger=event_logger,
    )
    app.state.media_handler = MediaWebSocketHandler(store, state_machine, event_logger, app.state.live_sessions)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Pizza Order Agent", lifespan=lifespan)

    @app.get("/healthz")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/calls/outbound")
    async def create_outbound_call(request: Request, payload: OrderRequest) -> JSONResponse:
        settings: Settings = request.app.state.settings
        store: SessionStore = request.app.state.store
        orchestrator: CallOrchestrator = request.app.state.orchestrator
        policy: PolicyEngine = request.app.state.policy
        normalized = NormalizedOrderRequest.from_order_request(payload)
        session = await store.create(normalized)
        session.policy_snapshot = policy.snapshot(normalized)
        call = orchestrator.create_outbound_call(normalized)
        session = await store.bind_call_sid(session.session_id, call.call_sid)
        return JSONResponse(
            {
                "session_id": session.session_id,
                "call_sid": session.call_sid,
                "phase": session.phase,
                "status": call.status,
                "public_base_url": settings.public_base_url,
            }
        )

    @app.post("/twilio/voice", response_class=PlainTextResponse)
    async def voice_webhook(request: Request, session_id: str) -> PlainTextResponse:
        store: SessionStore = request.app.state.store
        event_logger: EventLogger = request.app.state.event_logger
        callback_handler: TwilioCallbackHandler = request.app.state.twilio_callbacks
        form = dict(await request.form())
        signature = request.headers.get("X-Twilio-Signature")
        if not callback_handler.verify_signature(url=str(request.url), params=form, signature=signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        session = await store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session_id")
        websocket_url = request.app.state.settings.public_base_url.replace("http", "ws", 1) + f"/twilio/media/{session_id}"
        twiml = build_stream_twiml(websocket_url=websocket_url)
        event_logger.log(
            session_id=session.session_id,
            call_sid=session.call_sid,
            phase=session.phase,
            event_type="voice_webhook_hit",
            payload={"websocket_url": websocket_url},
        )
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/status")
    async def twilio_status(request: Request) -> JSONResponse:
        payload = dict(await request.form())
        signature = request.headers.get("X-Twilio-Signature")
        callback_handler: TwilioCallbackHandler = request.app.state.twilio_callbacks
        if not callback_handler.verify_signature(url=str(request.url), params=payload, signature=signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        response = await callback_handler.handle_status(payload)
        return JSONResponse(response)

    @app.post("/twilio/action/{session_id}", response_class=PlainTextResponse)
    async def twilio_action(request: Request, session_id: str, digits: str) -> PlainTextResponse:
        callback_handler: TwilioCallbackHandler = request.app.state.twilio_callbacks
        form = dict(await request.form())
        signature = request.headers.get("X-Twilio-Signature")
        if not callback_handler.verify_signature(url=str(request.url), params=form, signature=signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        session = await request.app.state.store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session_id")
        redirect_url = f"{request.app.state.settings.public_base_url}/twilio/voice?session_id={session_id}"
        twiml = build_dtmf_redirect_twiml(digits=digits, redirect_url=redirect_url)
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.get("/sessions/{session_id}")
    async def get_session(request: Request, session_id: str) -> JSONResponse:
        store: SessionStore = request.app.state.store
        session = await store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session_id")
        return JSONResponse(json.loads(session.model_dump_json()))

    @app.websocket("/twilio/media/{session_id}")
    async def media_websocket(websocket: WebSocket, session_id: str) -> None:
        await app.state.media_handler.handle(websocket, session_id)

    return app
