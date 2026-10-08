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
from app.domain.rules import MAX_ADDITION_PROMPT_CHARS
from app.repositories.audit import append_audit
from app.repositories.question_additions import QuestionAdditionRepository
from app.services.ai_task_service import AITaskService
from app.services.question_service import _insert_questions, _validate_questions


_MODES = {"USER_PROMPT", "AUTO_GROUP"}
_CATEGORIES = {"FOUNDATION", "APPLICATION", "DEEP_DIVE"}


class QuestionAdditionService:
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
        self.repository = QuestionAdditionRepository(database)

    def request_addition(
        self,
        case_id: str,
        question_set_id: str,
        target_category: str,
        mode: str,
        prompt: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_prompt = self._validate_request(target_category, mode, prompt)
        source = self._load_source(case_id, question_set_id)
        source_fingerprint = _fingerprint(source["sourceFingerprintInput"])
        manifest = {
            "schemaVersion": "ai-task-manifest.v1",
            "operation": "GENERATE_QUESTION_ADDITION",
            "questionSetId": question_set_id,
            "targetCategory": target_category,
            "mode": mode,
            "prompt": normalized_prompt,
            "sourceFingerprint": source_fingerprint,
            "questionSetUpdatedAt": source["questionSetUpdatedAt"],
            "documents": source["documents"],
            "existingQuestions": source["existingQuestions"],
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }
        task_fingerprint = _fingerprint(
            {
                "operation": "GENERATE_QUESTION_ADDITION",
                "questionSetId": question_set_id,
                "targetCategory": target_category,
                "mode": mode,
                "prompt": normalized_prompt,
                "sourceFingerprint": source_fingerprint,
                "schemaVersion": "question-addition.v1",
            }
        )
        task = self.tasks.enqueue(
            case_id,
            "GENERATE_QUESTION_ADDITION",
            input_manifest=manifest,
            input_fingerprint=task_fingerprint,
            idempotency_key=idempotency_key,
            target_question_category=target_category,
            provider=self.provider_name,
            model=self.model_name,
        )
        with self.database.transaction() as connection:
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_ADDITION_TASK_REQUESTED",
                entity_type="AI_TASK",
                entity_id=task["id"],
                metadata={
                    "questionSetId": question_set_id,
                    "targetCategory": target_category,
                    "mode": mode,
                },
            )
        return task

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        manifest = task["inputManifest"]
        output = self.tasks.process(
            task_id,
            provider,
            payload_override=self.provider_payload(task),
            context_override={
                "questionSetId": manifest.get("questionSetId"),
                "targetCategory": manifest.get("targetCategory"),
            },
        )
        if output["status"] == "COMPLETED":
            proposal_id = str(uuid.uuid4())
            with self.database.transaction() as connection:
                proposal_id, created = self.repository.create_proposal_from_result(
                    connection,
                    proposal_id=proposal_id,
                    ai_result_id=output["result"]["id"],
                    case_id=task["interviewCaseId"],
                    question_set_id=manifest["questionSetId"],
                    target_category=manifest["targetCategory"],
                    mode=manifest["mode"],
                    source_fingerprint=manifest["sourceFingerprint"],
                )
                if created:
                    append_audit(
                        connection,
                        actor_type="SYSTEM",
                        action="QUESTION_ADDITION_GENERATED",
                        entity_type="QUESTION_ADDITION_PROPOSAL",
                        entity_id=proposal_id,
                        metadata={
                            "taskId": task_id,
                            "questionSetId": manifest["questionSetId"],
                            "targetCategory": manifest["targetCategory"],
                        },
                    )
            output["proposalId"] = proposal_id
            output["proposal"] = self.repository.get_proposal(
                task["interviewCaseId"], manifest["questionSetId"], proposal_id
            )
        elif output["status"] == "FAILED":
            with self.database.transaction() as connection:
                append_audit(
                    connection,
                    actor_type="SYSTEM",
                    action="QUESTION_ADDITION_FAILED",
                    entity_type="AI_TASK",
                    entity_id=task_id,
                    metadata={"errorCode": output.get("errorCode")},
                )
        return output

    def provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        manifest = task["inputManifest"]
        case_id = task["interviewCaseId"]
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT c.candidate_code, c.full_name,
                          j.position_title, j.target_level
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id
                   WHERE ic.id=?""",
                (case_id,),
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            documents = []
            for reference in manifest.get("documents", []):
                row = connection.execute(
                    """SELECT document_type, id, version_no,
                              extracted_text, content_sha256
                       FROM documents
                       WHERE id=? AND interview_case_id=? AND is_ai_eligible=1""",
                    (reference.get("id"), case_id),
                ).fetchone()
                if (
                    row is None
                    or row["document_type"] != reference.get("document_type")
                    or row["version_no"] != reference.get("version_no")
                    or row["content_sha256"] != reference.get("content_sha256")
                ):
                    raise StateConflict("Question addition document snapshot no longer matches")
                documents.append(
                    {
                        "documentType": row["document_type"],
                        "documentId": row["id"],
                        "versionNo": row["version_no"],
                        "contentSha256": row["content_sha256"],
                        "sanitizedText": sanitize_text(
                            row["extracted_text"] or "", known_names=(case["full_name"],)
                        ),
                    }
                )
        return {
            "schemaVersion": "ai.input.v1",
            "operation": "GENERATE_QUESTION_ADDITION",
            "candidateCode": case["candidate_code"],
            "job": {
                "positionTitle": case["position_title"],
                "targetLevel": case["target_level"],
            },
            "mode": manifest["mode"],
            "questionSetId": manifest["questionSetId"],
            "targetCategory": manifest["targetCategory"],
            "prompt": sanitize_text(manifest.get("prompt") or "", known_names=(case["full_name"],)) or None,
            "documents": documents,
            "existingQuestions": sanitize_structure(
                manifest.get("existingQuestions", []), known_names=(case["full_name"],)
            ),
        }

    def get_proposal(
        self, case_id: str, question_set_id: str, proposal_id: str
    ) -> dict[str, Any]:
        return self.repository.get_proposal(case_id, question_set_id, proposal_id)

    def list_active_proposals(
        self,
        case_id: str,
        question_set_id: str,
        target_category: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.list_active_proposals(
            case_id, question_set_id, target_category
        )

    def discard_proposal(
        self, case_id: str, question_set_id: str, proposal_id: str
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._lock_check(connection, case_id, question_set_id)
            changed = self.repository.mark_discarded(
                connection,
                case_id=case_id,
                question_set_id=question_set_id,
                proposal_id=proposal_id,
            )
            if changed:
                append_audit(
                    connection,
                    actor_type="COMMITTEE",
                    action="QUESTION_ADDITION_DISCARDED",
                    entity_type="QUESTION_ADDITION_PROPOSAL",
                    entity_id=proposal_id,
                    metadata={"questionSetId": question_set_id},
                )
        return self.get_proposal(case_id, question_set_id, proposal_id)

    def apply_proposal(
        self,
        case_id: str,
        question_set_id: str,
        proposal_id: str,
        expected_question_set_updated_at: str,
        expected_source_fingerprint: str,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            question_set = self._lock_check(connection, case_id, question_set_id)
            if question_set["updated_at"] != expected_question_set_updated_at:
                raise StateConflict("Question addition proposal is stale")
            source = self._source_from_connection(connection, case_id, question_set_id)
            current_fingerprint = _fingerprint(source["sourceFingerprintInput"])
            if current_fingerprint != expected_source_fingerprint:
                raise StateConflict("Question addition proposal source is stale")
            proposal = connection.execute(
                """SELECT p.*, r.payload_json
                   FROM question_addition_proposals p
                   JOIN ai_results r ON r.id=p.ai_result_id
                   WHERE p.id=? AND p.interview_case_id=? AND p.question_set_id=?""",
                (proposal_id, case_id, question_set_id),
            ).fetchone()
            if proposal is None:
                raise ResourceNotFound("Question addition proposal not found")
            if proposal["status"] != "PROPOSED":
                raise StateConflict("Question addition proposal is no longer proposed")
            payload = json.loads(proposal["payload_json"])
            self.tasks.schemas.validate(
                "QUESTION_ADDITION",
                payload,
                context={
                    "questionSetId": question_set_id,
                    "targetCategory": proposal["target_category"],
                },
            )
            if payload["mode"] != proposal["mode"]:
                raise ValidationError("Question addition proposal mode does not match task")
            questions = source["existingQuestions"]
            if len(questions) >= 30:
                raise StateConflict("Question Set cannot contain more than 30 questions")
            addition = payload["question"]
            new_question = {
                "id": str(uuid.uuid4()),
                "displayOrder": len(questions) + 1,
                "questionText": addition["questionText"],
                "competencyKey": addition["competencyKey"],
                "sourceKind": addition["sourceKind"],
                "questionCategory": proposal["target_category"],
                "purpose": addition["purpose"],
                "nextStepObjective": addition["nextStepObjective"],
                "questionType": addition["questionType"],
                "difficulty": addition["difficulty"],
                "expectedEvidence": addition["expectedEvidence"],
                "rubric": addition["rubric"],
                "isRequired": addition["isRequired"],
                "estimatedSeconds": addition["estimatedSeconds"],
            }
            normalized = _validate_questions(
                questions + [new_question], allow_expanded=True
            )
            _insert_questions(connection, question_set_id, [normalized[-1]])
            connection.execute(
                """UPDATE question_sets
                   SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=?""",
                (question_set_id,),
            )
            self.repository.mark_applied(
                connection,
                case_id=case_id,
                question_set_id=question_set_id,
                proposal_id=proposal_id,
                question_id=new_question["id"],
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_ADDITION_APPLIED",
                entity_type="QUESTION_ADDITION_PROPOSAL",
                entity_id=proposal_id,
                metadata={
                    "questionSetId": question_set_id,
                    "questionId": new_question["id"],
                    "targetCategory": proposal["target_category"],
                    "questionCount": len(normalized),
                    "sourceFingerprint": expected_source_fingerprint,
                },
            )
        return {
            "question": new_question,
            "proposal": self.get_proposal(case_id, question_set_id, proposal_id),
        }

    def _load_source(self, case_id: str, question_set_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            return self._source_from_connection(connection, case_id, question_set_id)

    def _source_from_connection(
        self, connection, case_id: str, question_set_id: str
    ) -> dict[str, Any]:
        row = connection.execute(
            """SELECT qs.id, qs.status, qs.updated_at, qs.interview_case_id
               FROM question_sets qs
               WHERE qs.id=? AND qs.interview_case_id=?""",
            (question_set_id, case_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound("Question Set not found")
        self._assert_unlocked(connection, case_id, row["status"])
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
        if {document["document_type"] for document in documents} != {"JD", "CV"}:
            raise StateConflict("Confirmed current JD and CV are required")
        questions = [
            _question_from_row(question)
            for question in connection.execute(
                "SELECT * FROM questions WHERE question_set_id=? ORDER BY display_order",
                (question_set_id,),
            ).fetchall()
        ]
        source_fingerprint_input = {
            "questionSetId": question_set_id,
            "questionSetUpdatedAt": row["updated_at"],
            "documents": documents,
            "existingQuestions": questions,
        }
        return {
            "questionSetUpdatedAt": row["updated_at"],
            "documents": documents,
            "existingQuestions": questions,
            "sourceFingerprintInput": source_fingerprint_input,
        }

    def _lock_check(self, connection, case_id: str, question_set_id: str):
        row = connection.execute(
            """SELECT id, status, updated_at FROM question_sets
               WHERE id=? AND interview_case_id=?""",
            (question_set_id, case_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound("Question Set not found")
        self._assert_unlocked(connection, case_id, row["status"])
        return row

    @staticmethod
    def _assert_unlocked(connection, case_id: str, question_set_status: str) -> None:
        if question_set_status not in {"DRAFT", "GENERATED"}:
            raise StateConflict("Question Set is locked")
        attempt = connection.execute(
            "SELECT 1 FROM assessment_attempts WHERE interview_case_id=? LIMIT 1",
            (case_id,),
        ).fetchone()
        if attempt is not None:
            raise StateConflict("Question Set is locked after assessment start")

    @staticmethod
    def _validate_request(
        target_category: str, mode: str, prompt: str | None
    ) -> str | None:
        if target_category not in _CATEGORIES:
            raise ValidationError("Unsupported question addition category")
        if mode not in _MODES:
            raise ValidationError("Unsupported question addition mode")
        if prompt is not None and not isinstance(prompt, str):
            raise ValidationError("Question addition prompt must be text")
        normalized = prompt.strip() if isinstance(prompt, str) else None
        if mode == "USER_PROMPT":
            if not normalized:
                raise ValidationError("Question addition prompt is required")
            if len(normalized) > MAX_ADDITION_PROMPT_CHARS:
                raise ValidationError("Question addition prompt is too long")
            return normalized
        if normalized:
            raise ValidationError("AUTO_GROUP question addition does not accept a prompt")
        return None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


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
