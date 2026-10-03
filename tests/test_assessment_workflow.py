import unittest
from datetime import datetime, timedelta, timezone

from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


class AssessmentWorkflowTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.assessment_service import AssessmentService

        self.case, self.question_set, _ = create_approved_case(self)
        self.service = AssessmentService(self.database)

    def start(self, now=None):
        self.service.prepare(self.case["id"], self.question_set["id"])
        return self.service.start(
            self.case["id"], candidate_code_confirmed=True,
            committee_authorized=True, now=now,
        )

    def test_incomplete_manual_submit_is_idempotent_and_locks_all_answers(self):
        attempt = self.start()
        first = self.service.submit(attempt["id"], attempt["candidateToken"], reason="MANUAL")
        second = self.service.submit(attempt["id"], attempt["candidateToken"], reason="MANUAL")
        self.assertEqual(first["submittedAt"], second["submittedAt"])
        self.assertEqual(0, first["answeredCount"])
        self.assertEqual(5, first["totalCount"])

    def test_expiry_auto_submits_with_server_clock(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        results = self.service.expire_due(start + timedelta(seconds=901))

        self.assertEqual(1, len(results))
        self.assertEqual("TIME_EXPIRED", results[0]["submitReason"])
        self.assertEqual("ASSESSMENT_SUBMITTED", results[0]["status"])

    def test_interruption_resumes_same_attempt_before_expiry_and_never_reopens_terminal(self):
        from app.domain.errors import StateConflict

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        interrupted = self.service.interrupt(attempt["id"])
        resumed = self.service.resume(
            attempt["id"], attempt["candidateToken"], now=start + timedelta(seconds=10)
        )
        self.assertEqual("ASSESSMENT_INTERRUPTED", interrupted["status"])
        self.assertEqual(attempt["id"], resumed["id"])
        self.service.submit(attempt["id"], attempt["candidateToken"], reason="MANUAL")
        with self.assertRaises(StateConflict):
            self.service.resume(
                attempt["id"], attempt["candidateToken"], now=start + timedelta(seconds=20)
            )


if __name__ == "__main__":
    unittest.main()
