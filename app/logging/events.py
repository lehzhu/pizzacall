from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.logging.jsonl import JsonlWriter
from app.models import Phase, utc_now


@dataclass(slots=True)
class EventLogger:
    writer: JsonlWriter

    def log(
        self,
        *,
        session_id: str,
        phase: Phase | str,
        event_type: str,
        payload: dict[str, Any],
        call_sid: str | None = None,
        stream_sid: str | None = None,
    ) -> None:
        self.writer.append(
            {
                "ts": utc_now().isoformat(),
                "session_id": session_id,
                "call_sid": call_sid,
                "stream_sid": stream_sid,
                "phase": phase.value if isinstance(phase, Phase) else phase,
                "event_type": event_type,
                "payload": payload,
            }
        )
