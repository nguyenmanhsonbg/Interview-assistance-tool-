from __future__ import annotations

import sqlite3

from app.repositories.base import RepositoryBase


class CandidateRepository(RepositoryBase):
    def insert(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        candidate_code: str,
        full_name: str,
    ) -> None:
        connection.execute(
            "INSERT INTO candidates(id, candidate_code, full_name) VALUES (?, ?, ?)",
            (candidate_id, candidate_code, full_name),
        )

    def list(self, query: str | None = None) -> list[sqlite3.Row]:
        if query:
            pattern = f"%{query}%"
            return self.query_all(
                """SELECT * FROM candidates
                   WHERE candidate_code LIKE ? OR full_name LIKE ?
                   ORDER BY created_at DESC""",
                (pattern, pattern),
            )
        return self.query_all("SELECT * FROM candidates ORDER BY created_at DESC")
