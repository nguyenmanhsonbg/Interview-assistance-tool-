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
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.domain.rules import require_text
from app.infrastructure.case_locks import case_mutation_lock
from app.repositories.audit import append_audit
from app.services.ai_task_service import AITaskService


_MUTABLE_CASE_STATES = {
    "DRAFT",
    "DOCUMENT_PARSE_FAILED",
    "DOCUMENTS_READY",
    "QUESTIONS_GENERATING",
    "QUESTION_GENERATION_FAILED",
    "QUESTIONS_GENERATED",
    "QUESTIONS_APPROVED",
    "READY_FOR_ASSESSMENT",
}


class JobLevelService:
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

    def request_for_confirmed_jd(
        self, case_id: str, *, retry: bool = False
    ) -> dict[str, Any] | None:
        with case_mutation_lock(case_id):
            row = self._current_jd(case_id)
            if row is None:
                with self.database.connection() as connection:
                    case = connection.execute(
                        "SELECT id FROM interview_cases WHERE id=?", (case_id,)
                    ).fetchone()
                if case is None:
                    raise ResourceNotFound("Interview case not found")
                raise StateConflict("Confirmed current JD is required")
            if row["case_status"] not in _MUTABLE_CASE_STATES:
                raise StateConflict("Job level cannot be changed after the assessment starts")

            manifest = self._manifest(row)
            fingerprint = _fingerprint(manifest)
            existing = self.tasks.repository.find_by_case_task_fingerprint(
                case_id, "EXTRACT_JOB_LEVEL", fingerprint
            )
            if existing is not None:
                if existing["status"] in {"PENDING", "PENDING_RETRY", "RUNNING", "COMPLETED"}:
                    return existing
                if not retry:
                    return existing
                if existing["status"] != "FAILED":
                    raise StateConflict("Job level extraction is not retryable")
            elif retry:
                raise StateConflict("No failed extraction exists for the current JD")
            elif row["target_level_status"] == "READY":
                return None
            elif row["target_level_status"] == "EXTRACTING":
                raise StateConflict("Job level extraction is already in progress")

            idempotency_key = (
                f"job-level:{case_id}:{row['document_id']}:{row['document_version']}"
                f":{row['document_hash']}"
            )
            if retry:
                idempotency_key += f":retry:{uuid.uuid4()}"
            return self.tasks.enqueue(
                case_id,
                "EXTRACT_JOB_LEVEL",
                input_manifest=manifest,
                input_fingerprint=fingerprint,
                idempotency_key=idempotency_key,
                provider=self.provider_name,
                model=self.model_name,
            )

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        try:
            payload = self.provider_payload(task)
        except StateConflict:
            self._mark_stale(task)
            return self.tasks.repository.get(task_id)

        output = self.tasks.process(task_id, provider, payload_override=payload)
        if output["status"] == "COMPLETED":
            self._materialize(task, output["result"]["payload"])
            return self.tasks.repository.get(task_id)
        return output

    def provider_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        manifest_document = task.get("inputManifest", {}).get("document", {})
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT ic.id case_id, j.id job_id, j.position_title,
                          c.full_name, d.id document_id, d.version_no document_version,
                          d.content_sha256 document_hash, d.extracted_text,
                          d.is_current, d.is_ai_eligible
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id
                   JOIN documents d ON d.interview_case_id=ic.id
                   WHERE ic.id=? AND d.document_type='JD' AND d.is_current=1""",
                (task["interviewCaseId"],),
            ).fetchone()
        if row is None or not row["is_ai_eligible"]:
            raise StateConflict("Question-generation document snapshot no longer matches")
        if (
            row["document_id"] != manifest_document.get("id")
            or row["document_version"] != manifest_document.get("versionNo")
            or row["document_hash"] != manifest_document.get("contentSha256")
        ):
            raise StateConflict("Job-level extraction document snapshot no longer matches")
        sanitized = sanitize_text(row["extracted_text"], known_names=(row["full_name"],))
        return {
            "schemaVersion": "ai.input.v1",
            "operation": "EXTRACT_JOB_LEVEL",
            "interviewCaseId": row["case_id"],
            "job": {"id": row["job_id"], "positionTitle": row["position_title"]},
            "document": {
                "documentId": row["document_id"],
                "versionNo": row["document_version"],
                "contentSha256": row["document_hash"],
                "sanitizedText": sanitized,
            },
        }

    def _current_jd(self, case_id: str):
        with self.database.connection() as connection:
            return connection.execute(
                """SELECT ic.status case_status, ic.job_id,
                          j.position_title, j.updated_at job_updated_at,
                          j.target_level_status,
                          d.id document_id, d.version_no document_version,
                          d.content_sha256 document_hash, d.extracted_text,
                          c.full_name
                   FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id
                   JOIN documents d ON d.interview_case_id=ic.id
                   WHERE ic.id=? AND d.document_type='JD'
                     AND d.is_current=1 AND d.is_ai_eligible=1""",
                (case_id,),
            ).fetchone()

    @staticmethod
    def _manifest(row) -> dict[str, Any]:
        sanitized = sanitize_text(row["extracted_text"], known_names=(row["full_name"],))
        return {
            "schemaVersion": "ai-task-manifest.v1",
            "interviewCaseId": row["case_id"] if "case_id" in row.keys() else None,
            "jobId": row["job_id"],
            "jobUpdatedAt": row["job_updated_at"],
            "document": {
                "id": row["document_id"],
                "documentId": row["document_id"],
                "versionNo": row["document_version"],
                "contentSha256": row["document_hash"],
                "sanitizedText": sanitized,
            },
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }

    def _materialize(self, task: dict[str, Any], payload: dict[str, Any]) -> None:
        level = require_text(payload.get("targetLevel"), "targetLevel")
        confidence = payload.get("confidence")
        document = task.get("inputManifest", {}).get("document", {})
        with case_mutation_lock(task["interviewCaseId"]):
            with self.database.transaction() as connection:
                row = connection.execute(
                    """SELECT ic.status case_status, j.id job_id,
                              j.target_level_status, d.id document_id,
                              d.version_no document_version, d.content_sha256 document_hash,
                              d.is_current, d.is_ai_eligible
                       FROM interview_cases ic
                       JOIN jobs j ON j.id=ic.job_id
                       JOIN documents d ON d.interview_case_id=ic.id
                       WHERE ic.id=? AND d.document_type='JD' AND d.is_current=1""",
                    (task["interviewCaseId"],),
                ).fetchone()
                current = (
                    row is not None
                    and row["is_current"]
                    and row["is_ai_eligible"]
                    and row["job_id"] == task["inputManifest"].get("jobId")
                    and row["target_level_status"] == "EXTRACTING"
                    and row["document_id"] == document.get("id")
                    and row["document_version"] == document.get("versionNo")
                    and row["document_hash"] == document.get("contentSha256")
                    and row["case_status"] in _MUTABLE_CASE_STATES
                )
                if not current:
                    if row is not None and row["target_level_status"] == "EXTRACTING":
                        connection.execute(
                            """UPDATE jobs SET target_level_status='PENDING',
                               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                               WHERE id=? AND target_level_status='EXTRACTING'""",
                            (task["inputManifest"].get("jobId"),),
                        )
                    append_audit(
                        connection, actor_type="SYSTEM", action="JOB_LEVEL_EXTRACTION_STALE",
                        entity_type="AI_TASK", entity_id=task["id"],
                        metadata={"documentId": document.get("id")},
                    )
                    return
                connection.execute(
                    """UPDATE jobs SET target_level=?, target_level_status='READY',
                       target_level_source='JD_AI', target_level_confidence=?,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (level, confidence, row["job_id"]),
                )
                append_audit(
                    connection, actor_type="SYSTEM", action="JOB_LEVEL_EXTRACTION_COMPLETED",
                    entity_type="JOB", entity_id=row["job_id"],
                    metadata={
                        "taskId": task["id"], "documentId": document.get("id"),
                        "confidence": confidence,
                    },
                )

    def _mark_stale(self, task: dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE ai_tasks SET status='FAILED', error_code='AI_STALE_INPUT',
                   error_message='JD snapshot no longer matches',
                   finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (task["id"],),
            )
            connection.execute(
                """UPDATE jobs SET target_level_status='PENDING',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=(SELECT job_id FROM interview_cases WHERE id=?)
                     AND target_level_status='EXTRACTING'""",
                (task["interviewCaseId"],),
            )
            append_audit(
                connection, actor_type="SYSTEM", action="AI_TASK_FAILED",
                entity_type="AI_TASK", entity_id=task["id"],
                metadata={"errorCode": "AI_STALE_INPUT", "retryable": False},
            )


def _fingerprint(manifest: dict[str, Any]) -> str:
    fingerprint_manifest = dict(manifest)
    fingerprint_manifest.pop("jobUpdatedAt", None)
    return hashlib.sha256(
        json.dumps(
            fingerprint_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
