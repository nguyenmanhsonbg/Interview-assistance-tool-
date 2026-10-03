from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from app.ai.provider import ProviderError


class HttpAIProvider:
    """Provider-neutral JSON-over-HTTP adapter using the Standard Library."""

    def __init__(self, endpoint: str, *, api_key: str | None, model: str, timeout: float = 30, max_retry: int = 1, max_response_bytes: int = 2 * 1024 * 1024, opener: Callable[..., Any] = urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retry = max_retry
        self.max_response_bytes = max_response_bytes
        self.opener = opener
        self.sleep = sleep

    def generate_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("GENERATE_QUESTIONS", payload)

    def evaluate_answers(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("EVALUATE_ASSESSMENT", payload)

    def suggest_follow_up(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("SUGGEST_FOLLOW_UP", payload)

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"operation": operation, "model": self.model, "input": payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        for attempt in range(self.max_retry + 1):
            request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise ProviderError("AI provider response exceeded the configured limit", code="AI_RESPONSE_TOO_LARGE")
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ProviderError("AI provider returned invalid JSON", code="AI_INVALID_JSON") from error
                if not isinstance(decoded, dict):
                    raise ProviderError("AI provider response must be a JSON object", code="AI_INVALID_RESPONSE")
                return decoded
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                provider_error = ProviderError(f"AI provider HTTP error {error.code}", code="AI_HTTP_ERROR", retryable=retryable, status=error.code)
            except (urllib.error.URLError, TimeoutError, socket.timeout):
                provider_error = ProviderError("AI provider could not be reached", code="AI_CONNECTION_ERROR", retryable=True)
            if not provider_error.retryable or attempt >= self.max_retry:
                raise provider_error
            self.sleep(min(2**attempt, 5))
        raise ProviderError("AI provider request failed")
