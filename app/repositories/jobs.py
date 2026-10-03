from __future__ import annotations

import sqlite3

from app.repositories.base import RepositoryBase


class JobRepository(RepositoryBase):
    def insert(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        job_code: str | None,
        position_title: str,
        target_level: str,
    ) -> None:
        connection.execute(
            """INSERT INTO jobs(id, job_code, position_title, target_level)
               VALUES (?, ?, ?, ?)""",
            (job_id, job_code, position_title, target_level),
        )

    def list(self, query: str | None = None) -> list[sqlite3.Row]:
        if query:
            pattern = f"%{query}%"
            return self.query_all(
                """SELECT * FROM jobs
                   WHERE job_code LIKE ? OR position_title LIKE ? OR target_level LIKE ?
                   ORDER BY created_at DESC""",
                (pattern, pattern, pattern),
            )
        return self.query_all("SELECT * FROM jobs ORDER BY created_at DESC")
