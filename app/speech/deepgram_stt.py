from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import websockets

from app.config import get_settings
from app.errors import ProviderConfigurationError, ProviderRequestError


TranscriptCallback = Callable[[str, bool, float | None], Awaitable[None]]


class DeepgramStreamingSTT:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def consume_queue(self, audio_queue: "asyncio.Queue[bytes | None]", on_transcript: TranscriptCallback) -> None:
        if not self.settings.deepgram_api_key:
            raise ProviderConfigurationError("DEEPGRAM_API_KEY is required for streaming STT.")

        url = (
            "wss://api.deepgram.com/v1/listen"
            "?encoding=mulaw&sample_rate=8000&channels=1&punctuate=true&interim_results=true&endpointing=300"
        )
        try:
            async with websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {self.settings.deepgram_api_key}"},
                max_size=None,
            ) as websocket:
                send_task = asyncio.create_task(self._sender(websocket, audio_queue))
                receive_task = asyncio.create_task(self._receiver(websocket, on_transcript))
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except Exception as exc:
            raise ProviderRequestError(f"Deepgram streaming failed: {exc}") from exc

    async def _sender(self, websocket: websockets.ClientConnection, audio_queue: "asyncio.Queue[bytes | None]") -> None:
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                await websocket.send(json.dumps({"type": "CloseStream"}))
                return
            await websocket.send(chunk)

    async def _receiver(self, websocket: websockets.ClientConnection, on_transcript: TranscriptCallback) -> None:
        async for raw in websocket:
            if not isinstance(raw, str):
                continue
            payload = json.loads(raw)
            transcript = (
                payload.get("channel", {})
                .get("alternatives", [{}])[0]
                .get("transcript", "")
                .strip()
            )
            if not transcript:
                continue
            confidence = (
                payload.get("channel", {})
                .get("alternatives", [{}])[0]
                .get("confidence")
            )
            await on_transcript(transcript, bool(payload.get("is_final")), confidence)
