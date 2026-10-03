from __future__ import annotations

import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class AssessmentRepository(RepositoryBase):
    def by_case(self, case_id: str) -> sqlite3.Row | None:
        return self.query_one(
            "SELECT * FROM assessment_attempts WHERE interview_case_id=?", (case_id,)
        )

    def get(self, attempt_id: str) -> sqlite3.Row:
        row = self.query_one(
            "SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)
        )
        if row is None:
            raise ResourceNotFound("Assessment attempt not found")
        return row

    def candidate_questions(self, attempt_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            """SELECT q.id, q.display_order, q.question_text, q.question_type,
                      a.answer_text, a.is_answered, a.save_revision
               FROM assessment_attempts aa
               JOIN questions q ON q.question_set_id=aa.question_set_id
               LEFT JOIN answers a ON a.assessment_attempt_id=aa.id AND a.question_id=q.id
               WHERE aa.id=? ORDER BY q.display_order""",
            (attempt_id,),
        )
        return [
            {
                "id": row["id"],
                "displayOrder": row["display_order"],
                "questionText": row["question_text"],
                "questionType": row["question_type"],
                "answerText": row["answer_text"] or "",
                "isAnswered": bool(row["is_answered"]),
                "saveRevision": row["save_revision"] or 0,
            }
            for row in rows
        ]
