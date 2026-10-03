from __future__ import annotations

import os

from app.ai.http_provider import HttpAIProvider
from app.application import create_application
from app.config import AppConfig
from app.infrastructure.single_instance import SingleInstanceError, SingleInstanceLock
from app.server import run


def main() -> None:
    config = AppConfig.from_environment()
    lock = SingleInstanceLock(config.data_directory / "config" / "clawcv.lock")
    try:
        lock.acquire()
    except SingleInstanceError as error:
        raise SystemExit(str(error)) from error
    application = None
    try:
        provider = None
        if config.ai_endpoint:
            provider = HttpAIProvider(
                config.ai_endpoint,
                api_key=config.ai_api_key,
                model=config.ai_model,
                timeout=config.ai_timeout_seconds,
                max_retry=0,
                max_response_bytes=config.max_ai_response,
            )
        application = create_application(
            config,
            provider=provider,
            initial_pin=os.environ.get("CLAWCV_COMMITTEE_PIN") or None,
        )
        application.start()
        run(config, router=application.router, security=application.security)
    except OSError as error:
        raise SystemExit(
            f"ClawCV could not bind {config.host}:{config.port}: {error}"
        ) from error
    finally:
        if application is not None:
            application.stop()
        lock.release()


if __name__ == "__main__":
    main()
