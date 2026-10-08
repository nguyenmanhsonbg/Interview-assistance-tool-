from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound, StateConflict
from app.repositories.base import RepositoryBase


class QuestionAdditionRepository(RepositoryBase):
    def get_proposal(
        self, case_id: str, question_set_id: str, proposal_id: str
    ) -> dict[str, Any]:
        row = self.query_one(
            """SELECT p.*, r.payload_json, r.version_no,
                      r.created_at AS result_created_at
               FROM question_addition_proposals p
               JOIN ai_results r ON r.id=p.ai_result_id
               WHERE p.id=? AND p.interview_case_id=? AND p.question_set_id=?""",
            (proposal_id, case_id, question_set_id),
        )
        if row is None:
            raise ResourceNotFound("Question addition proposal not found")
        return _proposal_dict(row)

    def list_active_proposals(
        self,
        case_id: str,
        question_set_id: str,
        target_category: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """SELECT p.*, r.payload_json, r.version_no,
                         r.created_at AS result_created_at
                  FROM question_addition_proposals p
                  JOIN ai_results r ON r.id=p.ai_result_id
                  WHERE p.interview_case_id=? AND p.question_set_id=?
                    AND p.status='PROPOSED'"""
        parameters: list[Any] = [case_id, question_set_id]
        if target_category is not None:
            sql += " AND p.target_category=?"
            parameters.append(target_category)
        sql += " ORDER BY p.created_at DESC, p.id DESC"
        return [_proposal_dict(row) for row in self.query_all(sql, parameters)]

    def create_proposal_from_result(
        self,
        connection: sqlite3.Connection,
        *,
        proposal_id: str,
        ai_result_id: str,
        case_id: str,
        question_set_id: str,
        target_category: str,
        mode: str,
        source_fingerprint: str,
    ) -> tuple[str, bool]:
        existing = connection.execute(
            "SELECT id FROM question_addition_proposals WHERE ai_result_id=?",
            (ai_result_id,),
        ).fetchone()
        if existing is not None:
            return existing["id"], False
        connection.execute(
            """INSERT INTO question_addition_proposals(
                id, ai_result_id, interview_case_id, question_set_id,
                target_category, mode, source_fingerprint, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED')""",
            (
                proposal_id, ai_result_id, case_id, question_set_id,
                target_category, mode, source_fingerprint,
            ),
        )
        return proposal_id, True

    def mark_discarded(
        self,
        connection: sqlite3.Connection,
        *,
        case_id: str,
        question_set_id: str,
        proposal_id: str,
    ) -> bool:
        cursor = connection.execute(
            """UPDATE question_addition_proposals
               SET status='DISCARDED', discarded_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=? AND interview_case_id=? AND question_set_id=?
                 AND status='PROPOSED'""",
            (proposal_id, case_id, question_set_id),
        )
        if cursor.rowcount:
            return True
        row = connection.execute(
            """SELECT status FROM question_addition_proposals
               WHERE id=? AND interview_case_id=? AND question_set_id=?""",
            (proposal_id, case_id, question_set_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound("Question addition proposal not found")
        if row["status"] != "DISCARDED":
            raise StateConflict("Question addition proposal is no longer proposed")
        return False

    def mark_applied(
        self,
        connection: sqlite3.Connection,
        *,
        case_id: str,
        question_set_id: str,
        proposal_id: str,
        question_id: str,
    ) -> None:
        cursor = connection.execute(
            """UPDATE question_addition_proposals
               SET status='APPLIED', applied_question_id=?,
                   applied_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=? AND interview_case_id=? AND question_set_id=?
                 AND status='PROPOSED'""",
            (question_id, proposal_id, case_id, question_set_id),
        )
        if cursor.rowcount:
            return
        row = connection.execute(
            """SELECT status FROM question_addition_proposals
               WHERE id=? AND interview_case_id=? AND question_set_id=?""",
            (proposal_id, case_id, question_set_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound("Question addition proposal not found")
        raise StateConflict("Question addition proposal is no longer proposed")


def _proposal_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        "proposalId": row["id"],
        "aiResultId": row["ai_result_id"],
        "interviewCaseId": row["interview_case_id"],
        "questionSetId": row["question_set_id"],
        "targetCategory": row["target_category"],
        "mode": row["mode"],
        "sourceFingerprint": row["source_fingerprint"],
        "status": row["status"],
        "appliedQuestionId": row["applied_question_id"],
        "question": payload.get("question", {}),
        "confidence": payload.get("confidence"),
        "limitations": payload.get("limitations", []),
        "versionNo": row["version_no"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "appliedAt": row["applied_at"],
        "discardedAt": row["discarded_at"],
    }
