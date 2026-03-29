from __future__ import annotations

import re
from dataclasses import dataclass


EXACT_MONEY_RE = re.compile(r"(?<!\d)(?:\$)?(\d{1,3}(?:\.\d{1,2})?)(?!\d)")
APPROXIMATE_MARKERS = ("about", "around", "roughly", "approximately", "approx")


@dataclass(frozen=True)
class MoneyMatch:
    value: float
    approximate: bool
    span_text: str


def extract_money_values(text: str) -> list[MoneyMatch]:
    lowered = text.lower()
    approximate = any(marker in lowered for marker in APPROXIMATE_MARKERS)
    matches: list[MoneyMatch] = []
    for raw in EXACT_MONEY_RE.findall(text):
        if "-" in raw:
            continue
        matches.append(MoneyMatch(value=round(float(raw), 2), approximate=approximate, span_text=raw))
    return matches


def extract_exact_money(text: str) -> float | None:
    for match in extract_money_values(text):
        if not match.approximate:
            return match.value
    return None

