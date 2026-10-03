from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.ai.schemas import validate_question_generation
from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.domain.rules import require_text
from app.repositories.audit import append_audit
from app.repositories.questions import QuestionRepository


class QuestionService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = QuestionRepository(database)

    def create_manual_draft(
        self,
        case_id: str,
        questions: list[dict[str, Any]],
        *,
        duration_seconds: int = 900,
    ) -> dict[str, Any]:
        normalized = _validate_questions(questions)
        return self._create_set(
            case_id,
            normalized,
            duration_seconds=duration_seconds,
            status="GENERATED",
            expected_case_states={"DOCUMENTS_READY", "QUESTION_GENERATION_FAILED"},
            audit_action="QUESTION_SET_MANUAL_CREATED",
        )

    def materialize_generated(
        self, case_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        validated = validate_question_generation(payload)
        questions = [
            {
                "displayOrder": item["displayOrder"],
                "questionText": item["text"],
                "competencyKey": item["competencyKey"],
                "sourceKind": item["sourceKind"],
                "purpose": item["purpose"],
                "questionType": item["questionType"],
                "difficulty": item["difficulty"],
                "expectedEvidence": item["expectedEvidence"],
                "rubric": item["rubric"],
                "isRequired": item["isRequired"],
                "estimatedSeconds": item["estimatedSeconds"],
            }
            for item in validated["questions"]
        ]
        return self._create_set(
            case_id,
            _validate_questions(questions),
            duration_seconds=validated["estimatedDurationSeconds"],
            status="GENERATED",
            expected_case_states={"QUESTIONS_GENERATING"},
            audit_action="QUESTION_SET_GENERATED",
            question_policy={
                "confidence": validated["confidence"],
                "limitations": validated.get("limitations", []),
            },
        )

    def update_draft(
        self, question_set_id: str, questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        normalized = _validate_questions(questions)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM question_sets WHERE id=?", (question_set_id,)
            ).fetchone()
            if row is None:
                raise ResourceNotFound("Question Set not found")
            if row["status"] not in {"DRAFT", "GENERATED"}:
                raise StateConflict("Approved Question Set is immutable")
            connection.execute("DELETE FROM questions WHERE question_set_id=?", (question_set_id,))
            _insert_questions(connection, question_set_id, normalized)
            connection.execute(
                "UPDATE question_sets SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (question_set_id,),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_SET_EDITED",
                entity_type="QUESTION_SET",
                entity_id=question_set_id,
                metadata={"questionCount": len(normalized)},
            )
        return self.repository.get_set(question_set_id)

    def approve(self, question_set_id: str, member_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM question_sets WHERE id=?", (question_set_id,)
            ).fetchone()
            if row is None:
                raise ResourceNotFound("Question Set not found")
            if row["status"] == "APPROVED":
                return self.repository.get_set(question_set_id)
            if row["status"] not in {"DRAFT", "GENERATED"}:
                raise StateConflict("Question Set cannot be approved")
            member = connection.execute(
                """SELECT 1 FROM interview_case_committee_members
                   WHERE id=? AND interview_case_id=?""",
                (member_id, row["interview_case_id"]),
            ).fetchone()
            if member is None:
                raise ValidationError("Approving member does not belong to this case")
            count = connection.execute(
                "SELECT COUNT(*) FROM questions WHERE question_set_id=?",
                (question_set_id,),
            ).fetchone()[0]
            if not 5 <= count <= 8:
                raise ValidationError("Question Set must contain 5 to 8 questions")
            connection.execute(
                """UPDATE question_sets SET status='APPROVED', approved_by_member_id=?,
                   approved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (member_id, question_set_id),
            )
            connection.execute(
                """UPDATE interview_cases SET status='QUESTIONS_APPROVED',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (row["interview_case_id"],),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                actor_ref_id=member_id,
                action="QUESTION_SET_APPROVED",
                entity_type="QUESTION_SET",
                entity_id=question_set_id,
                metadata={"questionCount": count},
            )
        return self.repository.get_set(question_set_id)

    def get_for_case(self, case_id: str) -> dict[str, Any] | None:
        return self.repository.current_for_case(case_id)

    def _create_set(
        self,
        case_id: str,
        questions: list[dict[str, Any]],
        *,
        duration_seconds: int,
        status: str,
        expected_case_states: set[str],
        audit_action: str,
        question_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(duration_seconds, int) or not 600 <= duration_seconds <= 900:
            raise ValidationError("durationSeconds must be between 600 and 900")
        question_set_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            case = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (case_id,)
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] not in expected_case_states:
                raise StateConflict("Case is not ready for question materialization")
            previous = connection.execute(
                """SELECT id, version_no FROM question_sets WHERE interview_case_id=?
                   ORDER BY version_no DESC LIMIT 1""",
                (case_id,),
            ).fetchone()
            version = 1 if previous is None else previous["version_no"] + 1
            supersedes = None if previous is None else previous["id"]
            if previous is not None:
                connection.execute(
                    "UPDATE question_sets SET status='SUPERSEDED' WHERE id=? AND status!='APPROVED'",
                    (previous["id"],),
                )
            connection.execute(
                """INSERT INTO question_sets(
                    id, interview_case_id, version_no, status, duration_seconds,
                    rubric_policy_json, question_policy_json, supersedes_question_set_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    question_set_id, case_id, version, status, duration_seconds,
                    json.dumps({"version": "rubric.v1"}),
                    json.dumps(question_policy or {}), supersedes,
                ),
            )
            _insert_questions(connection, question_set_id, questions)
            connection.execute(
                """UPDATE interview_cases SET status='QUESTIONS_GENERATED',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
            append_audit(
                connection,
                actor_type="SYSTEM" if audit_action == "QUESTION_SET_GENERATED" else "COMMITTEE",
                action=audit_action,
                entity_type="QUESTION_SET",
                entity_id=question_set_id,
                metadata={"versionNo": version, "questionCount": len(questions)},
            )
        return self.repository.get_set(question_set_id)


def _validate_questions(questions: Any) -> list[dict[str, Any]]:
    if not isinstance(questions, list) or not 5 <= len(questions) <= 8:
        raise ValidationError("Question Set must contain 5 to 8 questions")
    normalized: list[dict[str, Any]] = []
    orders: set[int] = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValidationError("Question must be an object")
        order = question.get("displayOrder")
        if not isinstance(order, int) or isinstance(order, bool) or order in orders or not 1 <= order <= 8:
            raise ValidationError("displayOrder must be unique and between 1 and 8")
        orders.add(order)
        rubric = question.get("rubric")
        if not isinstance(rubric, dict) or any(
            not isinstance(rubric.get(f"score{score}"), str)
            or not rubric[f"score{score}"].strip()
            for score in range(5)
        ):
            raise ValidationError("rubric must define score0 through score4")
        normalized.append(
            {
                "id": question.get("id") or str(uuid.uuid4()),
                "displayOrder": order,
                "questionText": require_text(question.get("questionText"), "questionText"),
                "competencyKey": require_text(question.get("competencyKey"), "competencyKey"),
                "sourceKind": question.get("sourceKind", "MANUAL"),
                "purpose": require_text(question.get("purpose"), "purpose"),
                "questionType": question.get("questionType", "SHORT_TEXT"),
                "difficulty": question.get("difficulty", "MEDIUM"),
                "expectedEvidence": require_text(question.get("expectedEvidence"), "expectedEvidence"),
                "rubric": rubric,
                "isRequired": bool(question.get("isRequired", True)),
                "estimatedSeconds": question.get("estimatedSeconds"),
            }
        )
    return sorted(normalized, key=lambda item: item["displayOrder"])


def _insert_questions(
    connection: sqlite3.Connection,
    question_set_id: str,
    questions: list[dict[str, Any]],
) -> None:
    for question in questions:
        connection.execute(
            """INSERT INTO questions(
                id, question_set_id, display_order, question_text, competency_key,
                source_kind, purpose, question_type, difficulty, expected_evidence,
                rubric_json, is_required, estimated_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question["id"], question_set_id, question["displayOrder"],
                question["questionText"], question["competencyKey"],
                question["sourceKind"], question["purpose"], question["questionType"],
                question["difficulty"], question["expectedEvidence"],
                json.dumps(question["rubric"], ensure_ascii=False, separators=(",", ":")),
                int(question["isRequired"]), question["estimatedSeconds"],
            ),
        )
