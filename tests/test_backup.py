import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.support import MigratedDatabaseFixture


class BackupTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("JOB-BACKUP", "Engineer", "Senior")
        candidate = cases.create_candidate("CAND-BACKUP", "Backup Candidate")
        self.case = cases.create_case(candidate["id"], job["id"])

    def test_online_backup_restores_to_independent_valid_database(self):
        from app.services.backup_service import BackupService

        service = BackupService(self.database, self.data_root)
        backup = service.create_backup("before-change")
        with self.database.transaction() as connection:
            connection.execute("UPDATE candidates SET full_name='Changed' WHERE id=?", (self.case["candidateId"],))
        restored = self.data_root / "restore" / "restored.db"
        result = service.restore_to(backup["databasePath"], restored)
        self.assertEqual("ok", result["integrity"])
        import sqlite3
        connection = sqlite3.connect(restored)
        try:
            name = connection.execute("SELECT full_name FROM candidates WHERE id=?", (self.case["candidateId"],)).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("Backup Candidate", name)

    def test_export_excludes_secrets_and_safe_delete_creates_backup_with_retained_audit(self):
        from app.services.backup_service import BackupService

        secret = "do-not-export-secret"
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO app_settings(key, value_type, protected_value, is_sensitive)
                   VALUES ('provider_secret', 'SECRET_REF', ?, 1)""", (secret.encode(),),
            )
        service = BackupService(self.database, self.data_root)
        export = service.export_case(self.case["id"], include_documents=False)
        with zipfile.ZipFile(export["path"]) as archive:
            content = b"".join(archive.read(name) for name in archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
        self.assertNotIn(secret.encode(), content)
        self.assertTrue(manifest["files"])
        backup = service.backup_and_delete_case(
            self.case["id"], confirmation="DELETE_CASE"
        )
        self.assertTrue(Path(backup["manifestPath"]).is_file())
        with self.database.connection() as connection:
            exists = connection.execute("SELECT 1 FROM interview_cases WHERE id=?", (self.case["id"],)).fetchone()
            actions = {row[0] for row in connection.execute("SELECT action FROM audit_logs WHERE entity_id=?", (self.case["id"],))}
        self.assertIsNone(exists)
        self.assertIn("CASE_DELETE_COMPLETED", actions)

    def test_delete_file_failure_is_reported_and_audited_without_false_success(self):
        from app.services.backup_service import BackupService
        from app.services.document_service import DocumentService

        documents = DocumentService(self.database, self.data_root)
        documents.import_file(
            self.case["id"], "CV", "candidate.txt", "text/plain", b"CV content"
        )
        service = BackupService(self.database, self.data_root)
        with patch.object(Path, "unlink", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                service.backup_and_delete_case(
                    self.case["id"],
                    confirmation="DELETE_CASE",
                )

        with self.database.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM interview_cases WHERE id=?", (self.case["id"],)
            ).fetchone()
            actions = [
                row[0]
                for row in connection.execute(
                    "SELECT action FROM audit_logs WHERE entity_id=? ORDER BY created_at",
                    (self.case["id"],),
                )
            ]
        self.assertIsNone(exists)
        self.assertIn("CASE_DELETE_REQUESTED", actions)
        self.assertIn("CASE_DELETE_FAILED", actions)
        self.assertNotIn("CASE_DELETE_COMPLETED", actions)
        self.assertTrue(any((self.data_root / "deletion-staging").rglob("*.*")))

    def test_backup_and_delete_blocks_concurrent_document_import(self):
        from app.domain.errors import ResourceNotFound
        from app.services.backup_service import BackupService
        from app.services.document_service import DocumentService

        service = BackupService(self.database, self.data_root)
        documents = DocumentService(self.database, self.data_root)
        backup_started = threading.Event()
        release_backup = threading.Event()
        import_finished = threading.Event()
        case_mutation_finished = threading.Event()
        errors = []
        original_create_backup = service.create_backup

        def slow_backup(*args, **kwargs):
            backup_started.set()
            self.assertTrue(release_backup.wait(2))
            return original_create_backup(*args, **kwargs)

        def delete_case():
            try:
                service.backup_and_delete_case(
                    self.case["id"], confirmation="DELETE_CASE"
                )
            except Exception as error:
                errors.append(error)

        def import_document():
            try:
                documents.import_file(
                    self.case["id"], "CV", "late.txt", "text/plain", b"late CV"
                )
            except Exception as error:
                errors.append(error)
            finally:
                import_finished.set()

        def cancel_case():
            from app.services.case_service import CaseService

            try:
                CaseService(self.database).cancel_case(self.case["id"], "concurrent")
            except Exception as error:
                errors.append(error)
            finally:
                case_mutation_finished.set()

        with patch.object(service, "create_backup", side_effect=slow_backup):
            deleting = threading.Thread(target=delete_case)
            deleting.start()
            self.assertTrue(backup_started.wait(2))
            importing = threading.Thread(target=import_document)
            importing.start()
            mutating = threading.Thread(target=cancel_case)
            mutating.start()
            self.assertFalse(import_finished.wait(0.1))
            self.assertFalse(case_mutation_finished.wait(0.1))
            release_backup.set()
            deleting.join(3)
            importing.join(3)
            mutating.join(3)

        self.assertFalse(deleting.is_alive())
        self.assertFalse(importing.is_alive())
        self.assertFalse(mutating.is_alive())
        self.assertTrue(any(isinstance(error, ResourceNotFound) for error in errors))
        case_root = self.data_root / "documents" / self.case["id"]
        self.assertFalse(case_root.exists() and any(case_root.rglob("*.*")))


if __name__ == "__main__":
    unittest.main()
