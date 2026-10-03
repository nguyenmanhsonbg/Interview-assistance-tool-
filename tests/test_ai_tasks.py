import hashlib
import unittest

from tests.ai_fixtures import question_generation_payload
from tests.support import MigratedDatabaseFixture


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result or question_generation_payload()
        self.error = error
        self.calls = 0

    def generate_questions(self, payload):
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


if __name__ == "__main__":
    unittest.main()
