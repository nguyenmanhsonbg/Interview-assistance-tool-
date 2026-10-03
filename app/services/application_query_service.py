from __future__ import annotations

from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound


class ApplicationQueryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def case_overview(self, case_data: dict[str, Any]) -> dict[str, Any]:
        case_id = case_data["id"]
        with self.database.connection() as connection:
            current = connection.execute(
                """SELECT
                    (SELECT id FROM interview_briefs WHERE interview_case_id=? AND is_current=1) current_brief_id,
                    (SELECT id FROM question_sets WHERE interview_case_id=? ORDER BY version_no DESC LIMIT 1) question_set_id,
                    (SELECT id FROM assessment_attempts WHERE interview_case_id=?) attempt_id,
                    (SELECT id FROM evaluations WHERE interview_case_id=? AND is_current=1) evaluation_id""",
                (case_id, case_id, case_id, case_id),
            ).fetchone()
        return {
            **case_data,
            "currentBriefId": current["current_brief_id"],
            "questionSetId": current["question_set_id"],
            "assessmentAttemptId": current["attempt_id"],
            "evaluationId": current["evaluation_id"],
        }

    def settings(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT key, value_type, value_text, is_sensitive, updated_at FROM app_settings ORDER BY key"
            ).fetchall()
        return [
            {
                "key": row["key"], "valueType": row["value_type"],
                "value": None if row["is_sensitive"] else row["value_text"],
                "isSensitive": bool(row["is_sensitive"]), "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def update_settings(self, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from app.domain.errors import ValidationError
        from app.repositories.audit import append_audit
        import json

        allowed = {
            "assessment.default_duration_seconds": "INTEGER",
            "assessment.auto_submit_on_expiry": "BOOLEAN",
            "retention.mode": "STRING",
        }
        with self.database.transaction() as connection:
            for change in changes:
                key = change.get("key")
                if key not in allowed:
                    raise ValidationError(f"Setting is not editable: {key}")
                value_type = allowed[key]
                value = change.get("value")
                if value_type == "INTEGER" and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ValidationError(f"{key} must be an integer")
                if value_type == "BOOLEAN" and not isinstance(value, bool):
                    raise ValidationError(f"{key} must be a boolean")
                serialized = json.dumps(value) if value_type == "BOOLEAN" else str(value)
                connection.execute(
                    """INSERT INTO app_settings(key, value_type, value_text, is_sensitive)
                       VALUES (?, ?, ?, 0) ON CONFLICT(key) DO UPDATE SET
                       value_type=excluded.value_type, value_text=excluded.value_text,
                       protected_value=NULL, is_sensitive=0,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                    (key, value_type, serialized),
                )
            append_audit(connection, actor_type="COMMITTEE", action="SETTINGS_UPDATED",
                entity_type="APP_SETTINGS", entity_id="application",
                metadata={"keys": [change.get("key") for change in changes]})
        return self.settings()
