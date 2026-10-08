from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.ai.provider import AIProvider
from app.ai.redaction import sanitize_structure, sanitize_text
from app.ai.schemas import SchemaRegistry
from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.repositories.audit import append_audit
from app.repositories.question_variants import QuestionVariantRepository
from app.services.ai_task_service import AITaskService
from app.services.question_service import _validate_questions


MAX_VARIANT_PROMPT_CHARS = 2000
_MODES = {"USER_PROMPT", "SAME_GROUP"}


class QuestionVariantService:
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
        self.repository = QuestionVariantRepository(database)

    def request_variant(
        self,
        case_id: str,
        question_set_id: str,
        question_id: str,
        mode: str,
        prompt: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_prompt = self._validate_request(mode, prompt)
        source = self._load_source(case_id, question_set_id, question_id)
        source_fingerprint = _fingerprint(source["sourceFingerprintInput"])
        manifest = {
            "schemaVersion": "ai-task-manifest.v1",
            "operation": "GENERATE_QUESTION_VARIANT",
            "questionSetId": question_set_id,
            "sourceQuestionId": question_id,
            "sourceFingerprint": source_fingerprint,
            "mode": mode,
            "prompt": normalized_prompt,
            "sourceQuestion": source["sourceQuestion"],
            "documents": source["documents"],
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }
        task_fingerprint = _fingerprint(
            {
                "operation": "GENERATE_QUESTION_VARIANT",
                "questionSetId": question_set_id,
                "sourceQuestionId": question_id,
                "sourceFingerprint": source_fingerprint,
                "mode": mode,
                "prompt": normalized_prompt,
                "schemaVersion": "question-variant.v1",
            }
        )
        task = self.tasks.enqueue(
            case_id,
            "GENERATE_QUESTION_VARIANT",
            input_manifest=manifest,
            input_fingerprint=task_fingerprint,
            idempotency_key=idempotency_key,
            source_question_id=question_id,
            provider=self.provider_name,
            model=self.model_name,
        )
        with self.database.transaction() as connection:
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_VARIANT_TASK_REQUESTED",
                entity_type="AI_TASK",
                entity_id=task["id"],
                metadata={
                    "questionSetId": question_set_id,
                    "sourceQuestionId": question_id,
                    "mode": mode,
                },
            )
        return task

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        output = self.tasks.process(
            task_id,
            provider,
            payload_override=self.provider_payload(task),
            context_override={
                "questionSetId": task["inputManifest"].get("questionSetId"),
                "sourceQuestionId": task["inputManifest"].get("sourceQuestionId"),
            },
        )
        if output["status"] == "COMPLETED":
            manifest = task["inputManifest"]
            proposal_id = str(uuid.uuid4())
            with self.database.transaction() as connection:
                proposal_id, created = self.repository.create_proposal_from_result(
                    connection,
                    proposal_id=proposal_id,
                    ai_result_id=output["result"]["id"],
                    case_id=task["interviewCaseId"],
                    question_set_id=manifest["questionSetId"],
                    source_question_id=manifest["sourceQuestionId"],
                    mode=manifest["mode"],
                    source_fingerprint=manifest["sourceFingerprint"],
                )
                if created:
                    append_audit(
                        connection,
                        actor_type="SYSTEM",
                        action="QUESTION_VARIANT_GENERATED",
                        entity_type="QUESTION_VARIANT_PROPOSAL",
                        entity_id=proposal_id,
                        metadata={
                            "taskId": task_id,
                            "questionSetId": manifest["questionSetId"],
                            "sourceQuestionId": manifest["sourceQuestionId"],
                        },
                    )
            output["proposalId"] = proposal_id
            output["proposal"] = self.repository.get_proposal(
                task["interviewCaseId"],
                manifest["questionSetId"],
                manifest["sourceQuestionId"],
                proposal_id,
            )
        elif output["status"] == "FAILED":
            with self.database.transaction() as connection:
                append_audit(
                    connection,
                    actor_type="SYSTEM",
                    action="QUESTION_VARIANT_FAILED",
                    entity_type="AI_TASK",
                    entity_id=task_id,
                    metadata={"errorCode": output.get("errorCode")},
                )
        return output

    def get_proposal(
        self, case_id: str, question_set_id: str, question_id: str, proposal_id: str
    ) -> dict[str, Any]:
        return self.repository.get_proposal(
            case_id, question_set_id, question_id, proposal_id
        )

    def get_proposal_by_id(
        self, case_id: str, question_id: str, proposal_id: str
    ) -> dict[str, Any]:
        return self.repository.get_proposal_by_id(case_id, question_id, proposal_id)

    def list_active_proposals(
        self, case_id: str, question_set_id: str, question_id: str
    ) -> list[dict[str, Any]]:
        return self.repository.list_active_proposals(case_id, question_set_id, question_id)

    def discard_proposal(
        self,
        case_id: str,
        question_set_id: str,
        question_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            question_set = self._lock_check(
                connection, case_id, question_set_id, question_id
            )
            changed = self.repository.mark_discarded(
                connection,
                case_id=case_id,
                question_set_id=question_set_id,
                question_id=question_id,
                proposal_id=proposal_id,
            )
            if changed:
                append_audit(
                    connection,
                    actor_type="COMMITTEE",
                    action="QUESTION_VARIANT_DISCARDED",
                    entity_type="QUESTION_VARIANT_PROPOSAL",
                    entity_id=proposal_id,
                    metadata={"questionSetId": question_set["id"], "sourceQuestionId": question_id},
                )
        return self.get_proposal(case_id, question_set_id, question_id, proposal_id)

    def apply_proposal(
        self,
        case_id: str,
        question_set_id: str,
        question_id: str,
        proposal_id: str,
        expected_question_set_updated_at: str,
        expected_source_fingerprint: str,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            question_set = self._lock_check(
                connection, case_id, question_set_id, question_id
            )
            if question_set["updated_at"] != expected_question_set_updated_at:
                raise StateConflict("Question variant proposal is stale")
            source = _source_from_connection(
                connection, case_id, question_set_id, question_id
            )
            current_fingerprint = _fingerprint(source["sourceFingerprintInput"])
            if current_fingerprint != expected_source_fingerprint:
                raise StateConflict("Question variant proposal source is stale")
            proposal = connection.execute(
                """SELECT p.*, r.payload_json
                   FROM question_variant_proposals p
                   JOIN ai_results r ON r.id=p.ai_result_id
                   WHERE p.id=? AND p.interview_case_id=? AND p.question_set_id=?
                     AND p.source_question_id=?""",
                (proposal_id, case_id, question_set_id, question_id),
            ).fetchone()
            if proposal is None:
                raise ResourceNotFound("Question variant proposal not found")
            if proposal["status"] != "PROPOSED":
                raise StateConflict("Question variant proposal is no longer proposed")
            payload = json.loads(proposal["payload_json"])
            self.tasks.schemas.validate(
                "QUESTION_VARIANT",
                payload,
                context={
                    "questionSetId": question_set_id,
                    "sourceQuestionId": question_id,
                },
            )
            current_questions = [
                _question_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM questions WHERE question_set_id=? ORDER BY display_order",
                    (question_set_id,),
                ).fetchall()
            ]
            replacement = next(
                question for question in current_questions if question["id"] == question_id
            )
            replacement.update(
                {
                    "questionText": payload["variant"]["questionText"],
                    "purpose": payload["variant"]["purpose"],
                    "nextStepObjective": payload["variant"]["nextStepObjective"],
                    "expectedEvidence": payload["variant"]["expectedEvidence"],
                    "rubric": payload["variant"]["rubric"],
                }
            )
            _validate_questions(current_questions)
            connection.execute(
                """UPDATE questions SET question_text=?, purpose=?, next_step_objective=?,
                   expected_evidence=?, rubric_json=? WHERE id=? AND question_set_id=?""",
                (
                    replacement["questionText"],
                    replacement["purpose"],
                    replacement["nextStepObjective"],
                    replacement["expectedEvidence"],
                    json.dumps(replacement["rubric"], ensure_ascii=False, separators=(",", ":")),
                    question_id,
                    question_set_id,
                ),
            )
            connection.execute(
                """UPDATE question_sets SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=?""",
                (question_set_id,),
            )
            self.repository.mark_applied(
                connection,
                case_id=case_id,
                question_set_id=question_set_id,
                question_id=question_id,
                proposal_id=proposal_id,
            )
            after_source = _source_from_connection(
                connection, case_id, question_set_id, question_id
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_VARIANT_APPLIED",
                entity_type="QUESTION_VARIANT_PROPOSAL",
                entity_id=proposal_id,
                metadata={
                    "questionSetId": question_set_id,
                    "sourceQuestionId": question_id,
                    "beforeFingerprint": current_fingerprint,
                    "afterFingerprint": _fingerprint(after_source["sourceFingerprintInput"]),
                },
            )
        return {
            "question": replacement,
            "proposal": self.get_proposal(
                case_id, question_set_id, question_id, proposal_id
            ),
        }

    def provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        manifest = task["inputManifest"]
        case_id = task["interviewCaseId"]
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT c.full_name, c.candidate_code, j.position_title, j.target_level
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id
                   WHERE ic.id=?""",
                (case_id,),
            ).fetchone()
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
                    raise StateConflict("Question variant document snapshot no longer matches")
                documents.append(
                    {
                        "documentType": row["document_type"],
                        "documentId": row["id"],
                        "versionNo": row["version_no"],
                        "contentSha256": row["content_sha256"],
                        "sanitizedText": sanitize_text(
                            row["extracted_text"], known_names=(case["full_name"],)
                        ),
                    }
                )
        if case is None:
            raise ResourceNotFound("Interview case not found")
        return {
            "schemaVersion": "ai.input.v1",
            "operation": "GENERATE_QUESTION_VARIANT",
            "candidateCode": case["candidate_code"],
            "job": {
                "positionTitle": case["position_title"],
                "targetLevel": case["target_level"],
            },
            "mode": manifest["mode"],
            "questionSetId": manifest["questionSetId"],
            "sourceQuestionId": manifest["sourceQuestionId"],
            "sourceQuestion": sanitize_structure(
                manifest["sourceQuestion"], known_names=(case["full_name"],)
            ),
            "documents": documents,
            "prompt": manifest.get("prompt"),
        }

    @staticmethod
    def _validate_request(mode: str, prompt: str | None) -> str | None:
        if mode not in _MODES:
            raise ValidationError("Unsupported question variant mode")
        if prompt is not None and not isinstance(prompt, str):
            raise ValidationError("Question variant prompt must be text")
        normalized = prompt.strip() if isinstance(prompt, str) else None
        if mode == "USER_PROMPT":
            if not normalized:
                raise ValidationError("Question variant prompt is required")
            if len(normalized) > MAX_VARIANT_PROMPT_CHARS:
                raise ValidationError("Question variant prompt is too long")
        elif normalized:
            raise ValidationError("SAME_GROUP question variant does not accept a prompt")
        return normalized if mode == "USER_PROMPT" else None

    def _load_source(
        self, case_id: str, question_set_id: str, question_id: str
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            attempt = connection.execute(
                "SELECT 1 FROM assessment_attempts WHERE interview_case_id=? LIMIT 1",
                (case_id,),
            ).fetchone()
            if attempt is not None:
                raise StateConflict("Question Set is locked after assessment start")
            return _source_from_connection(connection, case_id, question_set_id, question_id)

    def _lock_check(self, connection, case_id: str, question_set_id: str, question_id: str):
        row = connection.execute(
            """SELECT qs.* FROM question_sets qs
               JOIN questions q ON q.question_set_id=qs.id AND q.id=?
               WHERE qs.id=? AND qs.interview_case_id=?""",
            (question_id, question_set_id, case_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound("Question source not found")
        if row["status"] not in {"DRAFT", "GENERATED"}:
            raise StateConflict("Question Set is locked")
        attempt = connection.execute(
            "SELECT 1 FROM assessment_attempts WHERE interview_case_id=? LIMIT 1",
            (case_id,),
        ).fetchone()
        if attempt is not None:
            raise StateConflict("Question Set is locked after assessment start")
        return row


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _source_from_connection(connection, case_id: str, question_set_id: str, question_id: str):
    row = connection.execute(
        """SELECT qs.id AS question_set_id, qs.interview_case_id,
                  qs.status AS question_set_status, qs.updated_at AS question_set_updated_at,
                  q.*, c.full_name
           FROM question_sets qs
           JOIN questions q ON q.question_set_id=qs.id
           JOIN interview_cases ic ON ic.id=qs.interview_case_id
           JOIN candidates c ON c.id=ic.candidate_id
           WHERE qs.id=? AND qs.interview_case_id=? AND q.id=?""",
        (question_set_id, case_id, question_id),
    ).fetchone()
    if row is None:
        raise ResourceNotFound("Question source not found")
    if row["question_set_status"] not in {"DRAFT", "GENERATED"}:
        raise StateConflict("Question Set is locked")
    documents = [
        dict(document)
        for document in connection.execute(
            """SELECT id, document_type, version_no, content_sha256
               FROM documents
               WHERE interview_case_id=? AND is_current=1 AND is_ai_eligible=1
               ORDER BY document_type""",
            (case_id,),
        ).fetchall()
    ]
    source_question = _question_from_row(row)
    source_fingerprint_input = {
        "questionSetId": question_set_id,
        "questionSetUpdatedAt": row["question_set_updated_at"],
        "sourceQuestion": source_question,
        "documents": documents,
    }
    return {
        "sourceQuestion": source_question,
        "documents": documents,
        "sourceFingerprintInput": source_fingerprint_input,
    }


def _question_from_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "displayOrder": row["display_order"],
        "questionText": row["question_text"],
        "competencyKey": row["competency_key"],
        "sourceKind": row["source_kind"],
        "questionCategory": row["question_category"],
        "purpose": row["purpose"],
        "nextStepObjective": row["next_step_objective"],
        "questionType": row["question_type"],
        "difficulty": row["difficulty"],
        "expectedEvidence": row["expected_evidence"],
        "rubric": json.loads(row["rubric_json"]),
        "isRequired": bool(row["is_required"]),
        "estimatedSeconds": row["estimated_seconds"],
    }
