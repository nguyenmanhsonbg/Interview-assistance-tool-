import hashlib
import unittest
from pathlib import Path

from app.ai.provider import ProviderError
from tests.ai_fixtures import question_variant_payload
from tests.support import MigratedDatabaseFixture


class VariantProvider:
    def __init__(self, *, result=None, error=None):
        self.result = result or question_variant_payload()
        self.error = error
        self.calls = 0
        self.payloads = []

    def generate_question_variant(self, payload):
        self.calls += 1
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class QuestionVariantTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("J", "Engineer", "Senior")
        candidate = cases.create_candidate("C", "Candidate")
        self.case = cases.create_case(candidate["id"], job["id"])
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
                        f"question-{number}",
                        number,
                        f"Question {number}",
                        category,
                        '{"score0":"No evidence","score1":"Weak","score2":"Basic","score3":"Good","score4":"Excellent"}',
                    ),
                )

    def make_service(self):
        from app.ai.schemas import SchemaRegistry
        from app.services.question_variant_service import QuestionVariantService

        return QuestionVariantService(
            self.database,
            Path(__file__).resolve().parents[1] / "schemas",
        )

    def test_request_is_idempotent_and_records_source_fingerprint(self):
        service = self.make_service()

        first = service.request_variant(
            self.case["id"], "set-1", "question-1", "USER_PROMPT",
            "Hãy làm rõ trade-off", "variant-idempotency",
        )
        duplicate = service.request_variant(
            self.case["id"], "set-1", "question-1", "USER_PROMPT",
            "Hãy làm rõ trade-off", "variant-idempotency",
        )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual("GENERATE_QUESTION_VARIANT", first["taskType"])
        self.assertEqual("question-1", first["sourceQuestionId"])
        self.assertEqual(64, len(first["inputFingerprint"]))
        self.assertEqual("set-1", first["inputManifest"]["questionSetId"])
        self.assertEqual("USER_PROMPT", first["inputManifest"]["mode"])
        with self.database.connection() as connection:
            task_count = connection.execute(
                "SELECT COUNT(*) FROM ai_tasks WHERE task_type='GENERATE_QUESTION_VARIANT'"
            ).fetchone()[0]
            proposal_count = connection.execute(
                "SELECT COUNT(*) FROM question_variant_proposals"
            ).fetchone()[0]
        self.assertEqual(1, task_count)
        self.assertEqual(0, proposal_count)

    def test_process_materializes_proposal_without_applying_question(self):
        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "same-group-key",
        )
        result = service.process(task["id"], VariantProvider())

        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual("QUESTION_VARIANT", result["result"]["resultType"])
        self.assertEqual("question-1", result["sourceQuestionId"])
        proposal = service.get_proposal(
            self.case["id"], "set-1", "question-1", result["proposalId"]
        )
        self.assertEqual("PROPOSED", proposal["status"])
        self.assertEqual("SAME_GROUP", proposal["mode"])
        self.assertEqual("Question 1", self._question_text("question-1"))
        self.assertEqual(
            "QUESTION_VARIANT_GENERATED",
            self._latest_audit_action(),
        )

    def test_multiple_question_slots_can_materialize_variants_with_independent_versions(self):
        service = self.make_service()

        first_task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "same-group-question-1-key",
        )
        first = service.process(first_task["id"], VariantProvider())

        second_task = service.request_variant(
            self.case["id"], "set-1", "question-2", "SAME_GROUP",
            None, "same-group-question-2-key",
        )
        second_result = question_variant_payload()
        second_result["mode"] = "SAME_GROUP"
        second_result["sourceQuestionId"] = "question-2"
        second = service.process(second_task["id"], VariantProvider(result=second_result))

        self.assertEqual("COMPLETED", first["status"])
        self.assertEqual("COMPLETED", second["status"])
        self.assertEqual(1, first["result"]["versionNo"])
        self.assertEqual(1, second["result"]["versionNo"])
        self.assertNotEqual(first["result"]["id"], second["result"]["id"])

    def test_provider_failure_keeps_question_and_proposal_absent(self):
        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "failure-key",
        )
        provider = VariantProvider(
            error=ProviderError("timeout", code="AI_TIMEOUT", retryable=True)
        )

        retry = service.process(task["id"], provider)
        failed = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", retry["status"])
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual("Question 1", self._question_text("question-1"))
        with self.database.connection() as connection:
            proposal_count = connection.execute(
                "SELECT COUNT(*) FROM question_variant_proposals"
            ).fetchone()[0]
        self.assertEqual(0, proposal_count)
        self.assertEqual("QUESTION_VARIANT_FAILED", self._latest_audit_action())

    def test_schema_failure_retries_with_repair_instruction_without_mutation(self):
        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "USER_PROMPT",
            "Tập trung vào tính vận hành", "schema-key",
        )
        invalid = question_variant_payload()
        invalid["operation"] = "WRONG"
        provider = VariantProvider(result=invalid)

        retry = service.process(task["id"], provider)
        failed = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", retry["status"])
        self.assertEqual("FAILED", failed["status"])
        self.assertNotIn("repairInstruction", provider.payloads[0])
        self.assertIn("repairInstruction", provider.payloads[1])
        self.assertEqual("Question 1", self._question_text("question-1"))

    def test_apply_replaces_only_content_and_marks_proposal_applied(self):
        from app.repositories.questions import QuestionRepository

        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "apply-key",
        )
        processed = service.process(task["id"], VariantProvider())
        before_set = QuestionRepository(self.database).get_set("set-1")
        proposal = processed["proposal"]

        applied = service.apply_proposal(
            self.case["id"],
            "set-1",
            "question-1",
            proposal["id"],
            before_set["updatedAt"],
            proposal["sourceFingerprint"],
        )

        question = applied["question"]
        self.assertEqual("question-1", question["id"])
        self.assertEqual(1, question["displayOrder"])
        self.assertEqual("backend", question["competencyKey"])
        self.assertEqual("FOUNDATION", question["questionCategory"])
        self.assertEqual("SCENARIO", question["questionType"])
        self.assertEqual("MEDIUM", question["difficulty"])
        self.assertNotEqual("Question 1", question["questionText"])
        self.assertEqual("APPLIED", applied["proposal"]["status"])
        self.assertEqual("QUESTION_VARIANT_APPLIED", self._latest_audit_action())

    def test_discard_is_idempotent_and_never_changes_question(self):
        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "discard-key",
        )
        processed = service.process(task["id"], VariantProvider())
        proposal_id = processed["proposalId"]

        discarded = service.discard_proposal(
            self.case["id"], "set-1", "question-1", proposal_id
        )
        repeated = service.discard_proposal(
            self.case["id"], "set-1", "question-1", proposal_id
        )

        self.assertEqual("DISCARDED", discarded["status"])
        self.assertEqual("DISCARDED", repeated["status"])
        self.assertEqual("Question 1", self._question_text("question-1"))

    def test_apply_rejects_stale_manual_edit_and_preserves_manual_content(self):
        from app.domain.errors import StateConflict
        from app.repositories.questions import QuestionRepository
        from app.services.question_service import QuestionService

        service = self.make_service()
        task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "stale-key",
        )
        processed = service.process(task["id"], VariantProvider())
        before_set = QuestionRepository(self.database).get_set("set-1")
        proposal = processed["proposal"]
        edited = before_set["questions"]
        edited[0]["questionText"] = "Manual edit wins"
        QuestionService(self.database).update_draft("set-1", edited)

        with self.assertRaises(StateConflict):
            service.apply_proposal(
                self.case["id"], "set-1", "question-1", proposal["id"],
                before_set["updatedAt"], proposal["sourceFingerprint"],
            )
        self.assertEqual("Manual edit wins", self._question_text("question-1"))
        self.assertIn("QUESTION_MANUALLY_EDITED", self._audit_actions())

    def test_apply_rejects_approved_and_assessment_started_question_sets(self):
        from app.domain.errors import StateConflict
        from app.repositories.questions import QuestionRepository

        service = self.make_service()
        approved_task = service.request_variant(
            self.case["id"], "set-1", "question-1", "SAME_GROUP",
            None, "approved-lock-key",
        )
        approved_processed = service.process(approved_task["id"], VariantProvider())
        approved_set = QuestionRepository(self.database).get_set("set-1")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE question_sets SET status='APPROVED' WHERE id='set-1'"
            )
        with self.assertRaises(StateConflict):
            service.apply_proposal(
                self.case["id"], "set-1", "question-1",
                approved_processed["proposalId"], approved_set["updatedAt"],
                approved_processed["proposal"]["sourceFingerprint"],
            )

        with self.database.transaction() as connection:
            connection.execute("UPDATE question_sets SET status='GENERATED' WHERE id='set-1'")
            connection.execute(
                """INSERT INTO assessment_attempts(id, interview_case_id, question_set_id, status)
                   VALUES ('attempt-1', ?, 'set-1', 'ASSESSMENT_IN_PROGRESS')""",
                (self.case["id"],),
            )
        with self.assertRaises(StateConflict):
            service.request_variant(
                self.case["id"], "set-1", "question-1", "SAME_GROUP",
                None, "assessment-lock-key",
            )

    def _question_text(self, question_id):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT question_text FROM questions WHERE id=?", (question_id,)
            ).fetchone()[0]

    def _latest_audit_action(self):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT action FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()[0]

    def _audit_actions(self):
        with self.database.connection() as connection:
            return [
                row[0]
                for row in connection.execute("SELECT action FROM audit_logs").fetchall()
            ]


if __name__ == "__main__":
    unittest.main()
