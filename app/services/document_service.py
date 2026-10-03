from __future__ import annotations

import hashlib
import io
import sqlite3
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, UnsupportedMediaType, ValidationError
from app.infrastructure.case_locks import case_mutation_lock
from app.infrastructure.file_storage import FileStorage
from app.repositories.audit import append_audit
from app.repositories.documents import DocumentRepository


MAX_FILE_BYTES = 7_500_000
MAX_TEXT_CODEPOINTS = 200_000
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentService:
    def __init__(self, database: Database, data_root: Path) -> None:
        self.database = database
        self.repository = DocumentRepository(database)
        self.storage = FileStorage(data_root)

    def import_manual_text(
        self, case_id: str, document_type: str, text: str
    ) -> dict[str, Any]:
        canonical = _canonicalize(text)
        with case_mutation_lock(case_id):
            return self._persist(
                case_id=case_id,
                document_type=document_type,
                source_kind="MANUAL_TEXT",
                extraction_status="MANUAL_CONFIRMED",
                original_filename=None,
                mime_type=None,
                raw=None,
                storage_path=None,
                extracted_text=canonical,
                ai_eligible=False,
            )

    def import_file(
        self,
        case_id: str,
        document_type: str,
        original_filename: str,
        mime_type: str,
        raw: bytes,
    ) -> dict[str, Any]:
        with case_mutation_lock(case_id):
            return self._import_file_locked(
                case_id, document_type, original_filename, mime_type, raw
            )

    def _import_file_locked(
        self,
        case_id: str,
        document_type: str,
        original_filename: str,
        mime_type: str,
        raw: bytes,
    ) -> dict[str, Any]:
        _validate_document_type(document_type)
        self._require_mutable_case(case_id)
        if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
            raise ValidationError("File exceeds the decoded size limit")
        extension = Path(original_filename).suffix.lower()
        _validate_media(extension, mime_type, raw)
        document_id = str(uuid.uuid4())
        version = self._peek_next_version(case_id, document_type)
        relative = (
            f"documents/{case_id}/{document_type.lower()}/v{version:03d}/"
            f"source-{document_id}{extension}"
        )
        self.storage.write_atomic(relative, raw)
        try:
            extracted = _extract(extension, raw)
            status = "SUCCEEDED"
        except (
            UnicodeDecodeError,
            ValueError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
            ValidationError,
        ):
            extracted = ""
            status = "FAILED"
        try:
            result = self._persist(
                case_id=case_id,
                document_type=document_type,
                source_kind="IMPORTED_FILE",
                extraction_status=status,
                original_filename=Path(original_filename).name,
                mime_type=mime_type,
                raw=raw,
                storage_path=relative,
                extracted_text=extracted,
                ai_eligible=False,
                document_id=document_id,
            )
        except Exception:
            stored = self.storage.resolve_relative(relative)
            if stored.is_file():
                stored.unlink()
            raise
        if status == "FAILED":
            with self.database.transaction() as connection:
                connection.execute(
                    """UPDATE interview_cases SET status='DOCUMENT_PARSE_FAILED',
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                       WHERE id=? AND status IN ('DRAFT','DOCUMENTS_READY')""",
                    (case_id,),
                )
                append_audit(
                    connection,
                    actor_type="SYSTEM",
                    action="DOCUMENT_PARSE_FAILED",
                    entity_type="DOCUMENT",
                    entity_id=result["id"],
                    metadata={"format": extension, "errorCode": "DOCUMENT_PARSE_FAILED"},
                )
        return result

    def confirm(self, document_id: str, expected_hash: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            existing = connection.execute(
                "SELECT interview_case_id FROM documents WHERE id=?", (document_id,)
            ).fetchone()
        if existing is None:
            raise ResourceNotFound("Document not found")
        with case_mutation_lock(existing["interview_case_id"]):
            return self._confirm_locked(document_id, expected_hash)

    def _confirm_locked(self, document_id: str, expected_hash: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT d.*, ic.status case_status, aa.status attempt_status
                   FROM documents d
                   JOIN interview_cases ic ON ic.id=d.interview_case_id
                   LEFT JOIN assessment_attempts aa ON aa.interview_case_id=ic.id
                   WHERE d.id=?""", (document_id,)
            ).fetchone()
            if row is None:
                raise ResourceNotFound("Document not found")
            if not row["is_current"]:
                raise StateConflict("Only the current document version can be confirmed")
            if not _documents_mutable(row["case_status"], row["attempt_status"]):
                raise StateConflict("Documents are locked after the assessment starts")
            if row["content_sha256"] != expected_hash or not row["extracted_text"].strip():
                raise ValidationError("Document text hash does not match or text is empty")
            connection.execute(
                """UPDATE documents SET is_ai_eligible=1, confirmed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   extraction_status=CASE WHEN source_kind='MANUAL_TEXT' THEN 'MANUAL_CONFIRMED' ELSE 'SUCCEEDED' END
                   WHERE id=?""",
                (document_id,),
            )
            count = connection.execute(
                """SELECT COUNT(DISTINCT document_type) FROM documents
                   WHERE interview_case_id=? AND is_current=1 AND is_ai_eligible=1
                     AND document_type IN ('JD','CV')""",
                (row["interview_case_id"],),
            ).fetchone()[0]
            if row["case_status"] in {"DRAFT", "DOCUMENT_PARSE_FAILED", "DOCUMENTS_READY"}:
                case_status = "DOCUMENTS_READY" if count == 2 else "DRAFT"
            else:
                case_status = row["case_status"]
            connection.execute(
                """UPDATE interview_cases SET status=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_status, row["interview_case_id"]),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="DOCUMENT_TEXT_CONFIRMED",
                entity_type="DOCUMENT",
                entity_id=document_id,
                metadata={"documentType": row["document_type"]},
            )
        result = self.repository.get(document_id)
        result["caseStatus"] = case_status
        return result

    def list_for_case(self, case_id: str) -> list[dict[str, Any]]:
        return self.repository.list_for_case(case_id)

    def _peek_next_version(self, case_id: str, document_type: str) -> int:
        with self.database.connection() as connection:
            return self.repository.next_version(connection, case_id, document_type)[0]

    def _require_mutable_case(self, case_id: str) -> None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT ic.status, aa.status attempt_status
                   FROM interview_cases ic
                   LEFT JOIN assessment_attempts aa ON aa.interview_case_id=ic.id
                   WHERE ic.id=?""",
                (case_id,),
            ).fetchone()
        if row is None:
            raise ResourceNotFound("Interview case not found")
        if not _documents_mutable(row["status"], row["attempt_status"]):
            raise StateConflict("Documents are locked after the assessment starts")

    def _persist(
        self,
        *,
        case_id: str,
        document_type: str,
        source_kind: str,
        extraction_status: str,
        original_filename: str | None,
        mime_type: str | None,
        raw: bytes | None,
        storage_path: str | None,
        extracted_text: str,
        ai_eligible: bool,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        _validate_document_type(document_type)
        document_id = document_id or str(uuid.uuid4())
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
        file_hash = hashlib.sha256(raw).hexdigest() if raw is not None else None
        with self.database.transaction() as connection:
            case = connection.execute(
                """SELECT ic.status, aa.status attempt_status
                   FROM interview_cases ic
                   LEFT JOIN assessment_attempts aa ON aa.interview_case_id=ic.id
                   WHERE ic.id=?""",
                (case_id,),
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if not _documents_mutable(case["status"], case["attempt_status"]):
                raise StateConflict("Documents are locked after the assessment starts")
            version, supersedes = self.repository.next_version(
                connection, case_id, document_type
            )
            connection.execute(
                "UPDATE documents SET is_current=0 WHERE interview_case_id=? AND document_type=? AND is_current=1",
                (case_id, document_type),
            )
            connection.execute(
                """UPDATE interview_cases SET status=CASE
                       WHEN status IN ('DRAFT','DOCUMENT_PARSE_FAILED','DOCUMENTS_READY')
                       THEN 'DRAFT' ELSE status END,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (case_id,),
            )
            connection.execute(
                """INSERT INTO documents(
                    id, interview_case_id, document_type, version_no, source_kind,
                    extraction_status, original_filename, mime_type, file_size_bytes,
                    file_sha256, content_sha256, storage_path, extracted_text,
                    is_ai_eligible, is_current, supersedes_document_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    document_id, case_id, document_type, version, source_kind,
                    extraction_status, original_filename, mime_type,
                    len(raw) if raw is not None else None, file_hash, content_hash,
                    storage_path, extracted_text, int(ai_eligible), supersedes,
                ),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="DOCUMENT_IMPORTED" if version == 1 else "DOCUMENT_VERSION_CREATED",
                entity_type="DOCUMENT",
                entity_id=document_id,
                metadata={"documentType": document_type, "versionNo": version},
            )
        return self.repository.get(document_id)


def _documents_mutable(case_status: str, attempt_status: str | None) -> bool:
    pre_assessment_states = {
        "DRAFT",
        "DOCUMENT_PARSE_FAILED",
        "DOCUMENTS_READY",
        "QUESTIONS_GENERATING",
        "QUESTION_GENERATION_FAILED",
        "QUESTIONS_GENERATED",
        "QUESTIONS_APPROVED",
        "READY_FOR_ASSESSMENT",
    }
    return (
        case_status in pre_assessment_states
        and attempt_status in {None, "READY_FOR_ASSESSMENT"}
    )


def _validate_document_type(document_type: str) -> None:
    if document_type not in {"JD", "CV"}:
        raise ValidationError("documentType must be JD or CV")


def _validate_media(extension: str, mime_type: str, raw: bytes) -> None:
    allowed = {
        ".txt": {"text/plain"},
        ".md": {"text/markdown", "text/plain"},
        ".markdown": {"text/markdown", "text/plain"},
        ".docx": {DOCX_MIME},
        ".pdf": {"application/pdf"},
    }
    if extension in {".doc", ".docm"} or extension not in allowed:
        raise UnsupportedMediaType("Unsupported document format")
    if mime_type not in allowed[extension]:
        raise UnsupportedMediaType("MIME type does not match document format")
    if extension == ".docx" and not raw.startswith(b"PK"):
        raise UnsupportedMediaType("DOCX signature is invalid")
    if extension == ".pdf" and not raw.startswith(b"%PDF-"):
        raise UnsupportedMediaType("PDF signature is invalid")


def _extract(extension: str, raw: bytes) -> str:
    if extension in {".txt", ".md", ".markdown"}:
        text = raw.decode("utf-8-sig", errors="strict")
        return _canonicalize(text)
    if extension == ".docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("DOCX required entries are missing")
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise ValueError("Macro-enabled document is not allowed")
            for info in archive.infolist():
                if info.file_size > MAX_FILE_BYTES or info.file_size > max(1, info.compress_size) * 100:
                    raise ValueError("Unsafe DOCX expansion")
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            text = "\n".join(node.text or "" for node in root.iter(namespace))
            return _canonicalize(text)
    if extension == ".pdf":
        raise ValueError("PDF extraction requires manual text or approved pdftotext")
    raise UnsupportedMediaType("Unsupported document format")


def _canonicalize(text: str) -> str:
    if not isinstance(text, str):
        raise ValidationError("Document text must be a string")
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        char for char in normalized
        if char in {"\n", "\t"} or (char != "\x00" and unicodedata.category(char) != "Cc")
    )
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    if not normalized:
        raise ValidationError("Extracted text is empty")
    if len(normalized) > MAX_TEXT_CODEPOINTS:
        raise ValidationError("Extracted text is too long")
    return normalized
