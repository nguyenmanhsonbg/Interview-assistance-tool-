from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class AITaskRepository(RepositoryBase):
    def pending_ids(self) -> list[str]:
        return [
            row["id"]
            for row in self.query_all(
                """SELECT id FROM ai_tasks WHERE status IN ('PENDING','PENDING_RETRY')
                   ORDER BY created_at, id"""
            )
        ]

    def recoverable_materialization_ids(self) -> list[str]:
        return [
            row["id"]
            for row in self.query_all(
                """SELECT t.id FROM ai_tasks t
                   JOIN interview_cases ic ON ic.id=t.interview_case_id
                   WHERE t.status='COMPLETED' AND t.error_code IS NULL AND (
                     (t.task_type='GENERATE_QUESTIONS' AND ic.status='QUESTIONS_GENERATING')
                     OR
                     (t.task_type IN ('EVALUATE_ASSESSMENT','GENERATE_BRIEF')
                      AND ic.status='AI_ANALYZING')
                     OR
                     (t.assessment_snapshot_id IS NOT NULL
                      AND ic.refined_flow_status='AI_ANALYZING')
                   )
                   ORDER BY t.created_at, t.id"""
            )
        ]
    def get(self, task_id: str) -> dict[str, Any]:
        row = self.query_one("SELECT * FROM ai_tasks WHERE id=?", (task_id,))
        if row is None:
            raise ResourceNotFound("AI task not found")
        task = _task_dict(row)
        result = self.query_one("SELECT * FROM ai_results WHERE ai_task_id=?", (task_id,))
        if result is not None:
            task["result"] = _result_dict(result)
        return task

    def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT id FROM ai_tasks WHERE idempotency_key=?", (key,))
        return None if row is None else self.get(row["id"])

    def current_result(self, case_id: str, result_type: str) -> dict[str, Any] | None:
        row = self.query_one(
            """SELECT * FROM ai_results
               WHERE interview_case_id=? AND result_type=? AND is_current=1""",
            (case_id, result_type),
        )
        return None if row is None else _result_dict(row)

    def insert(self, connection: sqlite3.Connection, *, task_id: str, case_id: str, assessment_attempt_id: str | None, assessment_snapshot_id: str | None, task_type: str, idempotency_key: str, input_fingerprint: str, input_manifest: dict[str, Any], provider: str | None, model: str | None, prompt_key: str, prompt_version: str, schema_version: str, max_retry: int) -> None:
        connection.execute(
            """INSERT INTO ai_tasks(
                id, interview_case_id, assessment_attempt_id, assessment_snapshot_id, task_type,
                idempotency_key, input_fingerprint, input_manifest_json,
                provider, model, prompt_key, prompt_version, schema_version, max_retry
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, case_id, assessment_attempt_id, assessment_snapshot_id, task_type, idempotency_key,
             input_fingerprint, json.dumps(input_manifest, ensure_ascii=False, separators=(",", ":")),
             provider, model, prompt_key, prompt_version, schema_version, max_retry),
        )

    def mark_running(self, connection: sqlite3.Connection, task_id: str) -> None:
        connection.execute(
            """UPDATE ai_tasks SET status='RUNNING', error_code=NULL,
               error_message=NULL, started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=?""", (task_id,),
        )

    def mark_error(self, connection: sqlite3.Connection, task_id: str, *, retryable: bool, error_code: str, error_message: str) -> None:
        row = connection.execute("SELECT retry_count, max_retry FROM ai_tasks WHERE id=?", (task_id,)).fetchone()
        next_retry = row["retry_count"] + 1
        pending_retry = retryable and row["retry_count"] < row["max_retry"]
        connection.execute(
            """UPDATE ai_tasks SET status=?, retry_count=?, error_code=?,
               error_message=?, finished_at=CASE WHEN ?='FAILED'
               THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END WHERE id=?""",
            ("PENDING_RETRY" if pending_retry else "FAILED", next_retry,
             error_code, error_message[:1000], "PENDING_RETRY" if pending_retry else "FAILED", task_id),
        )

    def complete(self, connection: sqlite3.Connection, task: dict[str, Any], *, result_type: str, payload: dict[str, Any]) -> str:
        previous = connection.execute(
            """SELECT id, version_no FROM ai_results
               WHERE interview_case_id=? AND result_type=? AND is_current=1""",
            (task["interviewCaseId"], result_type),
        ).fetchone()
        version = 1 if previous is None else previous["version_no"] + 1
        if previous is not None:
            connection.execute("UPDATE ai_results SET is_current=0 WHERE id=?", (previous["id"],))
        result_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO ai_results(
                id, ai_task_id, interview_case_id, assessment_attempt_id, assessment_snapshot_id,
                result_type, version_no, supersedes_result_id, payload_json,
                confidence, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (result_id, task["id"], task["interviewCaseId"], task["assessmentAttemptId"], task["assessmentSnapshotId"],
             result_type, version, None if previous is None else previous["id"],
             json.dumps(payload, ensure_ascii=False, separators=(",", ":")), payload.get("confidence")),
        )
        connection.execute(
            """UPDATE ai_tasks SET status='COMPLETED', error_code=NULL,
               error_message=NULL, finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
            (task["id"],),
        )
        return result_id


def _task_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "interviewCaseId": row["interview_case_id"],
        "assessmentAttemptId": row["assessment_attempt_id"], "assessmentSnapshotId": row["assessment_snapshot_id"], "taskType": row["task_type"],
        "status": row["status"], "idempotencyKey": row["idempotency_key"],
        "inputFingerprint": row["input_fingerprint"], "inputManifest": json.loads(row["input_manifest_json"]),
        "provider": row["provider"], "model": row["model"], "promptKey": row["prompt_key"],
        "promptVersion": row["prompt_version"], "schemaVersion": row["schema_version"],
        "retryCount": row["retry_count"], "maxRetry": row["max_retry"],
        "errorCode": row["error_code"], "errorMessage": row["error_message"],
        "createdAt": row["created_at"], "startedAt": row["started_at"], "finishedAt": row["finished_at"],
    }


def _result_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "aiTaskId": row["ai_task_id"], "resultType": row["result_type"],
        "assessmentSnapshotId": row["assessment_snapshot_id"],
        "versionNo": row["version_no"], "payload": json.loads(row["payload_json"]),
        "confidence": row["confidence"], "isCurrent": bool(row["is_current"]), "createdAt": row["created_at"],
    }
