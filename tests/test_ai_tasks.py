import hashlib
import threading
import unittest

from tests.ai_fixtures import question_generation_payload
from tests.support import MigratedDatabaseFixture


class FakeProvider:
    def __init__(self, result=None, error=None, level_result=None):
        self.result = result or question_generation_payload()
        self.level_result = level_result or {
            "schemaVersion": "job-level-extraction.v1",
            "targetLevel": "Senior",
            "confidence": 0.92,
            "evidence": ["Senior Engineer"],
        }
        self.error = error
        self.calls = 0

    def extract_job_level(self, payload):
        self.calls += 1
        if self.error:
            raise self.error
        return self.level_result

    def generate_questions(self, payload):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def generate_question_variant(self, payload):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def evaluate_answers(self, payload):
        return self.result

    def suggest_follow_up(self, payload):
        return self.result


class AITaskTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("J", "Engineer", "Senior")
        candidate = cases.create_candidate("C", "Candidate")
        self.case = cases.create_case(candidate["id"], job["id"])
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='DOCUMENTS_READY' WHERE id=?",
                (self.case["id"],),
            )

    def enqueue(self, service, key="key-1"):
        return service.enqueue(
            self.case["id"], "GENERATE_QUESTIONS",
            input_manifest={"payload": {"candidateCode": "C"}},
            input_fingerprint=hashlib.sha256(b"input").hexdigest(),
            idempotency_key=key,
        )

    def test_idempotent_enqueue_and_successful_result_are_persistent(self):
        from app.ai.schemas import SchemaRegistry
        from app.services.ai_task_service import AITaskService
        from pathlib import Path

        service = AITaskService(
            self.database,
            SchemaRegistry(Path(__file__).resolve().parents[1] / "schemas"),
        )
        first = self.enqueue(service)
        duplicate = self.enqueue(service)
        completed = service.process(first["id"], FakeProvider())

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual("COMPLETED", completed["status"])
        self.assertEqual(1, completed["result"]["versionNo"])
        with self.database.connection() as connection:
            result_count = connection.execute("SELECT COUNT(*) FROM ai_results").fetchone()[0]
        self.assertEqual(1, result_count)

    def test_question_task_records_provider_metadata(self):
        from pathlib import Path

        from app.services.document_service import DocumentService
        from app.services.question_generation_service import QuestionGenerationService

        documents = DocumentService(self.database, self.data_root)
        jd = documents.import_manual_text(self.case["id"], "JD", "Senior role")
        cv = documents.import_manual_text(self.case["id"], "CV", "Relevant experience")
        documents.confirm(jd["id"], jd["contentSha256"])
        documents.confirm(cv["id"], cv["contentSha256"])

        service = QuestionGenerationService(
            self.database,
            Path(__file__).resolve().parents[1] / "schemas",
            provider_name="gemini",
            model_name="gemini-3.6-flash",
        )
        task = service.request(self.case["id"], idempotency_key="metadata-key")

        self.assertEqual(9, task["inputManifest"]["questionPolicy"]["maxQuestions"])
        self.assertEqual(
            {"foundation": 3, "application": 4, "deepDive": 2},
            task["inputManifest"]["questionPolicy"]["distribution"],
        )

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT provider, model FROM ai_tasks WHERE id=?", (task["id"],)
            ).fetchone()
        self.assertEqual("gemini", row["provider"])
        self.assertEqual("gemini-3.6-flash", row["model"])

    def test_job_level_task_uses_fixed_operation_and_completes(self):
        from app.ai.schemas import SchemaRegistry
        from app.services.ai_task_service import AITaskService
        from pathlib import Path

        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET target_level=NULL, target_level_status='PENDING', target_level_source=NULL WHERE id=?",
                (self.case["jobId"],),
            )
        service = AITaskService(
            self.database,
            SchemaRegistry(Path(__file__).resolve().parents[1] / "schemas"),
        )
        task = service.enqueue(
            self.case["id"], "EXTRACT_JOB_LEVEL",
            input_manifest={"jobId": self.case["jobId"], "document": {"id": "jd"}},
            input_fingerprint=hashlib.sha256(b"level-input").hexdigest(),
            idempotency_key="level-task-key",
        )
        completed = service.process(task["id"], FakeProvider())

        self.assertEqual("COMPLETED", completed["status"])
        self.assertEqual("JOB_LEVEL_EXTRACTION", completed["result"]["resultType"])
        with self.database.connection() as connection:
            status = connection.execute(
                "SELECT target_level_status FROM jobs WHERE id=?", (self.case["jobId"],)
            ).fetchone()[0]
        self.assertEqual("EXTRACTING", status)

    def test_job_level_task_restart_recovery_keeps_extraction_pending(self):
        from app.services.ai_task_service import AITaskService
        from app.ai.schemas import SchemaRegistry
        from pathlib import Path

        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET target_level=NULL, target_level_status='PENDING', target_level_source=NULL WHERE id=?",
                (self.case["jobId"],),
            )
        service = AITaskService(
            self.database,
            SchemaRegistry(Path(__file__).resolve().parents[1] / "schemas"),
        )
        task = service.enqueue(
            self.case["id"], "EXTRACT_JOB_LEVEL",
            input_manifest={"jobId": self.case["jobId"]},
            input_fingerprint=hashlib.sha256(b"recovery-input").hexdigest(),
            idempotency_key="level-recovery-key",
        )
        with self.database.transaction() as connection:
            connection.execute("UPDATE ai_tasks SET status='RUNNING' WHERE id=?", (task["id"],))

        recovered = service.recover_interrupted()

        self.assertEqual([task["id"]], recovered["pendingRetry"])
        with self.database.connection() as connection:
            status = connection.execute(
                "SELECT target_level_status FROM jobs WHERE id=?", (self.case["jobId"],)
            ).fetchone()[0]
        self.assertEqual("EXTRACTING", status)

    def test_retry_once_then_fail_and_restart_recovery(self):
        from app.ai.provider import ProviderError
        from app.ai.schemas import SchemaRegistry
        from app.services.ai_task_service import AITaskService
        from pathlib import Path

        service = AITaskService(
            self.database,
            SchemaRegistry(Path(__file__).resolve().parents[1] / "schemas"),
        )
        task = self.enqueue(service, "retry-key")
        failing = FakeProvider(error=ProviderError("timeout", code="AI_TIMEOUT", retryable=True))
        retry = service.process(task["id"], failing)
        failed = service.process(task["id"], failing)
        self.assertEqual("PENDING_RETRY", retry["status"])
        self.assertEqual("FAILED", failed["status"])

        running = self.enqueue(service, "recovery-key")
        with self.database.transaction() as connection:
            connection.execute("UPDATE ai_tasks SET status='RUNNING' WHERE id=?", (running["id"],))
        recovered = service.recover_interrupted()
        self.assertEqual([running["id"]], recovered["pendingRetry"])

    def test_schema_failure_gets_one_repair_retry_then_terminal_fallback(self):
        from app.ai.schemas import SchemaRegistry
        from app.services.ai_task_service import AITaskService
        from pathlib import Path

        class InvalidProvider:
            def __init__(self):
                self.payloads = []

            def generate_questions(self, payload):
                self.payloads.append(payload)
                return {"schemaVersion": "wrong"}

        service = AITaskService(
            self.database,
            SchemaRegistry(Path(__file__).resolve().parents[1] / "schemas"),
        )
        task = self.enqueue(service, "schema-retry")
        provider = InvalidProvider()
        retry = service.process(task["id"], provider)
        failed = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", retry["status"])
        self.assertEqual("FAILED", failed["status"])
        self.assertNotIn("repairInstruction", provider.payloads[0])
        self.assertIn("repairInstruction", provider.payloads[1])
        with self.database.connection() as connection:
            status = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (self.case["id"],)
            ).fetchone()[0]
        self.assertEqual("QUESTION_GENERATION_FAILED", status)

    def test_worker_continues_with_next_task_after_unexpected_processor_error(self):
        from app.ai.task_worker import AITaskWorker

        completed = threading.Event()

        class Processor:
            def process(self, task_id, provider):
                if task_id == "broken":
                    raise RuntimeError("simulated materialization failure")
                completed.set()

        worker = AITaskWorker(Processor(), FakeProvider())
        worker.start()
        try:
            worker.submit("broken")
            worker.submit("next")
            self.assertTrue(completed.wait(1), "worker stopped after the first task failed")
        finally:
            worker.stop()

    def test_worker_requeues_one_persistent_retry(self):
        from app.ai.task_worker import AITaskWorker

        completed = threading.Event()

        class Processor:
            calls = 0

            def process(self, task_id, provider):
                self.calls += 1
                if self.calls == 1:
                    return {"status": "PENDING_RETRY", "retryCount": 1}
                completed.set()
                return {"status": "COMPLETED", "retryCount": 1}

        processor = Processor()
        worker = AITaskWorker(processor, FakeProvider(), sleep=lambda _: None)
        worker.start()
        try:
            worker.submit("retry-me")
            self.assertTrue(completed.wait(1), "persistent retry was not requeued")
            self.assertEqual(2, processor.calls)
        finally:
            worker.stop()


if __name__ == "__main__":
    unittest.main()
