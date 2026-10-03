from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.ai.provider import AIProvider
from app.ai.schemas import SchemaRegistry
from app.database import Database
from app.domain.errors import ForbiddenCapability, ResourceNotFound, StateConflict, ValidationError
from app.repositories.audit import append_audit
from app.repositories.evaluations import EvaluationRepository
from app.services.ai_task_service import AITaskService


class EvaluationService:
    def __init__(self, database: Database, schema_root: Path) -> None:
        self.database = database
        self.tasks = AITaskService(database, SchemaRegistry(schema_root))
        self.repository = EvaluationRepository(database)

    def request(
        self,
        case_id: str,
        attempt_id: str,
        *,
        idempotency_key: str,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        manifest = self._manifest(case_id, attempt_id)
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint = hashlib.sha256(canonical).hexdigest()
        with self.database.connection() as connection:
            case = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (case_id,)
            ).fetchone()
        if case is None:
            raise ResourceNotFound("Interview case not found")
        allowed = {"ASSESSMENT_SUBMITTED", "ASSESSMENT_EXPIRED", "AI_ANALYSIS_FAILED"}
        if force_rerun:
            allowed.add("INTERVIEW_BRIEF_READY")
        if case["status"] == "AI_ANALYZING":
            existing = self.tasks.repository.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        if case["status"] not in allowed:
            raise StateConflict("Case is not ready for AI answer evaluation")
        task = self.tasks.enqueue(
            case_id,
            "EVALUATE_ASSESSMENT",
            assessment_attempt_id=attempt_id,
            input_manifest=manifest,
            input_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE interview_cases SET status='AI_ANALYZING',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
        return task

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        payload = self.provider_payload(
            task["interviewCaseId"], task["assessmentAttemptId"]
        )
        return self.tasks.process(task_id, provider, payload_override=payload)

    def provider_payload(self, case_id: str, attempt_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            header = connection.execute(
                """SELECT c.candidate_code, c.full_name, j.position_title, j.target_level,
                          aa.question_set_id, aa.started_at, aa.submitted_at
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id
                   JOIN assessment_attempts aa ON aa.interview_case_id=ic.id
                   WHERE ic.id=? AND aa.id=?""",
                (case_id, attempt_id),
            ).fetchone()
            if header is None:
                raise ResourceNotFound("Assessment snapshot not found")
            documents = connection.execute(
                """SELECT document_type, id, version_no, extracted_text, content_sha256
                   FROM documents WHERE interview_case_id=? AND is_current=1
                     AND is_ai_eligible=1 ORDER BY document_type""",
                (case_id,),
            ).fetchall()
        return {
            "schemaVersion": "ai.input.v1",
            "operation": "EVALUATE_ASSESSMENT",
            "candidate": {"candidateCode": header["candidate_code"], "fullName": header["full_name"]},
            "job": {"positionTitle": header["position_title"], "targetLevel": header["target_level"]},
            "documents": [
                {"documentType": row["document_type"], "documentId": row["id"],
                 "versionNo": row["version_no"], "sanitizedText": row["extracted_text"],
                 "contentSha256": row["content_sha256"]}
                for row in documents
            ],
            "questionSetId": header["question_set_id"],
            "assessmentAttemptId": attempt_id,
            "answers": self.answer_snapshot(attempt_id),
        }

    def answer_snapshot(self, attempt_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT a.id answer_id, a.answer_text, a.is_answered, a.save_revision,
                          q.id question_id, q.question_text, q.competency_key,
                          q.expected_evidence, q.rubric_json
                   FROM answers a JOIN questions q ON q.id=a.question_id
                   WHERE a.assessment_attempt_id=? ORDER BY q.display_order""",
                (attempt_id,),
            ).fetchall()
        return [
            {"answerId": row["answer_id"], "questionId": row["question_id"],
             "questionText": row["question_text"], "competencyKey": row["competency_key"],
             "expectedEvidence": row["expected_evidence"], "rubric": json.loads(row["rubric_json"]),
             "answerText": row["answer_text"], "isAnswered": bool(row["is_answered"]),
             "saveRevision": row["save_revision"]}
            for row in rows
        ]

    def case_status(self, case_id: str) -> str:
        with self.database.connection() as connection:
            row = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise ResourceNotFound("Interview case not found")
        return row["status"]

    def current_final_evaluation(self, case_id: str) -> dict[str, Any]:
        evaluation = self.repository.current_evaluation(case_id)
        if evaluation is None:
            raise ResourceNotFound("Evaluation not found")
        return evaluation

    def save_final_draft(
        self,
        case_id: str,
        payload: dict[str, Any],
        *,
        revision_reason: str | None = None,
    ) -> dict[str, Any]:
        values = _validate_final_payload(payload)
        evaluation_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            case = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (case_id,)
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            current = connection.execute(
                "SELECT * FROM evaluations WHERE interview_case_id=? AND is_current=1",
                (case_id,),
            ).fetchone()
            if current is None:
                if case["status"] not in {"LIVE_INTERVIEW_COMPLETED", "AI_ANALYSIS_FAILED"}:
                    raise StateConflict("Case is not ready for evaluation")
                version, supersedes, action = 1, None, "EVALUATION_DRAFTED"
            elif current["status"] == "DRAFT":
                connection.execute(
                    """UPDATE evaluations SET final_result=?, final_level=?, summary=?,
                       strengths_json=?, gaps_json=?, risks_json=?, final_comment=? WHERE id=?""",
                    (*values, current["id"]),
                )
                append_audit(
                    connection, actor_type="COMMITTEE", action="EVALUATION_DRAFTED",
                    entity_type="EVALUATION", entity_id=current["id"],
                    metadata={"versionNo": current["version_no"], "updated": True},
                )
                return self.repository.get_evaluation(current["id"])
            else:
                if not isinstance(revision_reason, str) or not revision_reason.strip():
                    raise ValidationError("revisionReason is required to revise a final evaluation")
                version = current["version_no"] + 1
                supersedes = current["id"]
                action = "EVALUATION_REVISED"
                connection.execute(
                    "UPDATE evaluations SET is_current=0 WHERE id=?", (current["id"],)
                )
            connection.execute(
                """INSERT INTO evaluations(
                    id, interview_case_id, version_no, status, final_result,
                    final_level, summary, strengths_json, gaps_json, risks_json,
                    final_comment, supersedes_evaluation_id, is_current
                ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (evaluation_id, case_id, version, *values, supersedes),
            )
            connection.execute(
                "UPDATE interview_cases SET status='EVALUATION_PENDING', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (case_id,),
            )
            metadata = {"versionNo": version}
            if revision_reason:
                metadata["reason"] = revision_reason.strip()
            append_audit(
                connection, actor_type="COMMITTEE", action=action,
                entity_type="EVALUATION", entity_id=evaluation_id, metadata=metadata,
            )
        return self.repository.get_evaluation(evaluation_id)

    def finalize(self, evaluation_id: str, member_id: str, *, confirmation: str) -> dict[str, Any]:
        if confirmation != "FINALIZE_EVALUATION":
            raise ValidationError("Explicit finalization confirmation is required")
        with self.database.transaction() as connection:
            evaluation = connection.execute(
                "SELECT * FROM evaluations WHERE id=?", (evaluation_id,)
            ).fetchone()
            if evaluation is None:
                raise ResourceNotFound("Evaluation not found")
            if evaluation["status"] == "FINAL":
                return self.repository.get_evaluation(evaluation_id)
            if not evaluation["is_current"]:
                raise StateConflict("Only the current evaluation can be finalized")
            case = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?",
                (evaluation["interview_case_id"],),
            ).fetchone()
            if case["status"] != "EVALUATION_PENDING":
                raise StateConflict("Case is not pending evaluation")
            member = connection.execute(
                """SELECT role FROM interview_case_committee_members
                   WHERE id=? AND interview_case_id=?""",
                (member_id, evaluation["interview_case_id"]),
            ).fetchone()
            if member is None or member["role"] != "LEAD":
                raise ForbiddenCapability("Only the case lead/finalizer can finalize")
            if evaluation["final_result"] == "PENDING":
                raise ValidationError("A final result is required")
            connection.execute(
                """UPDATE evaluations SET status='FINAL', decided_by_member_id=?,
                   decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (member_id, evaluation_id),
            )
            connection.execute(
                "UPDATE interview_cases SET status='EVALUATED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (evaluation["interview_case_id"],),
            )
            append_audit(
                connection, actor_type="COMMITTEE", actor_ref_id=member_id,
                action="EVALUATION_FINALIZED", entity_type="EVALUATION",
                entity_id=evaluation_id,
                metadata={"versionNo": evaluation["version_no"], "finalResult": evaluation["final_result"]},
            )
        return self.repository.get_evaluation(evaluation_id)

    def _manifest(self, case_id: str, attempt_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            attempt = connection.execute(
                "SELECT * FROM assessment_attempts WHERE id=? AND interview_case_id=?",
                (attempt_id, case_id),
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] not in {"ASSESSMENT_SUBMITTED", "ASSESSMENT_EXPIRED"}:
                raise StateConflict("Assessment must be submitted or expired")
            documents = connection.execute(
                """SELECT id, document_type, version_no, content_sha256
                   FROM documents WHERE interview_case_id=? AND is_current=1
                     AND is_ai_eligible=1 ORDER BY document_type""", (case_id,)
            ).fetchall()
            answers = connection.execute(
                """SELECT id, question_id, is_answered, save_revision, answer_text
                   FROM answers WHERE assessment_attempt_id=? ORDER BY question_id""",
                (attempt_id,),
            ).fetchall()
        answer_references = [
            {
                "id": row["id"],
                "question_id": row["question_id"],
                "is_answered": row["is_answered"],
                "save_revision": row["save_revision"],
                "content_hash": hashlib.sha256(row["answer_text"].encode("utf-8")).hexdigest(),
            }
            for row in answers
        ]
        return {
            "schemaVersion": "ai-task-manifest.v1", "interviewCaseId": case_id,
            "assessmentAttemptId": attempt_id, "questionSetId": attempt["question_set_id"],
            "documents": [dict(row) for row in documents],
            "answers": answer_references,
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }


def _validate_final_payload(payload: Any) -> tuple[Any, ...]:
    if not isinstance(payload, dict):
        raise ValidationError("Evaluation payload must be an object")
    result = payload.get("finalResult", "PENDING")
    allowed = {"PASS", "FAIL", "NEXT_ROUND", "NEEDS_ADDITIONAL_ASSESSMENT", "PENDING"}
    if result not in allowed:
        raise ValidationError("Unsupported finalResult")
    encoded: list[str] = []
    for field in ("strengths", "gaps", "risks"):
        value = payload.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValidationError(f"{field} must be an array of strings")
        encoded.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    for field in ("finalLevel", "summary", "finalComment"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise ValidationError(f"{field} must be text or null")
    return (
        result, payload.get("finalLevel"), payload.get("summary"),
        encoded[0], encoded[1], encoded[2], payload.get("finalComment"),
    )
