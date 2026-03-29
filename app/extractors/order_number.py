from __future__ import annotations

import re


ORDER_RE = re.compile(
    r"\b(?:order|confirmation|ticket)\s*(?:number|no\.?)?\s*(?:is\s*)?([A-Za-z0-9-]{3,})\b",
    re.IGNORECASE,
)


def extract_order_number(text: str) -> str | None:
    match = ORDER_RE.search(text)
    if match:
        return match.group(1)
    return None

