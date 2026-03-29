from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HumanDetectionDecision:
    is_human: bool
    confidence: float
    reasons: list[str]


class HumanDetector:
    def __init__(self, human_patterns: list[str], blocking_patterns: list[str], grace_seconds: float = 2.0) -> None:
        self._human_patterns = [pattern.lower() for pattern in human_patterns]
        self._blocking_patterns = [pattern.lower() for pattern in blocking_patterns]
        self._grace_seconds = grace_seconds

    @property
    def grace_seconds(self) -> float:
        return self._grace_seconds

    def classify(self, transcript_window: list[str], seconds_without_ivr: float) -> HumanDetectionDecision:
        recent = [utterance.lower() for utterance in transcript_window[-3:] if utterance.strip()]
        joined = " ".join(recent)
        latest = recent[-1] if recent else ""
        reasons: list[str] = []
        human_hits = sum(1 for pattern in self._human_patterns if pattern in joined)
        latest_human_hits = sum(1 for pattern in self._human_patterns if pattern in latest)
        latest_blocking_hits = sum(1 for pattern in self._blocking_patterns if pattern in latest)
        if latest_blocking_hits and not latest_human_hits:
            reasons.append("blocking_ivr_pattern")
            return HumanDetectionDecision(False, 0.0, reasons)
        if latest_human_hits >= 1 and seconds_without_ivr >= self._grace_seconds:
            reasons.append("latest_human_signal_with_grace_window")
            return HumanDetectionDecision(True, 0.8, reasons)
        if human_hits >= 2:
            reasons.append("two_human_signals")
            return HumanDetectionDecision(True, 0.9, reasons)
        if human_hits >= 1 and seconds_without_ivr >= self._grace_seconds:
            reasons.append("single_signal_with_grace_window")
            return HumanDetectionDecision(True, 0.75, reasons)
        if human_hits:
            reasons.append("waiting_for_more_human_evidence")
            return HumanDetectionDecision(False, 0.4, reasons)
        reasons.append("no_human_signal")
        return HumanDetectionDecision(False, 0.0, reasons)
