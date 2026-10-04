from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Sequence
from urllib.parse import urlencode

from app.ai.provider import ProviderError
from app.ai.prompts import PromptCatalog
from app.config import DEFAULT_GEMINI_MODELS


_MODEL_ALIASES = {
    "gemini 3.6 flash": "gemini-3.6-flash",
    "gemini 3.5 flash": "gemini-3.5-flash",
    "gemini 3.5 flash lite": "gemini-3.5-flash-lite",
}
_CANONICAL_MODELS = frozenset(DEFAULT_GEMINI_MODELS)
_OPERATION_CONFIG = {
    "GENERATE_QUESTIONS": "question_generation",
    "EVALUATE_ASSESSMENT": "answer_evaluation",
    "SUGGEST_FOLLOW_UP": "follow_up_question",
}
_SYSTEM_INSTRUCTION = (
    "You are a safe JSON-only assistant for the supervised interview tool."
)


def _normalize_model_name(value: str) -> str | None:
    normalized = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
    canonical = _MODEL_ALIASES.get(normalized)
    if canonical in _CANONICAL_MODELS:
        return canonical
    return None


def normalize_model_ids(models: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in (*DEFAULT_GEMINI_MODELS, *models):
        canonical = _normalize_model_name(value)
        if canonical is not None and canonical not in ordered:
            ordered.append(canonical)
    return tuple(ordered) or DEFAULT_GEMINI_MODELS


class GeminiAIProvider:
    """Standard-library Gemini REST adapter for Phase 2 structured operations."""

    def __init__(
        self,
        api_key: str | None,
        models: Sequence[str],
        timeout: float,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
        max_response_bytes: int = 5 * 1024 * 1024,
        prompt_root: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.models = normalize_model_ids(models)
        self.timeout = timeout
        self.opener = opener
        self.sleep = sleep
        self.logger = logger
        self.max_response_bytes = max_response_bytes
        self.prompts = PromptCatalog(
            prompt_root or Path(__file__).resolve().parents[2] / "prompts"
        )
        self._rotation_lock = Lock()
        self._next_model_index = 0

    def generate_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("GENERATE_QUESTIONS", payload)

    def evaluate_answers(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("EVALUATE_ASSESSMENT", payload)

    def suggest_follow_up(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("SUGGEST_FOLLOW_UP", payload)

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError(
                "Gemini API key is not configured",
                code="MISSING_API_KEY",
                retryable=False,
            )
        try:
            prompt_key = _OPERATION_CONFIG[operation]
        except KeyError as error:
            raise ProviderError(
                "Unsupported Gemini operation", code="AI_OPERATION_UNSUPPORTED"
            ) from error

        prompt = self.prompts.render(prompt_key, payload)
        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
                "generationConfig": {"temperature": 0.7},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        with self._rotation_lock:
            start = self._next_model_index % len(self.models)
            self._next_model_index = (start + 1) % len(self.models)
        ordered_models = self.models[start:] + self.models[:start]

        last_error: ProviderError | None = None
        for model in ordered_models:
            started = time.monotonic()
            try:
                result = self._request(model, body)
            except ProviderError as error:
                last_error = error
                self._log_attempt(operation, model, "FAILED", error.code, started)
                if not error.retryable:
                    raise
                continue
            self._log_attempt(operation, model, "SUCCESS", None, started)
            return result
        assert last_error is not None
        raise last_error

    def _request(self, model: str, body: bytes) -> dict[str, Any]:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?{urlencode({'key': self.api_key})}"
        )
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise ProviderError(
                    "Gemini rate limit", code="RATE_LIMITED", retryable=True, status=error.code
                ) from error
            if error.code == 404:
                raise ProviderError(
                    "Gemini model unavailable",
                    code="MODEL_UNAVAILABLE",
                    retryable=True,
                    status=error.code,
                ) from error
            raise ProviderError(
                f"Gemini provider HTTP error {error.code}",
                code="PROVIDER_ERROR",
                retryable=error.code >= 500,
                status=error.code,
            ) from error
        except socket.timeout as error:
            raise ProviderError("Gemini request timed out", code="TIMEOUT", retryable=True) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError(
                "Gemini provider could not be reached",
                code="NETWORK_ERROR",
                retryable=True,
            ) from error

        if len(raw) > self.max_response_bytes:
            raise ProviderError(
                "Gemini provider response exceeded the configured limit",
                code="AI_RESPONSE_TOO_LARGE",
                retryable=False,
            )
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError("Gemini response was not valid JSON", code="INVALID_JSON") from error
        text = self._extract_text(envelope)
        return self._parse_output(text)

    @staticmethod
    def _extract_text(envelope: Any) -> str:
        try:
            parts = envelope["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Gemini response did not contain generated content",
                code="INVALID_RESPONSE",
                retryable=False,
            ) from error
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text", ""), str)
        ).strip()
        if not text:
            raise ProviderError("Gemini returned an empty response", code="EMPTY_RESPONSE", retryable=True)
        return text

    @staticmethod
    def _parse_output(text: str) -> dict[str, Any]:
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProviderError(
                "Gemini response was not valid JSON", code="INVALID_JSON", retryable=False
            ) from error
        if not isinstance(value, dict):
            raise ProviderError(
                "Gemini response must be a JSON object",
                code="INVALID_RESPONSE",
                retryable=False,
            )
        return value

    def _log_attempt(
        self,
        operation: str,
        model: str,
        status: str,
        error_code: str | None,
        started: float,
    ) -> None:
        if self.logger is None:
            return
        self.logger.info(
            "gemini_attempt",
            extra={
                "safe_fields": {
                    "provider": "gemini",
                    "model": model,
                    "operation": operation,
                    "status": status,
                    "durationMs": round((time.monotonic() - started) * 1000),
                    "errorCode": error_code,
                }
            },
        )
