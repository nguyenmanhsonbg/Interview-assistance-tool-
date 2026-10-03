from __future__ import annotations

import re
import uuid
from typing import Any

from app.ai.provider import AIProvider, ProviderError
from app.ai.schemas import SchemaRegistry
from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.repositories.ai_tasks import AITaskRepository
from app.repositories.audit import append_audit


_TASK_CONFIG = {
    "GENERATE_QUESTIONS": ("QUESTION_GENERATION", "question_generation", "question-generation.v1"),
    "EVALUATE_ASSESSMENT": ("ANSWER_EVALUATION", "answer_evaluation", "answer-evaluation.v1"),
    "GENERATE_BRIEF": ("INTERVIEW_BRIEF", "answer_evaluation", "answer-evaluation.v1"),
    "SUGGEST_FOLLOW_UP": ("FOLLOW_UP", "follow_up_question", "follow-up.v1"),
}


class AITaskService:
    def __init__(self, database: Database, schemas: SchemaRegistry) -> None:
        self.database = database
        self.schemas = schemas
        self.repository = AITaskRepository(database)

    def enqueue(self, case_id: str, task_type: str, *, input_manifest: dict[str, Any], input_fingerprint: str, idempotency_key: str, assessment_attempt_id: str | None = None, provider: str | None = None, model: str | None = None, max_retry: int = 1) -> dict[str, Any]:
        if task_type not in _TASK_CONFIG:
            raise ValidationError("Unsupported AI task type")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", input_fingerprint):
            raise ValidationError("inputFingerprint must be a SHA-256 hex digest")
        if not idempotency_key.strip():
            raise ValidationError("idempotencyKey is required")
        existing = self.repository.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing["inputFingerprint"] != input_fingerprint or existing["taskType"] != task_type or existing["interviewCaseId"] != case_id:
                raise StateConflict("Idempotency key was already used for different input")
            return existing

        result_type, prompt_key, schema_version = _TASK_CONFIG[task_type]
        task_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            case = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if task_type == "GENERATE_QUESTIONS":
                if case["status"] not in {"DOCUMENTS_READY", "QUESTION_GENERATION_FAILED"}:
                    raise StateConflict("Case is not ready for question generation")
                connection.execute("UPDATE interview_cases SET status='QUESTIONS_GENERATING', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (case_id,))
            self.repository.insert(connection, task_id=task_id, case_id=case_id,
                assessment_attempt_id=assessment_attempt_id, task_type=task_type,
                idempotency_key=idempotency_key, input_fingerprint=input_fingerprint.lower(),
                input_manifest=input_manifest, provider=provider, model=model,
                prompt_key=prompt_key, prompt_version=schema_version,
                schema_version=schema_version, max_retry=max_retry)
            append_audit(connection, actor_type="SYSTEM", action="AI_TASK_CREATED",
                entity_type="AI_TASK", entity_id=task_id,
                metadata={"taskType": task_type, "resultType": result_type})
        return self.repository.get(task_id)

    def process(self, task_id: str, provider: AIProvider, *, payload_override: dict[str, Any] | None = None, context_override: dict[str, Any] | None = None) -> dict[str, Any]:
        task = self.repository.get(task_id)
        if task["status"] == "COMPLETED":
            return task
        if task["status"] not in {"PENDING", "PENDING_RETRY"}:
            raise StateConflict("AI task is not pending")
        with self.database.transaction() as connection:
            self.repository.mark_running(connection, task_id)
        try:
            payload = payload_override or task["inputManifest"].get("payload", task["inputManifest"])
            if task["status"] == "PENDING_RETRY":
                payload = dict(payload)
                payload["repairInstruction"] = (
                    "Return one corrected JSON object that strictly matches the requested schema."
                )
            if task["taskType"] == "GENERATE_QUESTIONS":
                output = provider.generate_questions(payload)
                operation = result_type = "QUESTION_GENERATION"
            elif task["taskType"] in {"EVALUATE_ASSESSMENT", "GENERATE_BRIEF"}:
                output = provider.evaluate_answers(payload)
                operation = "ANSWER_EVALUATION"
                result_type = "ANSWER_EVALUATION" if task["taskType"] == "EVALUATE_ASSESSMENT" else "INTERVIEW_BRIEF"
            else:
                output = provider.suggest_follow_up(payload)
                operation = result_type = "FOLLOW_UP"
            context = context_override or task["inputManifest"].get("context")
            self.schemas.validate(operation, output, context=context)
        except ProviderError as error:
            self._record_error(task, error.code, str(error), retryable=error.retryable)
            return self.repository.get(task_id)
        except ValidationError as error:
            self._record_error(task, "AI_SCHEMA_VALIDATION_FAILED", str(error), retryable=True)
            return self.repository.get(task_id)
        except Exception:
            self._record_error(task, "AI_PROVIDER_UNEXPECTED_ERROR", "AI provider failed unexpectedly", retryable=False)
            return self.repository.get(task_id)

        with self.database.transaction() as connection:
            result_id = self.repository.complete(connection, task, result_type=result_type, payload=output)
            append_audit(connection, actor_type="SYSTEM", action="AI_TASK_COMPLETED",
                entity_type="AI_TASK", entity_id=task_id,
                metadata={"resultId": result_id, "resultType": result_type})
        return self.repository.get(task_id)

    def recover_interrupted(self) -> dict[str, list[str]]:
        pending_retry: list[str] = []
        failed: list[str] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                """SELECT id, interview_case_id, task_type, retry_count, max_retry
                   FROM ai_tasks WHERE status='RUNNING'"""
            ).fetchall()
            for row in rows:
                if row["retry_count"] < row["max_retry"]:
                    connection.execute("UPDATE ai_tasks SET status='PENDING_RETRY', retry_count=retry_count+1, error_code='AI_TASK_INTERRUPTED', error_message='Recovered after restart' WHERE id=?", (row["id"],))
                    append_audit(
                        connection, actor_type="SYSTEM", action="AI_TASK_RETRIED",
                        entity_type="AI_TASK", entity_id=row["id"],
                        metadata={"errorCode": "AI_TASK_INTERRUPTED"},
                    )
                    pending_retry.append(row["id"])
                else:
                    connection.execute("UPDATE ai_tasks SET status='FAILED', error_code='AI_TASK_INTERRUPTED', error_message='Retry limit reached', finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (row["id"],))
                    self._apply_terminal_failure(connection, row)
                    append_audit(
                        connection, actor_type="SYSTEM", action="AI_TASK_FAILED",
                        entity_type="AI_TASK", entity_id=row["id"],
                        metadata={"errorCode": "AI_TASK_INTERRUPTED", "retryable": False},
                    )
                    failed.append(row["id"])
        return {"pendingRetry": pending_retry, "failed": failed}

    def fail_materialization(self, task_id: str) -> dict[str, Any]:
        task = self.repository.get(task_id)
        if task["status"] != "COMPLETED":
            self._record_error(
                task,
                "AI_PROCESSING_FAILED",
                "AI task processing failed unexpectedly",
                retryable=False,
            )
            return self.repository.get(task_id)
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE ai_tasks SET error_code='AI_MATERIALIZATION_FAILED',
                   error_message='Validated AI output could not be materialized' WHERE id=?""",
                (task_id,),
            )
            self._apply_terminal_failure(
                connection,
                {
                    "task_type": task["taskType"],
                    "interview_case_id": task["interviewCaseId"],
                },
            )
            append_audit(
                connection, actor_type="SYSTEM", action="AI_TASK_FAILED",
                entity_type="AI_TASK", entity_id=task_id,
                metadata={"errorCode": "AI_MATERIALIZATION_FAILED", "retryable": False},
            )
        return self.repository.get(task_id)

    def _record_error(self, task: dict[str, Any], code: str, message: str, *, retryable: bool) -> None:
        with self.database.transaction() as connection:
            self.repository.mark_error(connection, task["id"], retryable=retryable, error_code=code, error_message=message)
            failed = connection.execute(
                "SELECT status FROM ai_tasks WHERE id=?", (task["id"],)
            ).fetchone()["status"] == "FAILED"
            if failed:
                self._apply_terminal_failure(
                    connection,
                    {
                        "task_type": task["taskType"],
                        "interview_case_id": task["interviewCaseId"],
                    },
                )
            append_audit(
                connection,
                actor_type="SYSTEM",
                action="AI_TASK_FAILED" if failed else "AI_TASK_RETRIED",
                entity_type="AI_TASK",
                entity_id=task["id"],
                metadata={"errorCode": code, "retryable": retryable},
            )

    @staticmethod
    def _apply_terminal_failure(connection, task: Any) -> None:
        task_type = task["task_type"]
        case_id = task["interview_case_id"]
        if task_type == "GENERATE_QUESTIONS":
            connection.execute(
                """UPDATE interview_cases SET status='QUESTION_GENERATION_FAILED',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
        elif task_type in {"EVALUATE_ASSESSMENT", "GENERATE_BRIEF"}:
            connection.execute(
                """UPDATE interview_cases SET status='AI_ANALYSIS_FAILED',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
