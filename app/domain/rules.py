from __future__ import annotations

from collections.abc import Collection

from app.domain.errors import StateConflict, ValidationError


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required")
    return value.strip()


def require_transition(current: str, allowed: Collection[str], target: str) -> None:
    if current not in allowed:
        raise StateConflict(f"Cannot transition from {current} to {target}")
