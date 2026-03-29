from __future__ import annotations

from dataclasses import dataclass

from cartesia import AsyncCartesia


@dataclass(slots=True)
class CartesiaConfig:
    voice_id: str = "calm-phone-agent"
    speaking_rate: float = 0.92
    websocket_preconnect: bool = True
    model_id: str = "sonic-3"


class CartesiaTTSService:
    def __init__(self, api_key: str, config: CartesiaConfig | None = None) -> None:
        self.api_key = api_key
        self.config = config or CartesiaConfig()
        self.client = AsyncCartesia(api_key=api_key) if api_key else None

    async def connect(self, ctx) -> None:
        if self.client is None:
            return
        ctx.cartesia_connection = await self.client.tts.websocket_connect().enter()

    async def synthesize(self, ctx, text: str):
        if ctx.cartesia_connection is None:
            return
        ws_context = ctx.cartesia_connection.context(
            model_id=self.config.model_id,
            voice={"mode": "id", "id": self.config.voice_id},
            output_format={"container": "raw", "encoding": "pcm_mulaw", "sample_rate": 8000},
            generation_config={"speed": self.config.speaking_rate},
        )
        await ws_context.push(text)
        await ws_context.no_more_inputs()
        async for response in ws_context.receive():
            if getattr(response, "type", None) == "chunk" and getattr(response, "audio", None):
                yield response.audio

    async def close(self, ctx) -> None:
        if ctx.cartesia_connection is not None:
            await ctx.cartesia_connection.close()
