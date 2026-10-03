from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class EvaluationRepository(RepositoryBase):
    def list_live_records(self, case_id: str) -> list[dict[str, Any]]:
        return [
            _live_dict(row)
            for row in self.query_all(
                """SELECT * FROM live_interview_records
                   WHERE interview_case_id=? ORDER BY sequence_no""",
                (case_id,),
            )
        ]

    def get_live_record(self, case_id: str, sequence_no: int) -> dict[str, Any]:
        row = self.query_one(
            """SELECT * FROM live_interview_records
               WHERE interview_case_id=? AND sequence_no=?""",
            (case_id, sequence_no),
        )
        if row is None:
            raise ResourceNotFound("Live interview record not found")
        return _live_dict(row)

    def current_evaluation(self, case_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM evaluations WHERE interview_case_id=? AND is_current=1",
            (case_id,),
        )
        return None if row is None else _evaluation_dict(row)

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        row = self.query_one("SELECT * FROM evaluations WHERE id=?", (evaluation_id,))
        if row is None:
            raise ResourceNotFound("Evaluation not found")
        return _evaluation_dict(row)

    def current_brief(self, case_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM interview_briefs WHERE interview_case_id=? AND is_current=1",
            (case_id,),
        )
        return None if row is None else _brief_dict(row)

    def brief_by_ai_result(self, ai_result_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM interview_briefs WHERE ai_result_id=?", (ai_result_id,)
        )
        return None if row is None else _brief_dict(row)

    def insert_brief(
        self,
        connection: sqlite3.Connection,
        *,
        brief_id: str,
        case_id: str,
        attempt_id: str,
        ai_result_id: str | None,
        source_kind: str,
        brief: dict[str, Any],
        member_id: str | None,
    ) -> None:
        previous = connection.execute(
            """SELECT id, version_no FROM interview_briefs
               WHERE interview_case_id=? AND is_current=1""",
            (case_id,),
        ).fetchone()
        version = 1 if previous is None else previous["version_no"] + 1
        if previous is not None:
            connection.execute(
                "UPDATE interview_briefs SET status='SUPERSEDED', is_current=0 WHERE id=?",
                (previous["id"],),
            )
        connection.execute(
            """INSERT INTO interview_briefs(
                id, interview_case_id, assessment_attempt_id, ai_result_id,
                source_kind, status, version_no, supersedes_brief_id,
                brief_json, is_current, created_by_member_id
            ) VALUES (?, ?, ?, ?, ?, 'READY', ?, ?, ?, 1, ?)""",
            (
                brief_id, case_id, attempt_id, ai_result_id, source_kind,
                version, None if previous is None else previous["id"],
                json.dumps(brief, ensure_ascii=False, separators=(",", ":")), member_id,
            ),
        )

    def get_brief(self, brief_id: str) -> dict[str, Any]:
        row = self.query_one("SELECT * FROM interview_briefs WHERE id=?", (brief_id,))
        if row is None:
            raise ResourceNotFound("Interview Brief not found")
        return _brief_dict(row)


def _brief_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "interviewCaseId": row["interview_case_id"],
        "assessmentAttemptId": row["assessment_attempt_id"],
        "aiResultId": row["ai_result_id"],
        "sourceKind": row["source_kind"],
        "status": row["status"],
        "versionNo": row["version_no"],
        "supersedesBriefId": row["supersedes_brief_id"],
        "brief": json.loads(row["brief_json"]),
        "isCurrent": bool(row["is_current"]),
        "createdByMemberId": row["created_by_member_id"],
        "createdAt": row["created_at"],
    }


def _live_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "interviewCaseId": row["interview_case_id"],
        "interviewBriefId": row["interview_brief_id"],
        "committeeMemberId": row["committee_member_id"],
        "sequenceNo": row["sequence_no"], "questionText": row["question_text"],
        "sourceKind": row["source_kind"], "askedStatus": row["asked_status"],
        "liveNotes": row["live_notes"], "score": row["score"],
        "evidenceStatus": row["evidence_status"], "askedAt": row["asked_at"],
        "completedAt": row["completed_at"], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _evaluation_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "interviewCaseId": row["interview_case_id"],
        "versionNo": row["version_no"], "status": row["status"],
        "finalResult": row["final_result"], "finalLevel": row["final_level"],
        "summary": row["summary"], "strengths": json.loads(row["strengths_json"]),
        "gaps": json.loads(row["gaps_json"]), "risks": json.loads(row["risks_json"]),
        "finalComment": row["final_comment"],
        "decidedByMemberId": row["decided_by_member_id"], "decidedAt": row["decided_at"],
        "supersedesEvaluationId": row["supersedes_evaluation_id"],
        "isCurrent": bool(row["is_current"]), "createdAt": row["created_at"],
    }
