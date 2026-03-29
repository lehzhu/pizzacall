from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.logger import JsonlLogger
from app.models import CallCreateRequest
from app.orchestrator import CallOrchestrator
from app.policy.llm_policy import LLMPolicy
from app.speech.cartesia_tts import CartesiaTTS
from app.speech.deepgram_stt import DeepgramStreamingSTT
from app.store import InMemoryCallStore
from app.telephony.twilio_adapter import TwilioAdapter


store = InMemoryCallStore()
logger = JsonlLogger()
orchestrator = CallOrchestrator(
    store=store,
    logger=logger,
    twilio=TwilioAdapter(),
    stt=DeepgramStreamingSTT(),
    tts=CartesiaTTS(),
    policy=LLMPolicy(),
)

app = FastAPI(title="Pizza Order Voice Agent MVP")


@app.post("/calls")
async def create_call(request: CallCreateRequest):
    response = await orchestrator.create_call(request)
    return JSONResponse(response.model_dump(mode="json"))


@app.get("/calls/{call_id}")
async def get_call(call_id: str):
    try:
        response = await orchestrator.get_status(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(response.model_dump(mode="json"))


@app.get("/calls/{call_id}/result")
async def get_call_result(call_id: str):
    try:
        result = await orchestrator.get_result(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result.model_dump(mode="json"))


@app.post("/twilio/voice")
async def twilio_voice(call_id: str):
    try:
        session = await orchestrator.advance_ivr(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(orchestrator.twilio.build_voice_response(session), media_type="application/xml")


@app.post("/twilio/status")
async def twilio_status(call_id: str, request: Request):
    form = dict(await request.form())
    try:
        await orchestrator.handle_twilio_status(call_id, form)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.websocket("/ws/media/{call_id}")
async def media_stream(websocket: WebSocket, call_id: str):
    try:
        await orchestrator.stream_media(call_id, websocket)
    except KeyError:
        await websocket.close(code=4404)


@app.get("/artifacts/{call_id}/{filename}")
async def artifact(call_id: str, filename: str):
    try:
        path = await orchestrator.artifact_path(call_id, filename)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type = "audio/wav" if Path(path).suffix == ".wav" else "application/octet-stream"
    return FileResponse(path, media_type=media_type)
