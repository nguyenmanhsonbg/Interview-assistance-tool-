import hashlib
import unittest
from pathlib import Path

from app.ai.provider import ProviderError
from tests.support import MigratedDatabaseFixture


class LevelProvider:
    def __init__(self, *, result=None, error=None):
        self.result = result or {
            "schemaVersion": "job-level-extraction.v1",
            "targetLevel": "Senior",
            "confidence": 0.92,
            "evidence": ["Senior Backend Engineer", "5+ years"],
        }
        self.error = error
        self.payloads = []

    def extract_job_level(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class JobLevelServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("JOB-LEVEL", "Backend Engineer", None)
        candidate = cases.create_candidate("CAND-LEVEL", "Nguyen Van A")
        self.case = cases.create_case(candidate["id"], job["id"])
        self.case_id = self.case["id"]
        self.job_id = job["id"]
        from app.services.document_service import DocumentService

        self.documents = DocumentService(self.database, self.data_root)
        self.jd = self.documents.import_manual_text(
            self.case_id, "JD", "Senior Backend Engineer\n5+ years of experience"
        )
        self.documents.confirm(self.jd["id"], self.jd["contentSha256"])

    def service(self):
        from app.services.job_level_service import JobLevelService

        return JobLevelService(
            self.database,
            Path(__file__).resolve().parents[1] / "schemas",
            provider_name="gemini",
            model_name="gemini-3.6-flash",
        )

    def test_confirmed_jd_enqueues_idempotent_task_with_sanitized_jd_only(self):
        service = self.service()
        first = service.request_for_confirmed_jd(self.case_id)
        duplicate = service.request_for_confirmed_jd(self.case_id)

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual("EXTRACT_JOB_LEVEL", first["taskType"])
        manifest = first["inputManifest"]
        self.assertEqual(self.jd["id"], manifest["document"]["id"])
        self.assertEqual(self.jd["versionNo"], manifest["document"]["versionNo"])
        self.assertEqual(self.jd["contentSha256"], manifest["document"]["contentSha256"])
        self.assertIn("sanitizedText", manifest["document"])
        self.assertNotIn("storagePath", manifest["document"])
        self.assertNotIn("CV", str(manifest))
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT target_level_status FROM jobs WHERE id=?", (self.job_id,)
            ).fetchone()
        self.assertEqual("EXTRACTING", row[0])

    def test_successful_extraction_updates_job_and_audits_without_raw_evidence(self):
        service = self.service()
        task = service.request_for_confirmed_jd(self.case_id)
        provider = LevelProvider()

        completed = service.process(task["id"], provider)

        self.assertEqual("COMPLETED", completed["status"])
        self.assertEqual(self.jd["id"], provider.payloads[0]["document"]["documentId"])
        self.assertNotIn("fullName", provider.payloads[0])
        with self.database.connection() as connection:
            job = connection.execute(
                "SELECT target_level, target_level_status, target_level_source, target_level_confidence FROM jobs WHERE id=?",
                (self.job_id,),
            ).fetchone()
            actions = [
                row[0]
                for row in connection.execute(
                    "SELECT action FROM audit_logs WHERE entity_id=? ORDER BY created_at",
                    (task["id"],),
                )
            ]
            result_payload = connection.execute(
                "SELECT payload_json FROM ai_results WHERE ai_task_id=?", (task["id"],)
            ).fetchone()[0]
        self.assertEqual(("Senior", "READY", "JD_AI", 0.92), tuple(job))
        self.assertIn("AI_TASK_COMPLETED", actions)
        self.assertIn("Senior Backend Engineer", result_payload)

    def test_stale_jd_output_does_not_overwrite_current_job_level(self):
        service = self.service()
        task = service.request_for_confirmed_jd(self.case_id)
        replacement = self.documents.import_manual_text(
            self.case_id, "JD", "Junior Backend Engineer\n1 year of experience"
        )
        self.documents.confirm(replacement["id"], replacement["contentSha256"])

        result = service.process(task["id"], LevelProvider())

        self.assertIn(result["status"], {"FAILED", "COMPLETED"})
        with self.database.connection() as connection:
            job = connection.execute(
                "SELECT target_level, target_level_status FROM jobs WHERE id=?", (self.job_id,)
            ).fetchone()
        self.assertIsNone(job[0])
        self.assertNotEqual("READY", job[1])

    def test_new_confirmed_jd_fingerprint_reprovisions_level_after_ready(self):
        service = self.service()
        first = service.request_for_confirmed_jd(self.case_id)
        service.process(first["id"], LevelProvider())

        replacement = self.documents.import_manual_text(
            self.case_id, "JD", "Junior Backend Engineer\n1 year of experience"
        )
        self.documents.confirm(replacement["id"], replacement["contentSha256"])

        second = service.request_for_confirmed_jd(self.case_id)

        self.assertIsNotNone(second)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual("EXTRACT_JOB_LEVEL", second["taskType"])

    def test_stale_extraction_does_not_reset_newer_jd_extraction(self):
        service = self.service()
        first = service.request_for_confirmed_jd(self.case_id)
        replacement = self.documents.import_manual_text(
            self.case_id, "JD", "Junior Backend Engineer\n1 year of experience"
        )
        self.documents.confirm(replacement["id"], replacement["contentSha256"])
        second = service.request_for_confirmed_jd(self.case_id)

        service.process(first["id"], LevelProvider())

        with self.database.connection() as connection:
            status = connection.execute(
                "SELECT target_level_status FROM jobs WHERE id=?", (self.job_id,)
            ).fetchone()[0]
        self.assertEqual("EXTRACTING", status)
        self.assertNotEqual(first["id"], second["id"])

    def test_provider_failure_marks_level_failed_without_default(self):
        service = self.service()
        task = service.request_for_confirmed_jd(self.case_id)
        result = service.process(
            task["id"],
            LevelProvider(error=ProviderError("timeout", code="AI_TIMEOUT", retryable=False)),
        )

        self.assertEqual("FAILED", result["status"])
        with self.database.connection() as connection:
            job = connection.execute(
                "SELECT target_level, target_level_status FROM jobs WHERE id=?", (self.job_id,)
            ).fetchone()
        self.assertEqual((None, "FAILED"), tuple(job))


if __name__ == "__main__":
    unittest.main()
