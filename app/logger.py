from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models import SessionState
from app.result_builder import build_final_result


class JsonlLogger:
    def __init__(self) -> None:
        settings = get_settings()
        self.log_dir = settings.log_dir

    def _path(self, call_id: str) -> Path:
        return self.log_dir / f"{call_id}.jsonl"

    def log(self, call_id: str, event_type: str, payload: dict[str, Any]) -> None:
        line = {"event_type": event_type, **payload}
        print(json.dumps(line, default=str), flush=True)
        with self._path(call_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, default=str) + "\n")

    def log_state(self, state: SessionState, event_type: str, extra: dict[str, Any] | None = None) -> None:
        payload = {"call_id": state.call_id, "phase": state.phase.value, "status": state.status.value}
        if extra:
            payload.update(extra)
        self.log(state.call_id, event_type, payload)

    def write_result(self, state: SessionState) -> None:
        path = self.log_dir / f"{state.call_id}.result.json"
        path.write_text(build_final_result(state).model_dump_json(indent=2), encoding="utf-8")
