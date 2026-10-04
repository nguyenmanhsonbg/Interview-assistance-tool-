from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)


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
    ai_provider: str = "generic"
    ai_endpoint: str | None = None
    ai_model: str = "configured-model"
    ai_api_key: str | None = field(default=None, repr=False)
    ai_timeout_seconds: float = 30.0
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_models: tuple[str, ...] = DEFAULT_GEMINI_MODELS
    gemini_timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("APP_HOST must be 127.0.0.1")
        if not 0 <= self.port <= 65535:
            raise ValueError("APP_PORT must be between 0 and 65535")
        if self.ai_provider not in {"generic", "gemini"}:
            raise ValueError("AI_PROVIDER must be generic or gemini")
        if min(self.max_json_body, self.max_upload_body, self.max_ai_response) <= 0:
            raise ValueError("Body limits must be positive")
        if self.gemini_timeout_seconds <= 0:
            raise ValueError("GEMINI_CV_PARSE_TIMEOUT_MS must be positive")
        models = tuple(model.strip() for model in self.gemini_models if model.strip())
        object.__setattr__(self, "gemini_models", models or DEFAULT_GEMINI_MODELS)

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
            max_ai_response=int(
                os.environ.get("MAX_AI_RESPONSE", str(5 * 1024 * 1024))
            ),
            ai_provider=os.environ.get("AI_PROVIDER", "generic").strip().lower(),
            ai_endpoint=os.environ.get("AI_ENDPOINT") or None,
            ai_model=os.environ.get("AI_MODEL", "configured-model"),
            ai_api_key=os.environ.get("AI_API_KEY") or None,
            ai_timeout_seconds=float(os.environ.get("AI_TIMEOUT_SECONDS", "30")),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_models=tuple(
                model.strip()
                for model in os.environ.get(
                    "GEMINI_CV_PARSE_MODELS", ",".join(DEFAULT_GEMINI_MODELS)
                ).split(",")
                if model.strip()
            ),
            gemini_timeout_seconds=float(
                os.environ.get("GEMINI_CV_PARSE_TIMEOUT_MS", "45000")
            )
            / 1000.0,
        )

    @property
    def database_path(self) -> Path:
        return self.data_directory / "database" / "clawcv.db"

    def ensure_directories(self) -> None:
        for name in ("database", "documents", "exports", "backups", "logs", "config"):
            (self.data_directory / name).mkdir(parents=True, exist_ok=True)
