import json
import unittest
from pathlib import Path

from tests.ai_fixtures import answer_evaluation_payload
from tests.evaluation_setup import create_submitted_assessment
from tests.support import MigratedDatabaseFixture


class EvaluationProvider:
    def evaluate_answers(self, payload):
        self.payload = payload
        return answer_evaluation_payload(answered=True)


class AIEvaluationTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, self.question_set, self.member_id, self.attempt = (
            create_submitted_assessment(self)
        )

    def test_manifest_has_references_not_raw_answers_and_provider_gets_snapshot(self):
        from app.services.evaluation_service import EvaluationService

        service = EvaluationService(self.database, Path(__file__).resolve().parents[1] / "schemas")
        task = service.request(
            self.case["id"], self.attempt["id"], idempotency_key="evaluation-1"
        )
        serialized = json.dumps(task["inputManifest"])
        self.assertNotIn("My private example", serialized)
        self.assertNotIn("answerText", serialized)
        self.assertEqual("AI_ANALYZING", service.case_status(self.case["id"]))

        provider = EvaluationProvider()
        completed = service.process(task["id"], provider)
        self.assertEqual("COMPLETED", completed["status"])
        self.assertNotIn("fullName", provider.payload["candidate"])
        self.assertEqual("My private example with concrete evidence", provider.payload["answers"][0]["answerText"])
        self.assertFalse(provider.payload["answers"][1]["isAnswered"])

    def test_evaluation_uses_documents_bound_to_question_set_not_current_pointer(self):
        from app.services.evaluation_service import EvaluationService

        with self.database.transaction() as connection:
            policy = json.loads(connection.execute(
                "SELECT question_policy_json FROM question_sets WHERE id=?",
                (self.question_set["id"],),
            ).fetchone()[0])
            source_documents = policy["sourceDocuments"]
            original_cv = next(
                item for item in source_documents if item["document_type"] == "CV"
            )
            connection.execute(
                "UPDATE documents SET is_current=0 WHERE id=?", (original_cv["id"],)
            )
            connection.execute(
                """INSERT INTO documents(
                    id, interview_case_id, document_type, version_no, source_kind,
                    extraction_status, content_sha256, extracted_text,
                    is_ai_eligible, is_current, supersedes_document_id
                ) VALUES ('replacement-cv', ?, 'CV', 2, 'MANUAL_TEXT',
                    'MANUAL_CONFIRMED', ?, 'replacement text', 1, 1, ?)""",
                (self.case["id"], "0" * 64, original_cv["id"]),
            )

        service = EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )
        task = service.request(
            self.case["id"], self.attempt["id"], idempotency_key="evaluation-provenance"
        )

        manifest_cv = next(
            item for item in task["inputManifest"]["documents"]
            if item["document_type"] == "CV"
        )
        self.assertEqual(original_cv["id"], manifest_cv["id"])

    def test_failed_analysis_keeps_original_answers_readable(self):
        from app.ai.provider import ProviderError
        from app.services.evaluation_service import EvaluationService

        class FailingProvider:
            def evaluate_answers(self, payload):
                raise ProviderError("offline", code="AI_OFFLINE", retryable=True)

        service = EvaluationService(self.database, Path(__file__).resolve().parents[1] / "schemas")
        task = service.request(
            self.case["id"], self.attempt["id"], idempotency_key="evaluation-fail"
        )
        service.process(task["id"], FailingProvider())
        failed = service.process(task["id"], FailingProvider())
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual("AI_ANALYSIS_FAILED", service.case_status(self.case["id"]))
        snapshot = service.answer_snapshot(self.attempt["id"])
        self.assertEqual("My private example with concrete evidence", snapshot[0]["answerText"])


if __name__ == "__main__":
    unittest.main()
