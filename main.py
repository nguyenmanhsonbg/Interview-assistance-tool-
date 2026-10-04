from __future__ import annotations

import os

from app.ai.factory import build_ai_provider
from app.application import create_application
from app.config import AppConfig
from app.infrastructure.single_instance import SingleInstanceError, SingleInstanceLock
from app.server import run
from app.services.audit_service import configure_safe_logger


def main() -> None:
    config = AppConfig.from_environment()
    lock = SingleInstanceLock(config.data_directory / "config" / "clawcv.lock")
    try:
        lock.acquire()
    except SingleInstanceError as error:
        raise SystemExit(str(error)) from error
    application = None
    safe_logger = None
    try:
        safe_logger = configure_safe_logger(config.data_directory / "logs" / "app.log")
        provider = build_ai_provider(config, logger=safe_logger)
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
        if safe_logger is not None:
            for handler in list(safe_logger.handlers):
                handler.close()
                safe_logger.removeHandler(handler)
        lock.release()


if __name__ == "__main__":
    main()
