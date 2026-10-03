from __future__ import annotations

import json
import uuid
from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.domain.rules import require_text
from app.repositories.audit import append_audit
from app.repositories.evaluations import EvaluationRepository


class InterviewBriefService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = EvaluationRepository(database)

    def current(self, case_id: str) -> dict[str, Any]:
        brief = self.repository.current_brief(case_id)
        if brief is None:
            raise ResourceNotFound("Interview Brief not found")
        return brief

    def create_manual(self, case_id: str, attempt_id: str, brief: dict[str, Any], member_id: str) -> dict[str, Any]:
        validated = _validate_brief(brief, strict_live_questions=False)
        return self._create(
            case_id, attempt_id, validated, source_kind="MANUAL",
            ai_result_id=None, member_id=member_id,
            allowed_states={"AI_ANALYSIS_FAILED", "INTERVIEW_BRIEF_READY"},
        )

    def materialize_ai(self, task_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT ar.*, at.status task_status, at.task_type
                   FROM ai_results ar JOIN ai_tasks at ON at.id=ar.ai_task_id
                   WHERE at.id=?""", (task_id,),
            ).fetchone()
        if row is None or row["task_status"] != "COMPLETED" or row["task_type"] != "EVALUATE_ASSESSMENT":
            raise StateConflict("Completed answer evaluation result is required")
        existing = self.repository.brief_by_ai_result(row["id"])
        if existing is not None:
            return existing
        payload = json.loads(row["payload_json"])
        brief = _validate_brief(payload.get("interviewBrief"), strict_live_questions=True)
        return self._create(
            row["interview_case_id"], row["assessment_attempt_id"], brief,
            source_kind="AI", ai_result_id=row["id"], member_id=None,
            allowed_states={"AI_ANALYZING", "INTERVIEW_BRIEF_READY"},
        )

    def _create(self, case_id: str, attempt_id: str, brief: dict[str, Any], *, source_kind: str, ai_result_id: str | None, member_id: str | None, allowed_states: set[str]) -> dict[str, Any]:
        brief_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            case = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] not in allowed_states:
                raise StateConflict("Case is not ready for an Interview Brief")
            attempt = connection.execute("SELECT 1 FROM assessment_attempts WHERE id=? AND interview_case_id=?", (attempt_id, case_id)).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if member_id is not None:
                member = connection.execute("SELECT 1 FROM interview_case_committee_members WHERE id=? AND interview_case_id=?", (member_id, case_id)).fetchone()
                if member is None:
                    raise ValidationError("Committee member does not belong to this case")
            self.repository.insert_brief(connection, brief_id=brief_id, case_id=case_id,
                attempt_id=attempt_id, ai_result_id=ai_result_id, source_kind=source_kind,
                brief=brief, member_id=member_id)
            connection.execute("UPDATE interview_cases SET status='INTERVIEW_BRIEF_READY', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (case_id,))
            append_audit(connection, actor_type="COMMITTEE" if source_kind == "MANUAL" else "SYSTEM",
                actor_ref_id=member_id, action="INTERVIEW_BRIEF_CREATED",
                entity_type="INTERVIEW_BRIEF", entity_id=brief_id,
                metadata={"sourceKind": source_kind})
            if source_kind == "MANUAL":
                append_audit(connection, actor_type="COMMITTEE", actor_ref_id=member_id,
                    action="MANUAL_FALLBACK_USED", entity_type="INTERVIEW_BRIEF", entity_id=brief_id)
        return self.repository.get_brief(brief_id)


def _validate_brief(brief: Any, *, strict_live_questions: bool) -> dict[str, Any]:
    if not isinstance(brief, dict):
        raise ValidationError("brief must be an object")
    required = ("summary", "strengths", "gaps", "conflicts", "competencyMatrix", "requiredLiveQuestions", "additionalLiveQuestions", "limitations")
    if any(field not in brief for field in required):
        raise ValidationError("brief is missing required fields")
    require_text(brief["summary"], "summary")
    for field in required[1:]:
        if not isinstance(brief[field], list):
            raise ValidationError(f"{field} must be an array")
    required_questions = brief["requiredLiveQuestions"]
    if strict_live_questions and len(required_questions) != 3:
        raise ValidationError("AI brief must contain exactly 3 required live questions")
    if len(required_questions) > 3 or len(brief["additionalLiveQuestions"]) > 2:
        raise ValidationError("Brief exceeds live question limits")
    if any(not isinstance(item, str) or not item.strip() for item in required_questions + brief["additionalLiveQuestions"]):
        raise ValidationError("Live questions must be non-empty text")
    return brief
