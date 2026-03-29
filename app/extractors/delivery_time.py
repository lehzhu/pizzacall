from __future__ import annotations

import re


TIME_RE = re.compile(r"\b(?:about\s+)?(\d{1,2}(?:\s*(?:to|-)\s*\d{1,2})?)\s+minutes?\b", re.IGNORECASE)


def extract_delivery_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    return f"{match.group(1).replace('-', ' to ')} minutes"

