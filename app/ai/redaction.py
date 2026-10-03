from __future__ import annotations

import re
from typing import Any, Iterable


_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])", re.IGNORECASE)
_PHONE_CANDIDATE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_ADDRESS_LINE = re.compile(
    r"(?im)^(\s*(?:address|địa\s*chỉ)\s*[:\-])\s*.*$"
)


def sanitize_text(text: str, *, known_names: Iterable[str] = ()) -> str:
    """Remove common unnecessary PII before text crosses the AI boundary."""
    value = _EMAIL.sub("[REDACTED_EMAIL]", text)

    def replace_phone(match: re.Match[str]) -> str:
        candidate = match.group(0)
        return "[REDACTED_PHONE]" if sum(char.isdigit() for char in candidate) >= 9 else candidate

    value = _PHONE_CANDIDATE.sub(replace_phone, value)
    value = _ADDRESS_LINE.sub(lambda match: f"{match.group(1)} [REDACTED_ADDRESS]", value)
    for name in known_names:
        normalized = name.strip()
        if len(normalized) >= 3:
            value = re.sub(re.escape(normalized), "[REDACTED_NAME]", value, flags=re.IGNORECASE)
    return value


def sanitize_structure(value: Any, *, known_names: Iterable[str] = ()) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, known_names=known_names)
    if isinstance(value, list):
        return [sanitize_structure(item, known_names=known_names) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize_structure(item, known_names=known_names)
            for key, item in value.items()
        }
    return value
