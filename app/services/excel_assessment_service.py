from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.infrastructure.excel_question_answer import (
    WORKBOOK_FORMAT_VERSION,
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from app.repositories.assessment_snapshots import AssessmentSnapshotRepository
from app.repositories.audit import append_audit
from app.repositories.questions import QuestionRepository


XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ExportedWorkbook:
    content: bytes
    filename: str
    content_type: str
    question_set_id: str

    @property
    def bytes(self) -> bytes:
        return self.content


class ExcelAssessmentService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.snapshots = AssessmentSnapshotRepository(database)
        self.questions = QuestionRepository(database)

    def export_question_set(self, case_id: str) -> ExportedWorkbook:
        question_set = self.questions.current_for_case(case_id)
        if question_set is None:
            raise ResourceNotFound("Question Set not found")
        if question_set["status"] not in {"GENERATED", "APPROVED"}:
            raise StateConflict("Question Set is not ready for Excel export")
        if len(question_set["questions"]) != 9:
            raise ValidationError("Question Set must contain exactly 9 questions")
        metadata = {
            "format_version": WORKBOOK_FORMAT_VERSION,
            "case_id": case_id,
            "question_set_id": question_set["id"],
            "question_set_version": str(question_set["versionNo"]),
            "duration_seconds": str(question_set["durationSeconds"]),
            "exported_at": _now_iso(),
        }
        questions = [
            {
                "questionId": question["id"],
                "displayOrder": question["displayOrder"],
                "questionText": question["questionText"],
                "competencyKey": question["competencyKey"],
                "sourceKind": question["sourceKind"],
                "questionCategory": question["questionCategory"],
                "purpose": question["purpose"],
                "nextStepObjective": question["nextStepObjective"],
                "questionType": question["questionType"],
                "difficulty": question["difficulty"],
                "expectedEvidence": question["expectedEvidence"],
                "rubric": question["rubric"],
                "isRequired": question["isRequired"],
                "estimatedSeconds": question["estimatedSeconds"] or 120,
                "answerText": "",
                "isAnswered": False,
            }
            for question in question_set["questions"]
        ]
        content = export_question_answer_workbook(metadata, questions)
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE interview_cases
                   SET refined_flow_status='QUESTIONS_EXPORTED',
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=?""",
                (case_id,),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="QUESTION_SET_EXPORTED",
                entity_type="QUESTION_SET",
                entity_id=question_set["id"],
                metadata={"versionNo": question_set["versionNo"]},
            )
        return ExportedWorkbook(
            content=content,
            filename=(
                f"question-answer-{case_id}-"
                f"{question_set['id']}-v{question_set['versionNo']}.xlsx"
            ),
            content_type=XLSX_CONTENT_TYPE,
            question_set_id=question_set["id"],
        )

    def import_answers(
        self, case_id: str, raw: bytes, *, idempotency_key: str
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("Idempotency key is required")
        if len(idempotency_key) > 256:
            raise ValidationError("Idempotency key is too long")
        workbook_hash = hashlib.sha256(raw).hexdigest()
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        existing = self.snapshots.find_by_idempotency(case_id, key_hash)
        if existing is not None:
            if existing["sourceFileSha256"] != workbook_hash:
                raise StateConflict("Idempotency key was already used for another workbook")
            return self._with_flow_status(existing)

        workbook = import_question_answer_workbook(raw)
        metadata = workbook.metadata
        if metadata["case_id"] != case_id:
            raise StateConflict("Workbook case_id does not match the target case")
        try:
            question_set = self.questions.get_set(metadata["question_set_id"])
        except ResourceNotFound as error:
            raise StateConflict("Workbook Question Set does not exist") from error
        if question_set["interviewCaseId"] != case_id:
            raise StateConflict("Workbook Question Set does not belong to the target case")
        if metadata["question_set_version"] != str(question_set["versionNo"]):
            raise StateConflict("Workbook Question Set version does not match")
        expected = {question["id"]: question for question in question_set["questions"]}
        imported = {question["questionId"]: question for question in workbook.questions}
        if set(imported) != set(expected):
            raise ValidationError("Workbook questions do not belong to the Question Set")
        for question_id, question in imported.items():
            if question["displayOrder"] != expected[question_id]["displayOrder"]:
                raise ValidationError("Workbook display order does not match the Question Set")

        document_manifest = question_set["questionPolicy"].get("sourceDocuments", [])
        if not isinstance(document_manifest, list):
            raise StateConflict("Question Set document provenance is invalid")
        normalized = json.dumps(
            {"metadata": metadata, "questions": workbook.questions},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        normalized_fingerprint = hashlib.sha256(normalized).hexdigest()
        answers = [
            {
                "answerId": str(uuid.uuid4()),
                "questionId": question["questionId"],
                "answerText": question["answerText"],
                "isAnswered": question["isAnswered"],
                "saveRevision": 0,
                "contentHash": hashlib.sha256(
                    question["answerText"].encode("utf-8")
                ).hexdigest(),
            }
            for question in workbook.questions
        ]
        with self.database.transaction() as connection:
            snapshot = self.snapshots.create_imported_snapshot(
                connection,
                case_id=case_id,
                question_set_id=question_set["id"],
                source_kind="EXCEL_IMPORT",
                source_file_sha256=workbook_hash,
                package_id=None,
                normalized_fingerprint=normalized_fingerprint,
                idempotency_key_hash=key_hash,
                document_manifest=document_manifest,
                questions=workbook.questions,
                answers=answers,
            )
            connection.execute(
                """UPDATE interview_cases
                   SET refined_flow_status='ANSWERS_IMPORTED',
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=?""",
                (case_id,),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="ASSESSMENT_ANSWERS_IMPORTED",
                entity_type="ASSESSMENT_SNAPSHOT",
                entity_id=snapshot["id"],
                metadata={
                    "questionSetId": question_set["id"],
                    "versionNo": snapshot["versionNo"],
                    "questionCount": len(workbook.questions),
                },
            )
        return self._with_flow_status(snapshot)

    def get_snapshot(
        self, case_id: str, snapshot_id: str | None = None
    ) -> dict[str, Any]:
        snapshot = (
            self.snapshots.get(snapshot_id)
            if snapshot_id is not None
            else self.snapshots.current_for_case(case_id)
        )
        if snapshot is None or snapshot["interviewCaseId"] != case_id:
            raise ResourceNotFound("Assessment snapshot not found")
        return self._with_flow_status(snapshot)

    def snapshot_manifest(self, snapshot_id: str) -> dict[str, Any]:
        return self.snapshots.payload(snapshot_id)

    def _with_flow_status(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        result = dict(snapshot)
        result["refinedFlowStatus"] = _refined_status(snapshot["status"])
        return result


def _refined_status(snapshot_status: str) -> str:
    return {
        "IMPORTED": "ANSWERS_IMPORTED",
        "AI_ANALYZING": "AI_ANALYZING",
        "AI_EVALUATED": "AI_EVALUATED",
        "AI_ANALYSIS_FAILED": "AI_ANALYSIS_FAILED",
    }.get(snapshot_status, "ANSWERS_IMPORTED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
