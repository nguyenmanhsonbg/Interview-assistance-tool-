from __future__ import annotations

import sqlite3
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.base import RepositoryBase


class DocumentRepository(RepositoryBase):
    def next_version(
        self, connection: sqlite3.Connection, case_id: str, document_type: str
    ) -> tuple[int, str | None]:
        row = connection.execute(
            """SELECT id, version_no FROM documents
               WHERE interview_case_id = ? AND document_type = ?
               ORDER BY version_no DESC LIMIT 1""",
            (case_id, document_type),
        ).fetchone()
        return (1, None) if row is None else (int(row["version_no"]) + 1, row["id"])

    def list_for_case(self, case_id: str) -> list[dict[str, Any]]:
        return [
            _document_dict(row)
            for row in self.query_all(
                """SELECT * FROM documents WHERE interview_case_id = ?
                   ORDER BY document_type, version_no DESC""",
                (case_id,),
            )
        ]

    def get(self, document_id: str) -> dict[str, Any]:
        row = self.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if row is None:
            raise ResourceNotFound("Document not found")
        return _document_dict(row)


def _document_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "interviewCaseId": row["interview_case_id"],
        "documentType": row["document_type"],
        "versionNo": row["version_no"],
        "sourceKind": row["source_kind"],
        "extractionStatus": row["extraction_status"],
        "originalFilename": row["original_filename"],
        "mimeType": row["mime_type"],
        "fileSizeBytes": row["file_size_bytes"],
        "fileSha256": row["file_sha256"],
        "contentSha256": row["content_sha256"],
        "storagePath": row["storage_path"],
        "extractedText": row["extracted_text"],
        "isAiEligible": bool(row["is_ai_eligible"]),
        "isCurrent": bool(row["is_current"]),
        "confirmedAt": row["confirmed_at"],
        "createdAt": row["created_at"],
    }
