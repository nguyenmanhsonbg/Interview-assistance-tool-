import unittest
from pathlib import Path

from app.ai.provider import ProviderError
from tests.ai_fixtures import question_addition_payload
from tests.support import MigratedDatabaseFixture


class AdditionProvider:
    def __init__(self, *, result=None, error=None):
        self.result = result or question_addition_payload()
        self.error = error
        self.calls = 0
        self.payloads = []

    def generate_question_addition(self, payload):
        self.calls += 1
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class QuestionAdditionTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService
        from app.services.document_service import DocumentService

        cases = CaseService(self.database)
        job = cases.create_job("J", "Engineer", "Senior")
        candidate = cases.create_candidate("C", "Candidate Name")
        self.case = cases.create_case(candidate["id"], job["id"])
        documents = DocumentService(self.database, self.data_root)
        jd = documents.import_manual_text(self.case["id"], "JD", "JD raw phone 0912345678")
        cv = documents.import_manual_text(self.case["id"], "CV", "CV raw candidate@example.com")
        documents.confirm(jd["id"], jd["contentSha256"])
        documents.confirm(cv["id"], cv["contentSha256"])
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='QUESTIONS_GENERATED' WHERE id=?",
                (self.case["id"],),
            )
            connection.execute(
                "INSERT INTO question_sets(id, interview_case_id, status) VALUES ('set-1', ?, 'GENERATED')",
                (self.case["id"],),
            )
            for number in range(1, 10):
                category = (
                    "FOUNDATION" if number <= 3
                    else "APPLICATION" if number <= 7
                    else "DEEP_DIVE"
                )
                connection.execute(
                    """INSERT INTO questions(
                        id, question_set_id, display_order, question_text,
                        competency_key, source_kind, question_category, purpose,
                        next_step_objective, question_type, difficulty,
                        expected_evidence, rubric_json, is_required, estimated_seconds
                    ) VALUES (?, 'set-1', ?, ?, 'backend', 'AI', ?,
                        'Purpose', 'Objective', 'SCENARIO', 'MEDIUM',
                        'Evidence', ?, 1, 60)""",
                    (
                        f"question-{number}", number, f"Question {number}", category,
                        '{"score0":"No evidence","score1":"Weak","score2":"Basic","score3":"Good","score4":"Excellent"}',
                    ),
                )

    def make_service(self):
        from app.services.question_addition_service import QuestionAdditionService

        return QuestionAdditionService(
            self.database,
            Path(__file__).resolve().parents[1] / "schemas",
            provider_name="gemini",
            model_name="gemini-3.6-flash",
        )

    def test_request_validates_modes_and_is_idempotent(self):
        from app.domain.errors import StateConflict, ValidationError

        service = self.make_service()
        first = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "USER_PROMPT",
            "Focus on incident response", "addition-key",
        )
        duplicate = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "USER_PROMPT",
            "Focus on incident response", "addition-key",
        )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual("GENERATE_QUESTION_ADDITION", first["taskType"])
        self.assertEqual("APPLICATION", first["targetQuestionCategory"])
        self.assertEqual("USER_PROMPT", first["inputManifest"]["mode"])
        self.assertEqual("Focus on incident response", first["inputManifest"]["prompt"])
        with self.assertRaises(StateConflict):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "USER_PROMPT",
                "Different input", "addition-key",
            )
        service.request_addition(
            self.case["id"], "set-1", "FOUNDATION", "AUTO_GROUP", None,
            "auto-key",
        )
        with self.assertRaises(ValidationError):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "USER_PROMPT", "   ",
                "blank-key",
            )
        with self.assertRaises(ValidationError):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", "prompt",
                "auto-prompt-key",
            )
        with self.assertRaises(ValidationError):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "USER_PROMPT", "x" * 2001,
                "long-key",
            )

    def test_request_rejects_invalid_or_locked_question_set(self):
        from app.domain.errors import ResourceNotFound, StateConflict, ValidationError

        service = self.make_service()
        with self.assertRaises(ValidationError):
            service.request_addition(
                self.case["id"], "set-1", "UNKNOWN", "AUTO_GROUP", None, "bad-category",
            )
        with self.assertRaises(ResourceNotFound):
            service.request_addition(
                self.case["id"], "missing", "APPLICATION", "AUTO_GROUP", None, "missing-set",
            )
        with self.database.transaction() as connection:
            connection.execute("UPDATE question_sets SET status='APPROVED' WHERE id='set-1'")
        with self.assertRaises(StateConflict):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "approved-set",
            )
        with self.database.transaction() as connection:
            connection.execute("UPDATE question_sets SET status='GENERATED' WHERE id='set-1'")
            connection.execute(
                """INSERT INTO assessment_attempts(id, interview_case_id, question_set_id)
                   VALUES ('attempt-1', ?, 'set-1')""",
                (self.case["id"],),
            )
        with self.assertRaises(StateConflict):
            service.request_addition(
                self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "assessment-lock",
            )

    def test_process_materializes_proposal_without_mutating_questions(self):
        service = self.make_service()
        task = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "process-key",
        )
        provider = AdditionProvider()
        result = service.process(task["id"], provider)

        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual("QUESTION_ADDITION", result["result"]["resultType"])
        proposal = service.get_proposal(self.case["id"], "set-1", result["proposalId"])
        self.assertEqual("PROPOSED", proposal["status"])
        self.assertEqual("APPLICATION", proposal["targetCategory"])
        self.assertEqual(9, self._question_count())
        payload = provider.payloads[0]
        self.assertEqual("GENERATE_QUESTION_ADDITION", payload["operation"])
        self.assertEqual("APPLICATION", payload["targetCategory"])
        self.assertIn("existingQuestions", payload)
        self.assertTrue(
            any(
                "[REDACTED_PHONE]" in document["sanitizedText"]
                for document in payload["documents"]
            )
        )
        self.assertNotIn("candidate@example.com", str(payload))
        self.assertEqual("QUESTION_ADDITION_GENERATED", self._latest_audit_action())

    def test_provider_failure_keeps_questions_and_proposals_absent(self):
        service = self.make_service()
        task = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "failure-key",
        )
        provider = AdditionProvider(
            error=ProviderError("timeout", code="AI_TIMEOUT", retryable=True)
        )

        retry = service.process(task["id"], provider)
        failed = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", retry["status"])
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual(0, self._proposal_count())
        self.assertEqual(9, self._question_count())
        self.assertEqual("QUESTION_ADDITION_FAILED", self._latest_audit_action())

    def test_result_versions_are_scoped_by_question_set_and_category(self):
        service = self.make_service()
        first_task = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "version-1",
        )
        first = service.process(first_task["id"], AdditionProvider())
        second_task = service.request_addition(
            self.case["id"], "set-1", "FOUNDATION", "AUTO_GROUP", None, "version-2",
        )
        second = service.process(
            second_task["id"],
            AdditionProvider(result=question_addition_payload("FOUNDATION")),
        )
        third_task = service.request_addition(
            self.case["id"], "set-1", "APPLICATION", "AUTO_GROUP", None, "version-3",
        )
        third = service.process(third_task["id"], AdditionProvider())

        self.assertEqual(1, first["result"]["versionNo"])
        self.assertEqual(1, second["result"]["versionNo"])
        self.assertEqual(2, third["result"]["versionNo"])
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT target_question_category, version_no, is_current
                   FROM ai_results WHERE result_type='QUESTION_ADDITION'
                   ORDER BY target_question_category, version_no"""
            ).fetchall()
        self.assertEqual(
            [("APPLICATION", 1, 0), ("APPLICATION", 2, 1), ("FOUNDATION", 1, 1)],
            [tuple(row) for row in rows],
        )

    def _question_count(self):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM questions WHERE question_set_id='set-1'"
            ).fetchone()[0]

    def _proposal_count(self):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM question_addition_proposals"
            ).fetchone()[0]

    def _latest_audit_action(self):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT action FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
