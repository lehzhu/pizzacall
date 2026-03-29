from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import json
import websockets
from typing import Any


@dataclass(slots=True)
class DeepgramConfig:
    model: str = "nova-2-phonecall"
    language: str = "en-US"
    encoding: str = "mulaw"
    sample_rate: int = 8000
    interim_results: bool = True
    endpointing: bool = True
    utterance_end_ms: int = 1000


class DeepgramSTTService:
    _non_transcript_events = {"Results", "Metadata", "UtteranceEnd", "SpeechStarted"}

    def __init__(self, api_key: str, config: DeepgramConfig | None = None) -> None:
        self.api_key = api_key
        self.config = config or DeepgramConfig()

    async def connect(self, ctx, on_transcript, on_error) -> None:
        if not self.api_key:
            on_error("Deepgram API key missing")
            return
        query = urlencode(
            {
                "model": self.config.model,
                "language": self.config.language,
                "encoding": self.config.encoding,
                "sample_rate": str(self.config.sample_rate),
                "interim_results": str(self.config.interim_results).lower(),
                "endpointing": str(self.config.endpointing).lower(),
                "utterance_end_ms": str(self.config.utterance_end_ms),
                "vad_events": "true",
            }
        )
        ctx.deepgram_ws = await websockets.connect(
            f"wss://api.deepgram.com/v1/listen?{query}",
            additional_headers={"Authorization": f"Token {self.api_key}"},
        )
        on_error("Deepgram websocket connected")

        async def receiver() -> None:
            assert ctx.deepgram_ws is not None
            try:
                async for message in ctx.deepgram_ws:
                    data = json.loads(message)
                    events = data if isinstance(data, list) else [data]
                    for item in events:
                        if not isinstance(item, dict):
                            on_error(f"Deepgram unexpected payload: {type(item).__name__}")
                            continue
                        transcript, confidence = self._extract_transcript(item)
                        if transcript:
                            on_transcript(
                                __import__("app.pipeline.live_session", fromlist=["TranscriptEvent"]).TranscriptEvent(
                                    transcript=transcript,
                                    is_final=bool(item.get("is_final")),
                                    confidence=confidence,
                                )
                            )
                        elif item.get("type") in self._non_transcript_events:
                            continue
                        elif item.get("type"):
                            on_error(f"Deepgram event: {item.get('type')}")
                        else:
                            on_error(f"Deepgram payload without transcript: {item}")
                        if item.get("type") == "Error":
                            on_error(str(item))
            except Exception as exc:
                on_error(f"Deepgram receiver failed: {exc}")

        ctx.keepalive_task = __import__("asyncio").create_task(receiver())

    async def send_audio(self, ctx, audio: bytes) -> None:
        if ctx.deepgram_ws is None:
            return
        try:
            await ctx.deepgram_ws.send(audio)
        except Exception as exc:
            raise RuntimeError(f"Failed to send audio to Deepgram: {exc}") from exc

    async def close(self, ctx) -> None:
        if ctx.deepgram_ws is not None:
            await ctx.deepgram_ws.close()
        if ctx.keepalive_task:
            ctx.keepalive_task.cancel()

    def _extract_transcript(self, payload: dict[str, Any]) -> tuple[str, float]:
        channels = payload.get("channel")
        if isinstance(channels, dict):
            return self._extract_from_channel_dict(channels)
        if isinstance(channels, list):
            for channel in channels:
                if isinstance(channel, dict):
                    transcript, confidence = self._extract_from_channel_dict(channel)
                    if transcript:
                        return transcript, confidence

        results = payload.get("results")
        if isinstance(results, dict):
            channels = results.get("channels")
            if isinstance(channels, list):
                for channel in channels:
                    if isinstance(channel, dict):
                        transcript, confidence = self._extract_from_channel_dict(channel)
                        if transcript:
                            return transcript, confidence

        alternatives = payload.get("alternatives")
        if isinstance(alternatives, list):
            for alternative in alternatives:
                if isinstance(alternative, dict):
                    transcript = str(alternative.get("transcript", "")).strip()
                    if transcript:
                        return transcript, float(alternative.get("confidence", 0.0))

        return "", 0.0

    def _extract_from_channel_dict(self, channel: dict[str, Any]) -> tuple[str, float]:
        alternatives = channel.get("alternatives")
        if not isinstance(alternatives, list):
            return "", 0.0
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            transcript = str(alternative.get("transcript", "")).strip()
            if transcript:
                return transcript, float(alternative.get("confidence", 0.0))
        return "", 0.0
