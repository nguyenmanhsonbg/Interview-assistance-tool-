import json
import logging
import tempfile
import unittest
from pathlib import Path

from tests.support import MigratedDatabaseFixture


class AuditLoggingTests(MigratedDatabaseFixture, unittest.TestCase):
    def test_audit_metadata_and_rotating_log_redact_sensitive_content(self):
        from app.services.audit_service import AuditService, configure_safe_logger

        service = AuditService(self.database)
        service.record(
            actor_type="SYSTEM", action="SETTINGS_UPDATED", entity_type="SETTING",
            entity_id="ai", metadata={"apiKey": "secret-key", "answerText": "private answer", "count": 2},
        )
        with self.database.connection() as connection:
            row = connection.execute("SELECT metadata_json FROM audit_logs ORDER BY created_at DESC LIMIT 1").fetchone()
        metadata = json.loads(row["metadata_json"])
        self.assertEqual("[REDACTED]", metadata["apiKey"])
        self.assertEqual("[REDACTED]", metadata["answerText"])
        self.assertEqual(2, metadata["count"])

        log_path = self.data_root / "logs" / "app.log"
        logger = configure_safe_logger(log_path)
        logger.info("request", extra={"safe_fields": {"requestId": "r1", "candidateToken": "token-secret"}})
        for handler in logger.handlers:
            handler.flush()
        content = log_path.read_text(encoding="utf-8")
        self.assertNotIn("token-secret", content)
        self.assertIn("[REDACTED]", content)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
