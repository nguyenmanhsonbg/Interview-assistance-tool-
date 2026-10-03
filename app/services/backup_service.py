from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import Database
from app.domain.errors import BackupRequired, ResourceNotFound, ValidationError
from app.infrastructure.file_storage import FileStorage
from app.repositories.audit import append_audit


class BackupService:
    def __init__(self, database: Database, data_root: Path) -> None:
        self.database = database
        self.data_root = Path(data_root).resolve()
        self.storage = FileStorage(self.data_root)
        self.backup_root = self.data_root / "backups"
        self.export_root = self.data_root / "exports"

    def create_backup(self, label: str, *, include_documents: bool = False) -> dict[str, Any]:
        backup_id = str(uuid.uuid4())
        safe_label = "".join(char for char in label if char.isalnum() or char in "-_")[:40] or "backup"
        folder = (self.backup_root / f"{_timestamp()}-{safe_label}-{backup_id}").resolve()
        self._require_inside(folder, self.backup_root)
        folder.mkdir(parents=True, exist_ok=False)
        temporary = folder / "clawcv.db.tmp"
        target = folder / "clawcv.db"
        destination = sqlite3.connect(temporary)
        try:
            with self.database.connection() as source:
                source.backup(destination)
        finally:
            destination.close()
        os.replace(temporary, target)
        files = {"clawcv.db": _sha256_file(target)}
        if include_documents:
            documents_root = self.data_root / "documents"
            if documents_root.exists():
                for source in documents_root.rglob("*"):
                    if not source.is_file():
                        continue
                    relative = source.relative_to(self.data_root)
                    destination_path = folder / relative
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination_path)
                    files[str(relative).replace("\\", "/")] = _sha256_file(destination_path)
        manifest = {
            "backupId": backup_id, "createdAt": _now(), "label": safe_label,
            "includeDocuments": include_documents, "files": files,
        }
        manifest_path = folder / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.database.transaction() as connection:
            append_audit(connection, actor_type="COMMITTEE", action="BACKUP_CREATED",
                entity_type="BACKUP", entity_id=backup_id,
                metadata={"label": safe_label, "includeDocuments": include_documents})
        return {
            "id": backup_id, "status": "COMPLETED", "databasePath": str(target),
            "manifestPath": str(manifest_path), "safePathSummary": folder.name,
        }

    def restore_to(self, backup_database: str | Path, target_database: Path) -> dict[str, Any]:
        source_path = Path(backup_database).resolve()
        self._require_inside(source_path, self.backup_root)
        if not source_path.is_file():
            raise ResourceNotFound("Backup database not found")
        target_database = Path(target_database).resolve()
        target_database.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(source_path)
        destination = sqlite3.connect(target_database)
        try:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
            destination.execute("PRAGMA foreign_keys=ON")
            foreign_key_violations = destination.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            source.close()
            destination.close()
        if integrity != "ok" or foreign_key_violations:
            raise ValidationError("Restored database failed validation")
        return {"integrity": integrity, "foreignKeyViolations": 0}

    def export_case(self, case_id: str, *, include_documents: bool) -> dict[str, Any]:
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT ic.id, ic.status, ic.scheduled_at, c.candidate_code, c.full_name,
                          j.job_code, j.position_title, j.target_level
                   FROM interview_cases ic JOIN candidates c ON c.id=ic.candidate_id
                   JOIN jobs j ON j.id=ic.job_id WHERE ic.id=?""", (case_id,),
            ).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            documents = connection.execute(
                """SELECT id, document_type, version_no, original_filename,
                          content_sha256, storage_path FROM documents
                   WHERE interview_case_id=? AND is_current=1 ORDER BY document_type""",
                (case_id,),
            ).fetchall()
            brief = connection.execute(
                "SELECT brief_json FROM interview_briefs WHERE interview_case_id=? AND is_current=1",
                (case_id,),
            ).fetchone()
            evaluation = connection.execute(
                """SELECT version_no, status, final_result, final_level, summary,
                          strengths_json, gaps_json, risks_json, final_comment, decided_at
                   FROM evaluations WHERE interview_case_id=? AND is_current=1""",
                (case_id,),
            ).fetchone()
        export_id = str(uuid.uuid4())
        self.export_root.mkdir(parents=True, exist_ok=True)
        target = (self.export_root / f"case-{case_id}-{export_id}.zip").resolve()
        self._require_inside(target, self.export_root)
        temporary = target.with_suffix(".zip.tmp")
        metadata = {
            "schemaVersion": "case-export.v1",
            "case": dict(case),
            "documents": [
                {key: row[key] for key in ("id", "document_type", "version_no", "original_filename", "content_sha256")}
                for row in documents
            ],
            "interviewBrief": None if brief is None else json.loads(brief["brief_json"]),
            "finalEvaluation": None if evaluation is None else dict(evaluation),
        }
        file_payloads: dict[str, bytes] = {
            "metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
        }
        if include_documents:
            for document in documents:
                if document["storage_path"]:
                    source = self.storage.resolve_relative(document["storage_path"])
                    if source.is_file():
                        suffix = source.suffix.lower()
                        file_payloads[f"documents/{document['id']}{suffix}"] = source.read_bytes()
        manifest = {
            "exportId": export_id, "caseId": case_id, "createdAt": _now(),
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in file_payloads.items()},
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in file_payloads.items():
                archive.writestr(name, data)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        os.replace(temporary, target)
        with self.database.transaction() as connection:
            append_audit(connection, actor_type="COMMITTEE", action="EXPORT_CREATED",
                entity_type="EXPORT", entity_id=export_id,
                metadata={"caseId": case_id, "includeDocuments": include_documents})
        return {"id": export_id, "status": "COMPLETED", "path": str(target)}

    def delete_case(self, case_id: str, *, confirmation: str, backup_id: str | None) -> None:
        if confirmation != "DELETE_CASE":
            raise ValidationError("Explicit case deletion confirmation is required")
        if not backup_id or self._backup_manifest(backup_id) is None:
            raise BackupRequired("A completed backup is required before deletion")
        with self.database.transaction() as connection:
            case = connection.execute("SELECT 1 FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            paths = [
                row[0] for row in connection.execute(
                    "SELECT storage_path FROM documents WHERE interview_case_id=? AND storage_path IS NOT NULL",
                    (case_id,),
                )
            ]
            append_audit(connection, actor_type="COMMITTEE", action="CASE_DELETE_REQUESTED",
                entity_type="INTERVIEW_CASE", entity_id=case_id,
                metadata={"backupId": backup_id})
            connection.execute("DELETE FROM interview_cases WHERE id=?", (case_id,))
            append_audit(connection, actor_type="COMMITTEE", action="CASE_DELETE_COMPLETED",
                entity_type="INTERVIEW_CASE", entity_id=case_id,
                metadata={"backupId": backup_id, "fileCount": len(paths)})
        for relative in paths:
            target = self.storage.resolve_relative(relative)
            if target.is_file():
                target.unlink()

    def _backup_manifest(self, backup_id: str) -> dict[str, Any] | None:
        if not self.backup_root.exists():
            return None
        for path in self.backup_root.glob("*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("backupId") == backup_id and (path.parent / "clawcv.db").is_file():
                return manifest
        return None

    @staticmethod
    def _require_inside(path: Path, root: Path) -> None:
        resolved_root = Path(root).resolve()
        resolved = Path(path).resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValidationError("Path is outside the permitted data directory")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
