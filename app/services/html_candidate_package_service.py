from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.infrastructure.html_candidate_package import (
    HTML_CONTENT_TYPE,
    export_question_package,
    import_candidate_package,
)
from app.repositories.assessment_snapshots import AssessmentSnapshotRepository
from app.repositories.audit import append_audit
from app.repositories.questions import QuestionRepository


@dataclass(frozen=True)
class ExportedCandidatePackage:
    content: bytes
    filename: str
    content_type: str
    package_id: str
    question_set_id: str

    @property
    def bytes(self) -> bytes:
        return self.content


class HtmlCandidatePackageService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.snapshots = AssessmentSnapshotRepository(database)
        self.questions = QuestionRepository(database)

    def export_question_package(self, case_id: str) -> ExportedCandidatePackage:
        question_set = self.questions.current_for_case(case_id)
        if question_set is None:
            raise ResourceNotFound("Question Set not found")
        if question_set["status"] not in {"GENERATED", "APPROVED"}:
            raise StateConflict("Question Set is not ready for candidate export")
        questions = _candidate_questions(question_set)
        package_id = str(uuid.uuid4())
        manifest = {
            "formatVersion": "candidate-html.v1",
            "packageId": package_id,
            "questionSetId": question_set["id"],
            "questionSetVersion": question_set["versionNo"],
            "questionSetFingerprint": _question_fingerprint(questions),
            "durationSeconds": question_set["durationSeconds"],
            "questionCount": len(questions),
            "exportedAt": _now_iso(),
        }
        content = export_question_package(manifest, questions)
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
                metadata={
                    "versionNo": question_set["versionNo"],
                    "packageId": package_id,
                    "questionCount": len(questions),
                    "formatVersion": "candidate-html.v1",
                },
            )
        return ExportedCandidatePackage(
            content=content,
            filename=f"candidate-assessment-{package_id}.html",
            content_type=HTML_CONTENT_TYPE,
            package_id=package_id,
            question_set_id=question_set["id"],
        )

    def import_response(
        self, case_id: str, raw: bytes, *, idempotency_key: str
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("Idempotency key is required")
        if len(idempotency_key) > 256:
            raise ValidationError("Idempotency key is too long")
        source_file_sha256 = hashlib.sha256(raw).hexdigest()
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        existing = self.snapshots.find_by_idempotency(case_id, key_hash)
        if existing is not None:
            if existing["sourceFileSha256"] != source_file_sha256:
                raise StateConflict("Idempotency key was already used for another response")
            return self._with_flow_status(existing)

        package = import_candidate_package(raw)
        if package.package_type != "RESPONSE":
            raise ValidationError("Only a submitted response package can be imported")
        question_set = self.questions.current_for_case(case_id)
        if question_set is None:
            raise ResourceNotFound("Question Set not found")
        manifest = package.manifest
        if manifest["questionSetId"] != question_set["id"]:
            raise StateConflict("Response Question Set does not match the case")
        if manifest["questionSetVersion"] != question_set["versionNo"]:
            raise StateConflict("Response Question Set version does not match")
        expected_questions = _candidate_questions(question_set)
        if manifest["questionSetFingerprint"] != _question_fingerprint(expected_questions):
            raise StateConflict("Response Question Set fingerprint does not match")
        if package.questions != expected_questions:
            raise StateConflict("Response questions do not match the approved Question Set")

        document_manifest = question_set["questionPolicy"].get("sourceDocuments", [])
        if not isinstance(document_manifest, list):
            raise StateConflict("Question Set document provenance is invalid")
        normalized = json.dumps(
            {
                "manifest": manifest,
                "questions": package.questions,
                "answers": package.answers,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        answers = [
            {
                "answerId": str(uuid.uuid4()),
                "questionId": answer["questionId"],
                "answerText": answer["answerText"],
                "isAnswered": answer["isAnswered"],
                "saveRevision": 0,
                "contentHash": hashlib.sha256(
                    answer["answerText"].encode("utf-8")
                ).hexdigest(),
            }
            for answer in package.answers
        ]
        with self.database.transaction() as connection:
            snapshot = self.snapshots.create_imported_snapshot(
                connection,
                case_id=case_id,
                question_set_id=question_set["id"],
                source_kind="HTML_IMPORT",
                source_file_sha256=source_file_sha256,
                package_id=manifest["packageId"],
                normalized_fingerprint=hashlib.sha256(normalized).hexdigest(),
                idempotency_key_hash=key_hash,
                document_manifest=document_manifest,
                questions=_snapshot_questions(question_set),
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
                    "sourceKind": "HTML_IMPORT",
                    "packageId": manifest["packageId"],
                    "questionSetId": question_set["id"],
                    "versionNo": snapshot["versionNo"],
                    "questionCount": len(package.questions),
                    "answeredCount": sum(1 for answer in package.answers if answer["isAnswered"]),
                },
            )
        return self._with_flow_status(snapshot)

    def get_snapshot(
        self, case_id: str, snapshot_id: str | None = None
    ) -> dict[str, Any] | None:
        snapshot = (
            self.snapshots.get(snapshot_id)
            if snapshot_id is not None
            else self.snapshots.current_for_case(case_id)
        )
        if snapshot is None or snapshot["interviewCaseId"] != case_id:
            return None
        return self._with_flow_status(snapshot)

    def snapshot_manifest(self, snapshot_id: str) -> dict[str, Any]:
        return self.snapshots.payload(snapshot_id)

    def _with_flow_status(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        result = dict(snapshot)
        result["refinedFlowStatus"] = _refined_status(snapshot["status"])
        return result


def _candidate_questions(question_set: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "questionId": question["id"],
            "displayOrder": question["displayOrder"],
            "questionText": question["questionText"],
            "questionType": question["questionType"],
            "isRequired": question["isRequired"],
        }
        for question in question_set["questions"]
    ]


def _snapshot_questions(question_set: dict[str, Any]) -> list[dict[str, Any]]:
    return [
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
        }
        for question in question_set["questions"]
    ]


def _question_fingerprint(questions: list[dict[str, Any]]) -> str:
    normalized = json.dumps(
        questions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


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
