from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.ai.provider import AIProvider
from app.ai.redaction import sanitize_text
from app.ai.schemas import SchemaRegistry
from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict
from app.services.ai_task_service import AITaskService
from app.services.question_service import QuestionService


class QuestionGenerationService:
    def __init__(self, database: Database, schema_root: Path) -> None:
        self.database = database
        self.tasks = AITaskService(database, SchemaRegistry(schema_root))
        self.questions = QuestionService(database)

    def request(
        self,
        case_id: str,
        *,
        idempotency_key: str,
        question_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT ic.status, j.id job_id, j.updated_at job_updated_at
                   FROM interview_cases ic JOIN jobs j ON j.id=ic.job_id
                   WHERE ic.id=?""", (case_id,),
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            documents = connection.execute(
                """SELECT id, document_type, version_no, content_sha256
                   FROM documents WHERE interview_case_id=? AND is_current=1
                     AND is_ai_eligible=1 ORDER BY document_type""", (case_id,),
            ).fetchall()
        if case["status"] not in {"DOCUMENTS_READY", "QUESTION_GENERATION_FAILED"}:
            raise StateConflict("Case is not ready for question generation")
        if {row["document_type"] for row in documents} != {"JD", "CV"}:
            raise StateConflict("Confirmed current JD and CV are required")
        manifest = {
            "schemaVersion": "ai-task-manifest.v1", "interviewCaseId": case_id,
            "jobId": case["job_id"], "jobUpdatedAt": case["job_updated_at"],
            "documents": [dict(row) for row in documents],
            "questionPolicy": question_policy or {
                "maxQuestions": 8, "durationSeconds": 900,
                "standardized": True, "situational": True,
                "cvVerification": True, "gapConflict": True,
            },
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }
        fingerprint = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.tasks.enqueue(
            case_id, "GENERATE_QUESTIONS", input_manifest=manifest,
            input_fingerprint=fingerprint, idempotency_key=idempotency_key,
        )

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        output = self.tasks.process(
            task_id, provider,
            payload_override=self.provider_payload(task),
        )
        if output["status"] == "COMPLETED":
            with self.database.connection() as connection:
                status = connection.execute(
                    "SELECT status FROM interview_cases WHERE id=?",
                    (task["interviewCaseId"],),
                ).fetchone()["status"]
            if status == "QUESTIONS_GENERATING":
                self.questions.materialize_generated(
                    task["interviewCaseId"],
                    output["result"]["payload"],
                    document_refs=task["inputManifest"].get("documents", []),
                )
        return output

    def provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        case_id = task["interviewCaseId"]
        document_refs = task["inputManifest"].get("documents", [])
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT c.candidate_code, c.full_name, j.position_title, j.target_level
                   FROM interview_cases ic JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id WHERE ic.id=?""", (case_id,),
            ).fetchone()
            documents = []
            for reference in document_refs:
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
                    raise StateConflict("Question-generation document snapshot no longer matches")
                documents.append(row)
        if case is None:
            raise ResourceNotFound("Interview case not found")
        return {
            "schemaVersion": "ai.input.v1", "operation": "GENERATE_QUESTIONS",
            "candidateCode": case["candidate_code"],
            "job": {"positionTitle": case["position_title"], "targetLevel": case["target_level"]},
            "documents": [
                {"documentType": row["document_type"], "documentId": row["id"],
                 "versionNo": row["version_no"],
                 "sanitizedText": sanitize_text(
                     row["extracted_text"], known_names=(case["full_name"],)
                 ),
                 "contentSha256": row["content_sha256"]}
                for row in documents
            ],
        }
