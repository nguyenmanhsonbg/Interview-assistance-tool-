from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.database import Database
from app.domain.errors import (
    ResourceNotFound,
    RevisionConflict,
    StateConflict,
    Unauthenticated,
    ValidationError,
)
from app.repositories.assessments import AssessmentRepository
from app.repositories.audit import append_audit
from app.security import generate_candidate_token, verify_candidate_token


class AssessmentService:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.repository = AssessmentRepository(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

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

    def get_for_case(self, case_id: str) -> dict[str, Any]:
        attempt = self.repository.by_case(case_id)
        if attempt is None:
            raise ResourceNotFound("Assessment attempt not found")
        return self._summary(attempt)

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
        now = self._now(now)
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

    def candidate_view(
        self, attempt_id: str, token: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        attempt = self._candidate_attempt(attempt_id, token, now=now)
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
        attempt = self._candidate_attempt(attempt_id, token)
        if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
            raise StateConflict("Answers are locked")
        if not isinstance(text, str):
            raise ValidationError("Answer text must be a string")
        normalized = text.strip()
        if is_answered and not normalized:
            raise ValidationError("Answered response cannot be blank")
        if not is_answered:
            normalized = ""
        terminal_due = False
        with self.database.transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            verify_candidate_token(token, attempt["candidate_token_hash"])
            if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
                raise StateConflict("Answers are locked")
            current = self._now()
            if attempt["expires_at"] and attempt["expires_at"] <= _iso(current):
                self._finish_due_in_transaction(connection, attempt, current)
                terminal_due = True
            else:
                answer = connection.execute(
                    "SELECT * FROM answers WHERE assessment_attempt_id=? AND question_id=?",
                    (attempt_id, question_id),
                ).fetchone()
                if answer is None:
                    raise ResourceNotFound("Question is outside this attempt")
                expected_revision = int(answer["save_revision"]) + 1
                if client_revision != expected_revision:
                    raise RevisionConflict("Answer revision is stale")
                saved_at = _iso(current)
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
        if terminal_due:
            raise Unauthenticated("Candidate session is invalid or expired")
        return {
            "questionId": question_id,
            "isAnswered": bool(is_answered),
            "saveRevision": client_revision,
            "lastSavedAt": saved_at,
        }

    def submit(
        self,
        attempt_id: str,
        token: str,
        *,
        reason: str = "MANUAL",
        expected_revisions: dict[str, int] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        request_fingerprint = _submission_fingerprint(expected_revisions)
        key_hash = _idempotency_hash(idempotency_key)
        return self._submit(
            attempt_id,
            reason=reason,
            actor_type="CANDIDATE",
            candidate_token=token,
            expected_revisions=expected_revisions,
            idempotency_key_hash=key_hash,
            request_fingerprint=request_fingerprint,
        )

    def expire_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = self._now(now)
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT aa.id, aa.status, ic.auto_submit_on_expiry
                   FROM assessment_attempts aa
                   JOIN interview_cases ic ON ic.id=aa.interview_case_id
                   WHERE aa.status IN ('ASSESSMENT_IN_PROGRESS','ASSESSMENT_INTERRUPTED')
                     AND aa.expires_at <= ?""",
                (_iso(now),),
            ).fetchall()
        results = []
        for row in rows:
            if row["status"] == "ASSESSMENT_IN_PROGRESS" and row["auto_submit_on_expiry"]:
                results.append(
                    self._submit(
                        row["id"], reason="TIME_EXPIRED", actor_type="SYSTEM", now=now
                    )
                )
            else:
                results.append(self._expire(row["id"], now=now))
        return results

    def recover_startup(self, now: datetime | None = None) -> dict[str, list[str]]:
        expired = [item["id"] for item in self.expire_due(now)]
        with self.database.connection() as connection:
            active = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM assessment_attempts WHERE status='ASSESSMENT_IN_PROGRESS'"
                ).fetchall()
            ]
        interrupted = [self.interrupt(attempt_id)["id"] for attempt_id in active]
        return {"expired": expired, "interrupted": interrupted}

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
        expired = False
        with self.database.transaction() as connection:
            now = self._now(now)
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            verify_candidate_token(token, attempt["candidate_token_hash"])
            if attempt["status"] != "ASSESSMENT_INTERRUPTED":
                raise StateConflict("Assessment is not resumable")
            if attempt["expires_at"] <= _iso(now):
                self._expire_in_transaction(connection, attempt, now)
                expired = True
            else:
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
        if expired:
            raise StateConflict("Assessment has expired")
        return self._summary(self.repository.get(attempt_id))

    def _submit(
        self,
        attempt_id: str,
        *,
        reason: str,
        actor_type: str,
        now: datetime | None = None,
        expected_revisions: dict[str, int] | None = None,
        idempotency_key_hash: str | None = None,
        request_fingerprint: str | None = None,
        candidate_token: str | None = None,
    ) -> dict[str, Any]:
        if reason not in {"MANUAL", "AUTO_SUBMIT", "TIME_EXPIRED", "RECOVERY"}:
            raise ValidationError("Invalid submit reason")
        terminal_due = False
        with self.database.transaction() as connection:
            now = self._now(now)
            timestamp = _iso(now)
            if idempotency_key_hash is not None:
                receipt = self._submission_receipt(
                    idempotency_key_hash, connection=connection
                )
                if receipt is not None:
                    verify_candidate_token(
                        candidate_token or "", receipt.get("candidateTokenHash")
                    )
                    if (
                        receipt["attemptId"] != attempt_id
                        or receipt["requestFingerprint"] != request_fingerprint
                    ):
                        raise StateConflict(
                            "Idempotency key was already used for another submission"
                        )
                    return_summary_only = True
                else:
                    return_summary_only = False
            else:
                return_summary_only = False

            if not return_summary_only:
                attempt = connection.execute(
                    "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
                ).fetchone()
                if attempt is None:
                    raise ResourceNotFound("Assessment attempt not found")
                if actor_type == "CANDIDATE":
                    verify_candidate_token(
                        candidate_token or "", attempt["candidate_token_hash"]
                    )
                    if attempt["status"] != "ASSESSMENT_IN_PROGRESS":
                        raise StateConflict(
                            "Assessment cannot be submitted from its current state"
                        )
                    if attempt["expires_at"] and attempt["expires_at"] <= timestamp:
                        self._finish_due_in_transaction(connection, attempt, now)
                        terminal_due = True
                elif attempt["status"] not in {
                    "ASSESSMENT_IN_PROGRESS", "ASSESSMENT_INTERRUPTED"
                }:
                    raise StateConflict("Assessment cannot be submitted")

                if not terminal_due:
                    if expected_revisions is not None:
                        rows = connection.execute(
                            "SELECT question_id, save_revision FROM answers WHERE assessment_attempt_id=?",
                            (attempt_id,),
                        ).fetchall()
                        persisted = {
                            row["question_id"]: row["save_revision"] for row in rows
                        }
                        if (
                            set(expected_revisions) != set(persisted)
                            or any(
                                isinstance(revision, bool)
                                or not isinstance(revision, int)
                                or persisted[question_id] != revision
                                for question_id, revision in expected_revisions.items()
                                if question_id in persisted
                            )
                        ):
                            raise RevisionConflict(
                                "Final answer revisions do not match persisted answers"
                            )
                    receipt_token_hash = attempt["candidate_token_hash"]
                    connection.execute(
                        "UPDATE answers SET submitted_at=?, updated_at=? WHERE assessment_attempt_id=?",
                        (timestamp, timestamp, attempt_id),
                    )
                    connection.execute(
                        """UPDATE assessment_attempts SET status='ASSESSMENT_SUBMITTED',
                           submitted_at=?, submit_reason=?, allow_answer_edit=0,
                           candidate_token_hash=NULL, updated_at=? WHERE id=?""",
                        (timestamp, reason, timestamp, attempt_id),
                    )
                    connection.execute(
                        "UPDATE interview_cases SET status='ASSESSMENT_SUBMITTED', updated_at=? WHERE id=?",
                        (timestamp, attempt["interview_case_id"]),
                    )
                    action = (
                        "ASSESSMENT_AUTO_SUBMITTED"
                        if reason != "MANUAL"
                        else "ASSESSMENT_SUBMITTED"
                    )
                    append_audit(
                        connection, actor_type=actor_type, action=action,
                        entity_type="ASSESSMENT_ATTEMPT", entity_id=attempt_id,
                        metadata={
                            "submitReason": reason,
                            **(
                                {
                                    "idempotencyKeyHash": idempotency_key_hash,
                                    "requestFingerprint": request_fingerprint,
                                    "candidateTokenHash": receipt_token_hash,
                                }
                                if idempotency_key_hash is not None
                                else {}
                            ),
                        },
                    )
        if terminal_due:
            raise Unauthenticated("Candidate session is invalid or expired")
        return self._summary(self.repository.get(attempt_id))

    def _expire(
        self, attempt_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            now = self._now(now)
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] == "ASSESSMENT_EXPIRED":
                return self._summary(attempt)
            if attempt["status"] not in {
                "ASSESSMENT_IN_PROGRESS", "ASSESSMENT_INTERRUPTED"
            }:
                raise StateConflict("Assessment cannot expire from its current state")
            self._expire_in_transaction(connection, attempt, now)
        return self._summary(self.repository.get(attempt_id))

    def _expire_in_transaction(
        self, connection: sqlite3.Connection, attempt: sqlite3.Row, now: datetime
    ) -> None:
        timestamp = _iso(now)
        connection.execute(
            """UPDATE answers SET submitted_at=COALESCE(submitted_at, ?), updated_at=?
               WHERE assessment_attempt_id=?""",
            (timestamp, timestamp, attempt["id"]),
        )
        connection.execute(
            """UPDATE assessment_attempts SET status='ASSESSMENT_EXPIRED',
               submit_reason='TIME_EXPIRED', allow_answer_edit=0,
               candidate_token_hash=NULL, updated_at=? WHERE id=?""",
            (timestamp, attempt["id"]),
        )
        connection.execute(
            "UPDATE interview_cases SET status='ASSESSMENT_EXPIRED', updated_at=? WHERE id=?",
            (timestamp, attempt["interview_case_id"]),
        )
        append_audit(
            connection,
            actor_type="SYSTEM",
            action="ASSESSMENT_EXPIRED",
            entity_type="ASSESSMENT_ATTEMPT",
            entity_id=attempt["id"],
            metadata={"submitReason": "TIME_EXPIRED"},
        )

    def _finish_due_in_transaction(
        self, connection: sqlite3.Connection, attempt: sqlite3.Row, now: datetime
    ) -> None:
        policy = connection.execute(
            "SELECT auto_submit_on_expiry FROM interview_cases WHERE id=?",
            (attempt["interview_case_id"],),
        ).fetchone()
        if (
            attempt["status"] == "ASSESSMENT_IN_PROGRESS"
            and policy is not None
            and policy["auto_submit_on_expiry"]
        ):
            self._auto_submit_due_in_transaction(connection, attempt, now)
        else:
            self._expire_in_transaction(connection, attempt, now)

    def _auto_submit_due_in_transaction(
        self, connection: sqlite3.Connection, attempt: sqlite3.Row, now: datetime
    ) -> None:
        timestamp = _iso(now)
        connection.execute(
            "UPDATE answers SET submitted_at=?, updated_at=? WHERE assessment_attempt_id=?",
            (timestamp, timestamp, attempt["id"]),
        )
        connection.execute(
            """UPDATE assessment_attempts SET status='ASSESSMENT_SUBMITTED',
               submitted_at=?, submit_reason='TIME_EXPIRED', allow_answer_edit=0,
               candidate_token_hash=NULL, updated_at=? WHERE id=?""",
            (timestamp, timestamp, attempt["id"]),
        )
        connection.execute(
            "UPDATE interview_cases SET status='ASSESSMENT_SUBMITTED', updated_at=? WHERE id=?",
            (timestamp, attempt["interview_case_id"]),
        )
        append_audit(
            connection,
            actor_type="SYSTEM",
            action="ASSESSMENT_AUTO_SUBMITTED",
            entity_type="ASSESSMENT_ATTEMPT",
            entity_id=attempt["id"],
            metadata={"submitReason": "TIME_EXPIRED"},
        )

    def _submission_receipt(
        self,
        idempotency_key_hash: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, str] | None:
        def find(active: sqlite3.Connection) -> dict[str, str] | None:
            rows = active.execute(
                """SELECT entity_id, metadata_json FROM audit_logs
                   WHERE entity_type='ASSESSMENT_ATTEMPT'
                     AND action IN ('ASSESSMENT_SUBMITTED','ASSESSMENT_AUTO_SUBMITTED')
                   ORDER BY created_at DESC"""
            ).fetchall()
            for row in rows:
                try:
                    metadata = json.loads(row["metadata_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if metadata.get("idempotencyKeyHash") == idempotency_key_hash:
                    return {
                        "attemptId": row["entity_id"],
                        "requestFingerprint": metadata.get("requestFingerprint", ""),
                        "candidateTokenHash": metadata.get("candidateTokenHash", ""),
                    }
            return None

        if connection is not None:
            return find(connection)
        with self.database.connection() as active:
            return find(active)

    def _candidate_attempt(
        self,
        attempt_id: str,
        token: str,
        *,
        now: datetime | None = None,
    ) -> sqlite3.Row:
        attempt = self.repository.get(attempt_id)
        verify_candidate_token(token, attempt["candidate_token_hash"])
        current = self._now(now)
        if (
            attempt["status"] in {"ASSESSMENT_IN_PROGRESS", "ASSESSMENT_INTERRUPTED"}
            and attempt["expires_at"]
            and attempt["expires_at"] <= _iso(current)
        ):
            self.expire_due(current)
            raise Unauthenticated("Candidate session is invalid or expired")
        return attempt

    def _now(self, value: datetime | None = None) -> datetime:
        return _utc(value if value is not None else self.clock())

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


def _submission_fingerprint(expected_revisions: dict[str, int] | None) -> str:
    canonical = json.dumps(
        expected_revisions, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _idempotency_hash(idempotency_key: str | None) -> str | None:
    if idempotency_key is None:
        return None
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValidationError("Idempotency key must be non-empty")
    if len(idempotency_key) > 256:
        raise ValidationError("Idempotency key is too long")
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
