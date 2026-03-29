from __future__ import annotations


class HoldDetector:
    def __init__(self, hold_patterns: list[str]) -> None:
        self._hold_patterns = [pattern.lower() for pattern in hold_patterns]

    def classify(self, transcript: str) -> bool:
        lowered = transcript.lower()
        return any(pattern in lowered for pattern in self._hold_patterns)
