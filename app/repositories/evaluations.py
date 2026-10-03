from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class EvaluationRepository(RepositoryBase):
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
