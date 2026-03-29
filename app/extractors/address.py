from __future__ import annotations

import re


ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def extract_zip_code(address: str) -> str:
    matches = ZIP_RE.findall(address)
    if not matches:
        raise ValueError("delivery_address must contain a 5-digit ZIP code")
    return matches[-1]

