from __future__ import annotations

import logging

from app.ai.gemini_provider import GeminiAIProvider, normalize_model_ids
from app.ai.http_provider import HttpAIProvider
from app.ai.provider import AIProvider
from app.config import AppConfig


def build_ai_provider(
    config: AppConfig, *, logger: logging.Logger | None = None
) -> AIProvider | None:
    if config.ai_provider == "gemini":
        return GeminiAIProvider(
            api_key=config.gemini_api_key,
            models=config.gemini_models,
            timeout=config.gemini_timeout_seconds,
            max_response_bytes=config.max_ai_response,
            logger=logger,
        )
    if config.ai_endpoint:
        return HttpAIProvider(
            config.ai_endpoint,
            api_key=config.ai_api_key,
            model=config.ai_model,
            timeout=config.ai_timeout_seconds,
            max_retry=0,
            max_response_bytes=config.max_ai_response,
        )
    return None


def configured_ai_metadata(config: AppConfig) -> tuple[str | None, str | None]:
    if config.ai_provider == "gemini":
        return "gemini", normalize_model_ids(config.gemini_models)[0]
    if config.ai_endpoint:
        return "generic", config.ai_model
    return None, None
