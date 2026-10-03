from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ClawCV"
    return Path.home() / "AppData" / "Local" / "ClawCV"


@dataclass(frozen=True, slots=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    data_directory: Path = _default_data_directory()
    web_directory: Path = Path(__file__).resolve().parents[1] / "web"
    max_json_body: int = 1024 * 1024
    max_upload_body: int = 10 * 1024 * 1024
    max_ai_response: int = 5 * 1024 * 1024
    app_version: str = "0.1.0"

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("APP_HOST must be 127.0.0.1")
        if not 0 <= self.port <= 65535:
            raise ValueError("APP_PORT must be between 0 and 65535")
        if min(self.max_json_body, self.max_upload_body, self.max_ai_response) <= 0:
            raise ValueError("Body limits must be positive")

    @classmethod
    def from_environment(cls) -> "AppConfig":
        return cls(
            host=os.environ.get("APP_HOST", "127.0.0.1"),
            port=int(os.environ.get("APP_PORT", "8787")),
            data_directory=Path(
                os.environ.get("DATA_DIRECTORY", str(_default_data_directory()))
            ),
            max_json_body=int(os.environ.get("MAX_JSON_BODY", str(1024 * 1024))),
            max_upload_body=int(
                os.environ.get("MAX_UPLOAD_BODY", str(10 * 1024 * 1024))
            ),
        )

    @property
    def database_path(self) -> Path:
        return self.data_directory / "database" / "clawcv.db"

    def ensure_directories(self) -> None:
        for name in ("database", "documents", "exports", "backups", "logs", "config"):
            (self.data_directory / name).mkdir(parents=True, exist_ok=True)
