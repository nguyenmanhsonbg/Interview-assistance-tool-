from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """A sanitized AI-provider failure safe to persist and return to callers."""

    def __init__(self, message: str, *, code: str = "AI_PROVIDER_ERROR", retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status = status


class AIProvider(Protocol):
    def generate_questions(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def evaluate_answers(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def suggest_follow_up(self, payload: dict[str, Any]) -> dict[str, Any]: ...
