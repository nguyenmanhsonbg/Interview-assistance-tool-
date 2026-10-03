import unittest

from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


class AnswerAutosaveTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.assessment_service import AssessmentService

        case, question_set, _ = create_approved_case(self)
        self.service = AssessmentService(self.database)
        self.service.prepare(case["id"], question_set["id"])
        self.attempt = self.service.start(
            case["id"], candidate_code_confirmed=True, committee_authorized=True
        )
        self.token = self.attempt["candidateToken"]
        self.question_id = self.service.candidate_view(
            self.attempt["id"], self.token
        )["questions"][0]["id"]

    def test_autosave_revision_persists_and_stale_write_is_rejected(self):
        from app.domain.errors import RevisionConflict

        saved = self.service.save_answer(
            self.attempt["id"], self.question_id, self.token,
            text="First answer", is_answered=True, client_revision=1,
        )
        self.assertEqual(1, saved["saveRevision"])
        refreshed = self.service.candidate_view(self.attempt["id"], self.token)
        self.assertEqual("First answer", refreshed["questions"][0]["answerText"])
        with self.assertRaises(RevisionConflict):
            self.service.save_answer(
                self.attempt["id"], self.question_id, self.token,
                text="Stale overwrite", is_answered=True, client_revision=1,
            )

    def test_blank_answer_is_explicit_and_submitted_answer_is_locked(self):
        from app.domain.errors import StateConflict

        self.service.save_answer(
            self.attempt["id"], self.question_id, self.token,
            text="", is_answered=False, client_revision=1,
        )
        submitted = self.service.submit(self.attempt["id"], self.token, reason="MANUAL")
        self.assertEqual("ASSESSMENT_SUBMITTED", submitted["status"])
        with self.assertRaises(StateConflict):
            self.service.save_answer(
                self.attempt["id"], self.question_id, self.token,
                text="late", is_answered=True, client_revision=2,
            )


if __name__ == "__main__":
    unittest.main()
