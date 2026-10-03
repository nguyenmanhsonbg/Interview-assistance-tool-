from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class QuestionRepository(RepositoryBase):
    def get_set(self, question_set_id: str) -> dict[str, Any]:
        row = self.query_one("SELECT * FROM question_sets WHERE id=?", (question_set_id,))
        if row is None:
            raise ResourceNotFound("Question Set not found")
        questions = self.query_all(
            "SELECT * FROM questions WHERE question_set_id=? ORDER BY display_order",
            (question_set_id,),
        )
        return _set_dict(row, questions)

    def current_for_case(self, case_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            """SELECT * FROM question_sets WHERE interview_case_id=?
               ORDER BY CASE status WHEN 'APPROVED' THEN 0 ELSE 1 END, version_no DESC LIMIT 1""",
            (case_id,),
        )
        return None if row is None else self.get_set(row["id"])


def _set_dict(row: sqlite3.Row, questions: list[sqlite3.Row]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "interviewCaseId": row["interview_case_id"],
        "versionNo": row["version_no"],
        "status": row["status"],
        "durationSeconds": row["duration_seconds"],
        "rubricPolicy": json.loads(row["rubric_policy_json"]),
        "questionPolicy": json.loads(row["question_policy_json"]),
        "approvedByMemberId": row["approved_by_member_id"],
        "approvedAt": row["approved_at"],
        "questions": [
            {
                "id": question["id"],
                "displayOrder": question["display_order"],
                "questionText": question["question_text"],
                "competencyKey": question["competency_key"],
                "sourceKind": question["source_kind"],
                "purpose": question["purpose"],
                "questionType": question["question_type"],
                "difficulty": question["difficulty"],
                "expectedEvidence": question["expected_evidence"],
                "rubric": json.loads(question["rubric_json"]),
                "isRequired": bool(question["is_required"]),
                "estimatedSeconds": question["estimated_seconds"],
            }
            for question in questions
        ],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
