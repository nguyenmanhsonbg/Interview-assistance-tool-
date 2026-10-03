from __future__ import annotations

from app.config import AppConfig
from app.server import run


def main() -> None:
    config = AppConfig.from_environment()
    try:
        run(config)
    except OSError as error:
        raise SystemExit(
            f"ClawCV could not bind {config.host}:{config.port}: {error}"
        ) from error


if __name__ == "__main__":
    main()
