import unittest
from pathlib import Path

from tests.ai_fixtures import answer_evaluation_payload
from tests.evaluation_setup import create_submitted_assessment
from tests.support import MigratedDatabaseFixture


def manual_brief(additional=0):
    return {
        "summary": "Committee fallback summary",
        "strengths": [], "gaps": ["AI unavailable"], "conflicts": [],
        "competencyMatrix": [],
        "requiredLiveQuestions": ["One", "Two", "Three"],
        "additionalLiveQuestions": [f"Additional {i}" for i in range(additional)],
        "limitations": ["Prepared manually"],
    }


class BriefTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, _, self.member_id, self.attempt = create_submitted_assessment(self)

    def test_manual_fallback_is_versioned_and_current(self):
        from app.services.interview_brief_service import InterviewBriefService

        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='AI_ANALYSIS_FAILED' WHERE id=?",
                (self.case["id"],),
            )
        service = InterviewBriefService(self.database)
        first = service.create_manual(
            self.case["id"], self.attempt["id"], manual_brief(), self.member_id
        )
        second = service.create_manual(
            self.case["id"], self.attempt["id"], manual_brief(2), self.member_id
        )
        self.assertEqual(1, first["versionNo"])
        self.assertEqual(2, second["versionNo"])
        self.assertEqual(second["id"], service.current(self.case["id"])["id"])
        with self.database.connection() as connection:
            old = connection.execute(
                "SELECT status, is_current FROM interview_briefs WHERE id=?", (first["id"],)
            ).fetchone()
        self.assertEqual(("SUPERSEDED", 0), tuple(old))

    def test_brief_rejects_more_than_two_additional_questions(self):
        from app.domain.errors import ValidationError
        from app.services.interview_brief_service import InterviewBriefService

        with self.assertRaises(ValidationError):
            InterviewBriefService(self.database).create_manual(
                self.case["id"], self.attempt["id"], manual_brief(3), self.member_id
            )

    def test_completed_ai_result_materializes_ai_brief(self):
        from app.services.evaluation_service import EvaluationService
        from app.services.interview_brief_service import InterviewBriefService

        class Provider:
            def evaluate_answers(self, payload):
                return answer_evaluation_payload(answered=True)

        evaluations = EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )
        task = evaluations.request(
            self.case["id"], self.attempt["id"], idempotency_key="brief-ai"
        )
        evaluations.process(task["id"], Provider())
        brief = InterviewBriefService(self.database).materialize_ai(task["id"])
        self.assertEqual("AI", brief["sourceKind"])
        self.assertEqual(3, len(brief["brief"]["requiredLiveQuestions"]))
        self.assertEqual("INTERVIEW_BRIEF_READY", evaluations.case_status(self.case["id"]))


if __name__ == "__main__":
    unittest.main()
