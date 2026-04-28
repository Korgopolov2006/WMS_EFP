from __future__ import annotations

import re


_NON_ALNUM_RE = re.compile(r"[^0-9A-Z]+")


def normalize_part_number(value: str | None) -> str:
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    return _NON_ALNUM_RE.sub("", raw)
