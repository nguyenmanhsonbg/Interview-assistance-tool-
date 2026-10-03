from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.database import Database
from app.domain.errors import ValidationError
from app.repositories.audit import append_audit


AUDIT_ACTIONS = frozenset(
    {
        "CASE_CREATED", "CASE_UPDATED", "CASE_CANCELLED", "CASE_DELETED",
        "DOCUMENT_IMPORTED", "DOCUMENT_TEXT_CONFIRMED", "DOCUMENT_VERSION_CREATED",
        "QUESTION_SET_GENERATION_REQUESTED", "QUESTION_SET_GENERATED",
        "QUESTION_SET_EDITED", "QUESTION_SET_APPROVED", "ASSESSMENT_CREATED",
        "ASSESSMENT_STARTED", "ASSESSMENT_RESUMED", "ANSWER_AUTOSAVED",
        "ASSESSMENT_SUBMITTED", "ASSESSMENT_AUTO_SUBMITTED", "ASSESSMENT_EXPIRED",
        "CANDIDATE_MODE_ENTERED", "COMMITTEE_MODE_ENTERED", "CANDIDATE_NO_SHOW",
        "AI_TASK_CREATED", "AI_TASK_RETRIED", "AI_TASK_COMPLETED", "AI_TASK_FAILED",
        "AI_RESULT_RERUN", "INTERVIEW_BRIEF_CREATED", "MANUAL_FALLBACK_USED",
        "LIVE_INTERVIEW_STARTED", "LIVE_QUESTION_RECORDED", "LIVE_QUESTION_SKIPPED",
        "CONFLICT_FLAGGED", "LIVE_INTERVIEW_COMPLETED", "EVALUATION_DRAFTED",
        "EVALUATION_FINALIZED", "EVALUATION_REVISED", "SETTINGS_UPDATED",
        "BACKUP_CREATED", "EXPORT_CREATED", "CASE_DELETE_REQUESTED",
        "CASE_DELETE_COMPLETED", "CASE_DELETE_FAILED",
    }
)

_SENSITIVE_KEYS = {
    "apikey", "api_key", "pin", "password", "startuptoken", "startup_token",
    "committeesession", "committee_session", "candidatetoken", "candidate_token",
    "answertext", "answer_text", "livenotes", "live_notes", "cv", "jd",
    "payload", "rawpayload", "protectedvalue", "protected_value",
}


def redact(value: Any, *, key: str = "") -> Any:
    normalized = key.replace("-", "").casefold()
    if normalized in {item.replace("_", "") for item in _SENSITIVE_KEYS}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): redact(child, key=str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return "[REDACTED]"


class AuditService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, *, actor_type: str, action: str, entity_type: str, entity_id: str, actor_ref_id: str | None = None, request_id: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        if action not in AUDIT_ACTIONS:
            raise ValidationError("Unknown audit action")
        with self.database.transaction() as connection:
            return append_audit(
                connection, actor_type=actor_type, actor_ref_id=actor_ref_id,
                action=action, entity_type=entity_type, entity_id=entity_id,
                request_id=request_id, metadata=redact(metadata or {}),
            )


class _SafeJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": str(record.getMessage()),
        }
        payload.update(redact(getattr(record, "safe_fields", {})))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_safe_logger(path: Path, *, max_bytes: int = 1_000_000, backup_count: int = 3) -> logging.Logger:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"clawcv.{path.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing in list(logger.handlers):
        existing.close()
        logger.removeHandler(existing)
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    handler.setFormatter(_SafeJSONFormatter())
    logger.addHandler(handler)
    return logger
