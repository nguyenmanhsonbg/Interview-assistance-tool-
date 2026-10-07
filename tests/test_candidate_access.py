import unittest

from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


class CandidateAccessTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.assessment_service import AssessmentService

        self.case, self.question_set, _ = create_approved_case(self)
        self.service = AssessmentService(self.database)
        attempt = self.service.prepare(self.case["id"], self.question_set["id"])
        self.started = self.service.start(
            self.case["id"], candidate_code_confirmed=True, committee_authorized=True
        )

    def test_candidate_token_is_scoped_and_projection_excludes_internal_fields(self):
        from app.domain.errors import Unauthenticated

        view = self.service.candidate_view(
            self.started["id"], self.started["candidateToken"]
        )
        self.assertEqual(9, len(view["questions"]))
        self.assertEqual(
            {"id", "displayOrder", "questionText", "questionType", "answerText", "isAnswered", "saveRevision"},
            set(view["questions"][0]),
        )
        serialized = str(view).lower()
        for forbidden in ("rubric", "expected_evidence", "competency", "cv", "airesult"):
            self.assertNotIn(forbidden, serialized)
        with self.assertRaises(Unauthenticated):
            self.service.candidate_view(self.started["id"], "wrong-token")

    def test_one_attempt_per_case_is_enforced(self):
        from app.domain.errors import StateConflict

        with self.assertRaises(StateConflict):
            self.service.prepare(self.case["id"], self.question_set["id"])


if __name__ == "__main__":
    unittest.main()
