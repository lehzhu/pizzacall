from __future__ import annotations

import re
from dataclasses import dataclass


PRICE_RE = re.compile(r"(?:\$|price\s*(?:is|for)?\s*)(\d+(?:\.\d{1,2})?)", re.IGNORECASE)
TOTAL_RE = re.compile(r"(?:your\s+)?total\s*(?:is|comes to|will be)?\s*\$?\s*(\d+(?:\.\d{1,2})?)", re.IGNORECASE)
ORDER_NUMBER_RE = re.compile(r"(?:order|confirmation)\s*(?:number|#)?\s*(?:is|:)?\s*([A-Z0-9-]+)", re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2}\s*(?:to|-)\s*\d{1,2}\s*minutes|\d{1,2}\s*minutes)", re.IGNORECASE)


@dataclass(slots=True)
class ExtractedFacts:
    prices: list[float]
    total: float | None
    delivery_time: str | None
    order_number: str | None
    needs_llm_help: bool = False


class TranscriptInterpreter:
    def extract_facts(self, transcript: str) -> ExtractedFacts:
        prices = [float(match) for match in PRICE_RE.findall(transcript)]
        total_match = TOTAL_RE.search(transcript)
        total = float(total_match.group(1)) if total_match else None
        delivery_time_match = TIME_RE.search(transcript)
        order_number_match = ORDER_NUMBER_RE.search(transcript)
        needs_llm_help = not delivery_time_match and "ready" in transcript.lower()
        return ExtractedFacts(
            prices=prices,
            total=total,
            delivery_time=delivery_time_match.group(1) if delivery_time_match else None,
            order_number=order_number_match.group(1) if order_number_match else None,
            needs_llm_help=needs_llm_help,
        )
