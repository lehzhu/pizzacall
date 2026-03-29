from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class ResponseWindow:
    grace_ms: int = 1400
    _last_endpoint_at: float | None = None

    def mark_endpoint(self) -> None:
        self._last_endpoint_at = monotonic()

    def ready(self) -> bool:
        if self._last_endpoint_at is None:
            return False
        return (monotonic() - self._last_endpoint_at) * 1000 >= self.grace_ms

