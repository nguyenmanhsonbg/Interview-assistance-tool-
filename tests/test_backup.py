import json
import tempfile
import unittest
import zipfile
from pathlib import Path

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

    def test_export_excludes_secrets_and_delete_requires_backup_with_retained_audit(self):
        from app.domain.errors import BackupRequired
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
        with self.assertRaises(BackupRequired):
            service.delete_case(self.case["id"], confirmation="DELETE_CASE", backup_id=None)
        backup = service.create_backup("before-delete")
        service.delete_case(self.case["id"], confirmation="DELETE_CASE", backup_id=backup["id"])
        with self.database.connection() as connection:
            exists = connection.execute("SELECT 1 FROM interview_cases WHERE id=?", (self.case["id"],)).fetchone()
            actions = {row[0] for row in connection.execute("SELECT action FROM audit_logs WHERE entity_id=?", (self.case["id"],))}
        self.assertIsNone(exists)
        self.assertIn("CASE_DELETE_COMPLETED", actions)


if __name__ == "__main__":
    unittest.main()
