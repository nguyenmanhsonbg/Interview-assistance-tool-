from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.ai.provider import AIProvider
from app.ai.redaction import sanitize_text
from app.ai.schemas import SchemaRegistry
from app.database import Database
from app.domain.errors import ForbiddenCapability, ResourceNotFound, StateConflict, ValidationError
from app.repositories.audit import append_audit
from app.repositories.assessment_snapshots import AssessmentSnapshotRepository
from app.repositories.evaluations import EvaluationRepository
from app.services.ai_task_service import AITaskService


class EvaluationService:
    def __init__(
        self,
        database: Database,
        schema_root: Path,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.database = database
        self.provider_name = provider_name
        self.model_name = model_name
        self.tasks = AITaskService(database, SchemaRegistry(schema_root))
        self.repository = EvaluationRepository(database)
        self.snapshots = AssessmentSnapshotRepository(database)

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
            provider=self.provider_name,
            model=self.model_name,
            prompt_key="answer_evaluation",
            schema_version="answer-evaluation.v1",
        )
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE interview_cases SET status='AI_ANALYZING',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
        return task

    def request_snapshot(
        self,
        case_id: str,
        snapshot_id: str,
        *,
        idempotency_key: str,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.snapshots.get(snapshot_id)
        if snapshot["interviewCaseId"] != case_id:
            raise ResourceNotFound("Assessment snapshot not found")
        manifest = self._snapshot_manifest(snapshot)
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint = hashlib.sha256(canonical).hexdigest()
        with self.database.connection() as connection:
            case = connection.execute(
                "SELECT refined_flow_status FROM interview_cases WHERE id=?", (case_id,)
            ).fetchone()
        if case is None:
            raise ResourceNotFound("Interview case not found")
        allowed = {"ANSWERS_IMPORTED", "AI_ANALYSIS_FAILED"}
        if force_rerun:
            allowed.add("AI_EVALUATED")
        if case["refined_flow_status"] == "AI_ANALYZING":
            existing = self.tasks.repository.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        if case["refined_flow_status"] not in allowed:
            raise StateConflict("Assessment snapshot is not ready for AI evaluation")
        task = self.tasks.enqueue(
            case_id,
            "EVALUATE_ASSESSMENT",
            assessment_snapshot_id=snapshot_id,
            input_manifest=manifest,
            input_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            provider=self.provider_name,
            model=self.model_name,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE interview_cases SET refined_flow_status='AI_ANALYZING',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
            connection.execute(
                "UPDATE assessment_snapshots SET status='AI_ANALYZING' WHERE id=?",
                (snapshot_id,),
            )
        return task

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        payload = self.provider_payload(task)
        result = self.tasks.process(task_id, provider, payload_override=payload)
        snapshot_id = task.get("assessmentSnapshotId")
        if snapshot_id and result["status"] in {"COMPLETED", "FAILED"}:
            status = "AI_EVALUATED" if result["status"] == "COMPLETED" else "AI_ANALYSIS_FAILED"
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE assessment_snapshots SET status=? WHERE id=?",
                    (status, snapshot_id),
                )
                connection.execute(
                    """UPDATE interview_cases SET refined_flow_status=?,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (status, task["interviewCaseId"]),
                )
        return result

    def provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        if task.get("assessmentSnapshotId"):
            return self._snapshot_provider_payload(task)
        case_id = task["interviewCaseId"]
        attempt_id = task["assessmentAttemptId"]
        manifest = task["inputManifest"]
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
            documents = []
            for reference in manifest.get("documents", []):
                row = connection.execute(
                    """SELECT document_type, id, version_no, extracted_text, content_sha256
                       FROM documents WHERE id=? AND interview_case_id=? AND is_ai_eligible=1""",
                    (reference.get("id"), case_id),
                ).fetchone()
                if (
                    row is None
                    or row["document_type"] != reference.get("document_type")
                    or row["version_no"] != reference.get("version_no")
                    or row["content_sha256"] != reference.get("content_sha256")
                ):
                    raise StateConflict("Evaluation document snapshot no longer matches")
                documents.append(row)
        answers = self.answer_snapshot(attempt_id)
        answer_refs = {reference["id"]: reference for reference in manifest.get("answers", [])}
        if set(answer_refs) != {answer["answerId"] for answer in answers}:
            raise StateConflict("Evaluation answer snapshot no longer matches")
        for answer in answers:
            reference = answer_refs[answer["answerId"]]
            content_hash = hashlib.sha256(answer["answerText"].encode("utf-8")).hexdigest()
            if (
                reference.get("question_id") != answer["questionId"]
                or reference.get("save_revision") != answer["saveRevision"]
                or reference.get("content_hash") != content_hash
            ):
                raise StateConflict("Evaluation answer snapshot no longer matches")
        return {
            "schemaVersion": "ai.input.v1",
            "operation": "EVALUATE_ASSESSMENT",
            "candidate": {"candidateCode": header["candidate_code"]},
            "job": {"positionTitle": header["position_title"], "targetLevel": header["target_level"]},
            "documents": [
                {"documentType": row["document_type"], "documentId": row["id"],
                  "versionNo": row["version_no"],
                  "sanitizedText": sanitize_text(
                      row["extracted_text"], known_names=(header["full_name"],)
                  ),
                 "contentSha256": row["content_sha256"]}
                for row in documents
            ],
            "questionSetId": header["question_set_id"],
            "assessmentAttemptId": attempt_id,
            "answers": [
                {
                    **answer,
                    "answerText": sanitize_text(
                        answer["answerText"], known_names=(header["full_name"],)
                    ),
                }
                for answer in answers
            ],
        }

    def current_ai_result(self, case_id: str) -> dict[str, Any]:
        result = self.tasks.repository.current_result(case_id, "ANSWER_EVALUATION")
        if result is None:
            raise ResourceNotFound("AI evaluation result not found")
        return result

    def refined_status(self, case_id: str) -> str:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT refined_flow_status, status FROM interview_cases WHERE id=?",
                (case_id,),
            ).fetchone()
        if row is None:
            raise ResourceNotFound("Interview case not found")
        return row["refined_flow_status"] or row["status"]

    def _snapshot_manifest(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "schemaVersion": "ai-task-manifest.v2",
            "interviewCaseId": snapshot["interviewCaseId"],
            "assessmentSnapshotId": snapshot["id"],
            "questionSetId": snapshot["questionSetId"],
            "snapshotVersion": snapshot["versionNo"],
            "workbookSha256": snapshot["workbookSha256"],
            "documents": snapshot["documentManifest"],
            "questions": [
                {
                    "id": question["questionId"],
                    "displayOrder": question["displayOrder"],
                    "contentHash": hashlib.sha256(
                        question["questionText"].encode("utf-8")
                    ).hexdigest(),
                }
                for question in snapshot["questions"]
            ],
            "answers": [
                {
                    "id": answer["answerId"],
                    "questionId": answer["questionId"],
                    "isAnswered": answer["isAnswered"],
                    "contentHash": answer["contentHash"],
                }
                for answer in snapshot["answers"]
            ],
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }

    def _snapshot_provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        case_id = task["interviewCaseId"]
        snapshot_id = task["assessmentSnapshotId"]
        snapshot = self.snapshots.get(snapshot_id)
        manifest = task["inputManifest"]
        if snapshot["interviewCaseId"] != case_id or snapshot["workbookSha256"] != manifest.get("workbookSha256"):
            raise StateConflict("Evaluation snapshot no longer matches")
        with self.database.connection() as connection:
            header = connection.execute(
                """SELECT c.candidate_code, c.full_name, j.position_title, j.target_level
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id WHERE ic.id=?""",
                (case_id,),
            ).fetchone()
            documents = []
            for reference in snapshot["documentManifest"]:
                row = connection.execute(
                    """SELECT document_type, id, version_no, extracted_text, content_sha256
                       FROM documents WHERE id=? AND interview_case_id=? AND is_ai_eligible=1""",
                    (reference.get("id"), case_id),
                ).fetchone()
                if (
                    row is None
                    or row["document_type"] != reference.get("document_type")
                    or row["version_no"] != reference.get("version_no")
                    or row["content_sha256"] != reference.get("content_sha256")
                ):
                    raise StateConflict("Evaluation document snapshot no longer matches")
                documents.append(row)
        if header is None:
            raise ResourceNotFound("Interview case not found")
        known_names = (header["full_name"],)
        return {
            "schemaVersion": "ai.input.v2",
            "operation": "EVALUATE_ASSESSMENT",
            "candidate": {"candidateCode": header["candidate_code"]},
            "job": {"positionTitle": header["position_title"], "targetLevel": header["target_level"]},
            "documents": [
                {
                    "documentType": row["document_type"],
                    "documentId": row["id"],
                    "versionNo": row["version_no"],
                    "sanitizedText": sanitize_text(row["extracted_text"], known_names=known_names),
                    "contentSha256": row["content_sha256"],
                }
                for row in documents
            ],
            "questionSetId": snapshot["questionSetId"],
            "assessmentSnapshotId": snapshot_id,
            "questions": [
                {
                    "questionId": question["questionId"],
                    "displayOrder": question["displayOrder"],
                    "questionText": sanitize_text(question["questionText"], known_names=known_names),
                    "competencyKey": sanitize_text(question["competencyKey"], known_names=known_names),
                    "expectedEvidence": sanitize_text(question["expectedEvidence"], known_names=known_names),
                    "rubric": {
                        key: sanitize_text(value, known_names=known_names)
                        for key, value in question["rubric"].items()
                    },
                }
                for question in snapshot["questions"]
            ],
            "answers": [
                {
                    "answerId": answer["answerId"],
                    "questionId": answer["questionId"],
                    "answerText": sanitize_text(answer["answerText"], known_names=known_names),
                    "isAnswered": answer["isAnswered"],
                    "assessmentStatus": answer["assessmentStatus"],
                }
                for answer in snapshot["answers"]
            ],
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
                evaluation_id = current["id"]
            else:
                if not isinstance(revision_reason, str) or not revision_reason.strip():
                    raise ValidationError("revisionReason is required to revise a final evaluation")
                version = current["version_no"] + 1
                supersedes = current["id"]
                action = "EVALUATION_REVISED"
                connection.execute(
                    "UPDATE evaluations SET is_current=0 WHERE id=?", (current["id"],)
                )
            if current is None or current["status"] != "DRAFT":
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
                """SELECT aa.*, qs.question_policy_json
                   FROM assessment_attempts aa
                   JOIN question_sets qs ON qs.id=aa.question_set_id
                   WHERE aa.id=? AND aa.interview_case_id=?""",
                (attempt_id, case_id),
            ).fetchone()
            if attempt is None:
                raise ResourceNotFound("Assessment attempt not found")
            if attempt["status"] not in {"ASSESSMENT_SUBMITTED", "ASSESSMENT_EXPIRED"}:
                raise StateConflict("Assessment must be submitted or expired")
            try:
                question_policy = json.loads(attempt["question_policy_json"])
            except (TypeError, json.JSONDecodeError) as error:
                raise StateConflict("Question Set provenance is invalid") from error
            documents = question_policy.get("sourceDocuments", [])
            if not isinstance(documents, list):
                raise StateConflict("Question Set provenance is invalid")
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
            "documents": documents,
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
