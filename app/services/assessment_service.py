from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import Database
from app.domain.errors import (
    ResourceNotFound,
    RevisionConflict,
    StateConflict,
    ValidationError,
)
from app.repositories.assessments import AssessmentRepository
from app.repositories.audit import append_audit
from app.security import generate_candidate_token, verify_candidate_token


class AssessmentService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = AssessmentRepository(database)

    def prepare(self, case_id: str, question_set_id: str) -> dict[str, Any]:
        attempt_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            case = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (case_id,)
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] != "QUESTIONS_APPROVED":
                raise StateConflict("Case is not ready to prepare an assessment")
            existing = connection.execute(
                "SELECT id FROM assessment_attempts WHERE interview_case_id=?", (case_id,)
            ).fetchone()
            if existing is not None:
                raise StateConflict("Only one assessment attempt is allowed per case")
            question_set = connection.execute(
                """SELECT id FROM question_sets
                   WHERE id=? AND interview_case_id=? AND status='APPROVED'""",
                (question_set_id, case_id),
            ).fetchone()
            if question_set is None:
                raise StateConflict("Approved Question Set is required")
            connection.execute(
                """INSERT INTO assessment_attempts(id, interview_case_id, question_set_id)
                   VALUES (?, ?, ?)""",
                (attempt_id, case_id, question_set_id),
            )
            questions = connection.execute(
                "SELECT id FROM questions WHERE question_set_id=? ORDER BY display_order",
                (question_set_id,),
            ).fetchall()
            for question in questions:
                connection.execute(
                    """INSERT INTO answers(id, assessment_attempt_id, question_id)
                       VALUES (?, ?, ?)""",
                    (str(uuid.uuid4()), attempt_id, question["id"]),
                )
            connection.execute(
                """UPDATE interview_cases SET status='READY_FOR_ASSESSMENT',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="ASSESSMENT_CREATED",
                entity_type="ASSESSMENT_ATTEMPT",
                entity_id=attempt_id,
                metadata={"questionCount": len(questions)},
            )
        return self._summary(self.repository.get(attempt_id))

    def start(
        self,
        case_id: str,
        *,
        candidate_code_confirmed: bool,
        committee_authorized: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not candidate_code_confirmed or not committee_authorized:
            raise ValidationError("Candidate confirmation and Committee authorization are required")
        now = _utc(now)
        token, token_hash = generate_candidate_token()
        with self.database.transaction() as connection:
            attempt = connection.execute(
                """SELECT aa.*, qs.duration_seconds FROM assessment_attempts aa
                   JOIN question_sets qs ON qs.id=aa.question_set_id
                   WHERE aa.interview_case_id=?""",
                (case_id,),
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] != "READY_FOR_ASSESSMENT":
                raise StateConflict("Assessment cannot be started from its current state")
            expires = now + timedelta(seconds=attempt["duration_seconds"])
            connection.execute(
                """UPDATE assessment_attempts SET status='ASSESSMENT_IN_PROGRESS',
                   candidate_token_hash=?, started_at=?, expires_at=?,
                   updated_at=? WHERE id=?""",
                (token_hash, _iso(now), _iso(expires), _iso(now), attempt["id"]),
            )
            connection.execute(
                "UPDATE interview_cases SET status='ASSESSMENT_IN_PROGRESS', updated_at=? WHERE id=?",
                (_iso(now), case_id),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="ASSESSMENT_STARTED",
                entity_type="ASSESSMENT_ATTEMPT",
                entity_id=attempt["id"],
                metadata={"expiresAt": _iso(expires)},
            )
            append_audit(
                connection,
                actor_type="SYSTEM",
                action="CANDIDATE_MODE_ENTERED",
                entity_type="ASSESSMENT_ATTEMPT",
                entity_id=attempt["id"],
            )
        result = self._summary(self.repository.get(attempt["id"]))
        result["candidateToken"] = token
        return result

    def candidate_view(self, attempt_id: str, token: str) -> dict[str, Any]:
        attempt = self.repository.get(attempt_id)
        verify_candidate_token(token, attempt["candidate_token_hash"])
        return {
            "attemptId": attempt["id"],
            "status": attempt["status"],
            "expiresAt": attempt["expires_at"],
            "questions": self.repository.candidate_questions(attempt_id),
        }

    def save_answer(
        self,
        attempt_id: str,
        question_id: str,
        token: str,
        *,
        text: str,
        is_answered: bool,
        client_revision: int,
    ) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ValidationError("Answer text must be a string")
        normalized = text.strip()
        if is_answered and not normalized:
            raise ValidationError("Answered response cannot be blank")
        if not is_answered:
            normalized = ""
        with self.database.transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            verify_candidate_token(token, attempt["candidate_token_hash"])
            if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
                raise StateConflict("Answers are locked")
            answer = connection.execute(
                "SELECT * FROM answers WHERE assessment_attempt_id=? AND question_id=?",
                (attempt_id, question_id),
            ).fetchone()
            if answer is None:
                raise ResourceNotFound("Question is outside this attempt")
            expected_revision = int(answer["save_revision"]) + 1
            if client_revision != expected_revision:
                raise RevisionConflict("Answer revision is stale")
            saved_at = _iso(_utc(None))
            connection.execute(
                """UPDATE answers SET answer_text=?, is_answered=?, save_revision=?,
                   last_saved_at=?, updated_at=? WHERE id=?""",
                (normalized, int(is_answered), client_revision, saved_at, saved_at, answer["id"]),
            )
            append_audit(
                connection,
                actor_type="CANDIDATE",
                action="ANSWER_AUTOSAVED",
                entity_type="ANSWER",
                entity_id=answer["id"],
                metadata={"saveRevision": client_revision, "isAnswered": bool(is_answered)},
            )
        return {
            "questionId": question_id,
            "isAnswered": bool(is_answered),
            "saveRevision": client_revision,
            "lastSavedAt": saved_at,
        }

    def submit(
        self, attempt_id: str, token: str, *, reason: str = "MANUAL"
    ) -> dict[str, Any]:
        attempt = self.repository.get(attempt_id)
        verify_candidate_token(token, attempt["candidate_token_hash"])
        if attempt["status"] == "ASSESSMENT_SUBMITTED":
            return self._summary(attempt)
        if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
            raise StateConflict("Assessment cannot be submitted from its current state")
        return self._submit(attempt_id, reason=reason, actor_type="CANDIDATE")

    def expire_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = _utc(now)
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT id FROM assessment_attempts
                   WHERE status='ASSESSMENT_IN_PROGRESS' AND expires_at <= ?""",
                (_iso(now),),
            ).fetchall()
        return [self._submit(row["id"], reason="TIME_EXPIRED", actor_type="SYSTEM", now=now) for row in rows]

    def interrupt(self, attempt_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
                raise StateConflict("Only an active assessment can be interrupted")
            connection.execute(
                "UPDATE assessment_attempts SET status='ASSESSMENT_INTERRUPTED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (attempt_id,),
            )
            connection.execute(
                "UPDATE interview_cases SET status='ASSESSMENT_INTERRUPTED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (attempt["interview_case_id"],),
            )
            append_audit(
                connection, actor_type="SYSTEM", action="ASSESSMENT_INTERRUPTED",
                entity_type="ASSESSMENT_ATTEMPT", entity_id=attempt_id,
            )
        return self._summary(self.repository.get(attempt_id))

    def resume(
        self, attempt_id: str, token: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        now = _utc(now)
        with self.database.transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            verify_candidate_token(token, attempt["candidate_token_hash"])
            if attempt["status"] != "ASSESSMENT_INTERRUPTED":
                raise StateConflict("Assessment is not resumable")
            if attempt["expires_at"] <= _iso(now):
                raise StateConflict("Assessment has expired")
            connection.execute(
                "UPDATE assessment_attempts SET status='ASSESSMENT_IN_PROGRESS', updated_at=? WHERE id=?",
                (_iso(now), attempt_id),
            )
            connection.execute(
                "UPDATE interview_cases SET status='ASSESSMENT_IN_PROGRESS', updated_at=? WHERE id=?",
                (_iso(now), attempt["interview_case_id"]),
            )
            append_audit(
                connection, actor_type="COMMITTEE", action="ASSESSMENT_RESUMED",
                entity_type="ASSESSMENT_ATTEMPT", entity_id=attempt_id,
            )
        return self._summary(self.repository.get(attempt_id))

    def _submit(
        self,
        attempt_id: str,
        *,
        reason: str,
        actor_type: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if reason not in {"MANUAL", "AUTO_SUBMIT", "TIME_EXPIRED", "RECOVERY"}:
            raise ValidationError("Invalid submit reason")
        now = _utc(now)
        timestamp = _iso(now)
        with self.database.transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] == "ASSESSMENT_SUBMITTED":
                return self._summary(attempt)
            if attempt["status"] not in {"ASSESSMENT_IN_PROGRESS", "ASSESSMENT_INTERRUPTED"}:
                raise StateConflict("Assessment cannot be submitted")
            connection.execute(
                "UPDATE answers SET submitted_at=?, updated_at=? WHERE assessment_attempt_id=?",
                (timestamp, timestamp, attempt_id),
            )
            connection.execute(
                """UPDATE assessment_attempts SET status='ASSESSMENT_SUBMITTED',
                   submitted_at=?, submit_reason=?, allow_answer_edit=0, updated_at=? WHERE id=?""",
                (timestamp, reason, timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE interview_cases SET status='ASSESSMENT_SUBMITTED', updated_at=? WHERE id=?",
                (timestamp, attempt["interview_case_id"]),
            )
            action = "ASSESSMENT_AUTO_SUBMITTED" if reason != "MANUAL" else "ASSESSMENT_SUBMITTED"
            append_audit(
                connection, actor_type=actor_type, action=action,
                entity_type="ASSESSMENT_ATTEMPT", entity_id=attempt_id,
                metadata={"submitReason": reason},
            )
        return self._summary(self.repository.get(attempt_id))

    def _summary(self, attempt: sqlite3.Row) -> dict[str, Any]:
        with self.database.connection() as connection:
            counts = connection.execute(
                """SELECT COUNT(*) total, SUM(CASE WHEN is_answered=1 THEN 1 ELSE 0 END) answered
                   FROM answers WHERE assessment_attempt_id=?""",
                (attempt["id"],),
            ).fetchone()
        return {
            "id": attempt["id"],
            "interviewCaseId": attempt["interview_case_id"],
            "questionSetId": attempt["question_set_id"],
            "status": attempt["status"],
            "startedAt": attempt["started_at"],
            "expiresAt": attempt["expires_at"],
            "submittedAt": attempt["submitted_at"],
            "submitReason": attempt["submit_reason"],
            "answeredCount": int(counts["answered"] or 0),
            "totalCount": int(counts["total"] or 0),
        }


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValidationError("Datetime must include timezone")
    return current.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
