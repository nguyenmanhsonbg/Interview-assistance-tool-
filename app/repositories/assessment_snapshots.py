from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any, Sequence

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


_ASSESSMENT_INPUT_SOURCES = {"EXCEL_IMPORT", "HTML_IMPORT"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AssessmentSnapshotRepository(RepositoryBase):
    def create_imported_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        case_id: str,
        question_set_id: str,
        source_kind: str,
        source_file_sha256: str,
        package_id: str | None,
        normalized_fingerprint: str,
        idempotency_key_hash: str,
        document_manifest: list[dict[str, Any]],
        questions: Sequence[dict[str, Any]],
        answers: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if source_kind not in _ASSESSMENT_INPUT_SOURCES:
            raise ValueError("Unsupported assessment input source")
        if not isinstance(source_file_sha256, str) or not _SHA256_RE.fullmatch(
            source_file_sha256
        ):
            raise ValueError("Invalid source file SHA-256")
        if package_id is not None and (
            not isinstance(package_id, str) or not package_id.strip() or len(package_id) > 256
        ):
            raise ValueError("Invalid assessment package ID")
        previous = connection.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS version_no "
            "FROM assessment_snapshots WHERE interview_case_id=?",
            (case_id,),
        ).fetchone()
        snapshot_id = str(uuid.uuid4())
        version_no = int(previous["version_no"]) + 1
        connection.execute(
            """INSERT INTO assessment_snapshots(
                id, interview_case_id, question_set_id, version_no,
                source_kind, workbook_sha256, normalized_fingerprint,
                idempotency_key_hash, document_manifest_json,
                assessment_input_source, source_file_sha256, package_id
            ) VALUES (?, ?, ?, ?, 'EXCEL_IMPORT', ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                case_id,
                question_set_id,
                version_no,
                source_file_sha256,
                normalized_fingerprint,
                idempotency_key_hash,
                json.dumps(document_manifest, ensure_ascii=False, separators=(",", ":")),
                source_kind,
                source_file_sha256,
                package_id,
            ),
        )
        for question in questions:
            connection.execute(
                """INSERT INTO assessment_snapshot_questions(
                    assessment_snapshot_id, question_id, display_order,
                    question_text, competency_key, source_kind, question_category,
                    purpose, next_step_objective, question_type, difficulty,
                    expected_evidence, rubric_json, is_required, estimated_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    question["questionId"],
                    question["displayOrder"],
                    question["questionText"],
                    question["competencyKey"],
                    question["sourceKind"],
                    question["questionCategory"],
                    question["purpose"],
                    question["nextStepObjective"],
                    question["questionType"],
                    question["difficulty"],
                    question["expectedEvidence"],
                    json.dumps(question["rubric"], ensure_ascii=False, separators=(",", ":")),
                    int(question["isRequired"]),
                    question["estimatedSeconds"],
                ),
            )
        for answer in answers:
            connection.execute(
                """INSERT INTO assessment_snapshot_answers(
                    id, assessment_snapshot_id, question_id, answer_text,
                    is_answered, save_revision, content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    answer["answerId"],
                    snapshot_id,
                    answer["questionId"],
                    answer["answerText"],
                    int(answer["isAnswered"]),
                    answer["saveRevision"],
                    answer["contentHash"],
                ),
            )
        row = connection.execute(
            "SELECT * FROM assessment_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        assert row is not None
        return self._read(connection, row)

    def get(self, snapshot_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM assessment_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
            if row is None:
                raise ResourceNotFound("Assessment snapshot not found")
            return self._read(connection, row)

    def find_by_idempotency(
        self, case_id: str, idempotency_key_hash: str
    ) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM assessment_snapshots
                   WHERE interview_case_id=? AND idempotency_key_hash=?""",
                (case_id, idempotency_key_hash),
            ).fetchone()
            return None if row is None else self._read(connection, row)

    def current_for_case(self, case_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM assessment_snapshots
                   WHERE interview_case_id=? ORDER BY version_no DESC LIMIT 1""",
                (case_id,),
            ).fetchone()
            return None if row is None else self._read(connection, row)

    def payload(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.get(snapshot_id)
        return {
            "snapshotId": snapshot["id"],
            "interviewCaseId": snapshot["interviewCaseId"],
            "questionSetId": snapshot["questionSetId"],
            "snapshotVersion": snapshot["versionNo"],
            "documents": snapshot["documentManifest"],
            "questions": snapshot["questions"],
            "answers": snapshot["answers"],
        }

    def update_status(self, snapshot_id: str, status: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE assessment_snapshots SET status=? WHERE id=?",
                (status, snapshot_id),
            )

    @staticmethod
    def _read(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        questions = connection.execute(
            """SELECT * FROM assessment_snapshot_questions
               WHERE assessment_snapshot_id=? ORDER BY display_order""",
            (row["id"],),
        ).fetchall()
        answers = connection.execute(
            """SELECT * FROM assessment_snapshot_answers
               WHERE assessment_snapshot_id=? ORDER BY question_id""",
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "interviewCaseId": row["interview_case_id"],
            "questionSetId": row["question_set_id"],
            "versionNo": row["version_no"],
            "sourceKind": row["assessment_input_source"],
            "status": row["status"],
            "workbookSha256": row["workbook_sha256"],
            "sourceFileSha256": row["source_file_sha256"] or row["workbook_sha256"],
            "packageId": row["package_id"],
            "normalizedFingerprint": row["normalized_fingerprint"],
            "idempotencyKeyHash": row["idempotency_key_hash"],
            "documentManifest": json.loads(row["document_manifest_json"]),
            "importedAt": row["imported_at"],
            "createdAt": row["created_at"],
            "questions": [_question_dict(item) for item in questions],
            "answers": [_answer_dict(item) for item in answers],
        }


def _question_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "questionId": row["question_id"],
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


def _answer_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "answerId": row["id"],
        "questionId": row["question_id"],
        "answerText": row["answer_text"],
        "isAnswered": bool(row["is_answered"]),
        "assessmentStatus": "ANSWERED" if row["is_answered"] else "NOT_ASSESSED",
        "saveRevision": row["save_revision"],
        "contentHash": row["content_sha256"],
    }
