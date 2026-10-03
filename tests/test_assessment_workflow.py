import unittest
import threading
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
        from app.domain.errors import Unauthenticated

        attempt = self.start()
        first = self.service.submit(
            attempt["id"], attempt["candidateToken"], reason="MANUAL",
            idempotency_key="submit-once",
        )
        second = self.service.submit(
            attempt["id"], attempt["candidateToken"], reason="MANUAL",
            idempotency_key="submit-once",
        )
        self.assertEqual(first["submittedAt"], second["submittedAt"])
        self.assertEqual(0, first["answeredCount"])
        self.assertEqual(5, first["totalCount"])
        with self.assertRaises(Unauthenticated):
            self.service.candidate_view(attempt["id"], attempt["candidateToken"])
        with self.assertRaises(Unauthenticated):
            self.service.submit(
                attempt["id"], attempt["candidateToken"], reason="MANUAL",
                idempotency_key="different-request",
            )
        with self.assertRaises(Unauthenticated):
            self.service.submit(
                attempt["id"], "wrong-token", reason="MANUAL",
                idempotency_key="submit-once",
            )

    def test_concurrent_submit_replay_is_serialized_and_token_bound(self):
        attempt = self.start()
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def submit():
            barrier.wait()
            try:
                results.append(self.service.submit(
                    attempt["id"], attempt["candidateToken"],
                    idempotency_key="concurrent-submit",
                ))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(3)

        self.assertFalse(errors)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0]["submittedAt"], results[1]["submittedAt"])

    def test_expiry_auto_submits_with_server_clock(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        results = self.service.expire_due(start + timedelta(seconds=901))

        self.assertEqual(1, len(results))
        self.assertEqual("TIME_EXPIRED", results[0]["submitReason"])
        self.assertEqual("ASSESSMENT_SUBMITTED", results[0]["status"])

    def test_interrupted_attempt_expires_and_invalidates_candidate_token(self):
        from app.domain.errors import Unauthenticated

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        self.service.interrupt(attempt["id"])

        results = self.service.expire_due(start + timedelta(seconds=901))

        self.assertEqual(1, len(results))
        self.assertEqual("ASSESSMENT_EXPIRED", results[0]["status"])
        with self.assertRaises(Unauthenticated):
            self.service.candidate_view(attempt["id"], attempt["candidateToken"])

    def test_expiry_policy_can_lock_instead_of_auto_submit(self):
        from app.domain.errors import Unauthenticated

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET auto_submit_on_expiry=0 WHERE id=?",
                (self.case["id"],),
            )

        results = self.service.expire_due(start + timedelta(seconds=901))

        self.assertEqual("ASSESSMENT_EXPIRED", results[0]["status"])
        with self.assertRaises(Unauthenticated):
            self.service.candidate_view(attempt["id"], attempt["candidateToken"])

    def test_candidate_request_after_expiry_auto_submits_before_any_write(self):
        from app.domain.errors import Unauthenticated

        start = datetime.now(timezone.utc) - timedelta(seconds=901)
        attempt = self.start(now=start)
        with self.assertRaises(Unauthenticated):
            self.service.candidate_view(attempt["id"], attempt["candidateToken"])

        submitted = self.service.get_for_case(self.case["id"])
        self.assertEqual("ASSESSMENT_SUBMITTED", submitted["status"])
        self.assertEqual("TIME_EXPIRED", submitted["submitReason"])
        self.assertEqual(0, submitted["answeredCount"])

    def test_expiry_is_rechecked_inside_autosave_transaction(self):
        from app.domain.errors import Unauthenticated
        from app.services.assessment_service import AssessmentService

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        question_id = self.service.candidate_view(
            attempt["id"], attempt["candidateToken"], now=start
        )["questions"][0]["id"]
        moments = iter([
            start + timedelta(seconds=899),
            start + timedelta(seconds=901),
        ])
        service = AssessmentService(self.database, clock=lambda: next(moments))

        with self.assertRaises(Unauthenticated):
            service.save_answer(
                attempt["id"], question_id, attempt["candidateToken"],
                text="must not commit", is_answered=True, client_revision=1,
            )

        current = service.get_for_case(self.case["id"])
        self.assertEqual("ASSESSMENT_SUBMITTED", current["status"])
        self.assertEqual(0, current["answeredCount"])

    def test_submit_checks_server_expiry_inside_its_transaction(self):
        from app.domain.errors import Unauthenticated
        from app.services.assessment_service import AssessmentService

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = self.start(now=start)
        service = AssessmentService(
            self.database,
            clock=lambda: start + timedelta(seconds=901),
        )

        with self.assertRaises(Unauthenticated):
            service.submit(
                attempt["id"], attempt["candidateToken"],
                idempotency_key="expired-submit",
            )

        current = service.get_for_case(self.case["id"])
        self.assertEqual("ASSESSMENT_SUBMITTED", current["status"])
        self.assertEqual("TIME_EXPIRED", current["submitReason"])

    def test_manual_submit_rejects_stale_final_answer_revisions(self):
        from app.domain.errors import RevisionConflict

        attempt = self.start()
        questions = self.service.candidate_view(
            attempt["id"], attempt["candidateToken"]
        )["questions"]
        first = questions[0]
        self.service.save_answer(
            attempt["id"], first["id"], attempt["candidateToken"],
            text="saved", is_answered=True, client_revision=1,
        )
        stale = {question["id"]: 0 for question in questions}
        with self.assertRaises(RevisionConflict):
            self.service.submit(
                attempt["id"], attempt["candidateToken"],
                expected_revisions=stale,
                idempotency_key="stale-submit",
            )
        current = self.service.get_for_case(self.case["id"])
        self.assertEqual("ASSESSMENT_IN_PROGRESS", current["status"])

        revisions = {question["id"]: 0 for question in questions}
        revisions[first["id"]] = 1
        submitted = self.service.submit(
            attempt["id"], attempt["candidateToken"],
            expected_revisions=revisions,
            idempotency_key="final-submit",
        )
        self.assertEqual("ASSESSMENT_SUBMITTED", submitted["status"])

    def test_interruption_resumes_same_attempt_before_expiry_and_never_reopens_terminal(self):
        from app.domain.errors import Unauthenticated

        start = datetime.now(timezone.utc)
        attempt = self.start(now=start)
        interrupted = self.service.interrupt(attempt["id"])
        resumed = self.service.resume(
            attempt["id"], attempt["candidateToken"], now=start + timedelta(seconds=10)
        )
        self.assertEqual("ASSESSMENT_INTERRUPTED", interrupted["status"])
        self.assertEqual(attempt["id"], resumed["id"])
        self.service.submit(
            attempt["id"], attempt["candidateToken"], reason="MANUAL",
            idempotency_key="terminal-submit",
        )
        with self.assertRaises(Unauthenticated):
            self.service.resume(
                attempt["id"], attempt["candidateToken"], now=start + timedelta(seconds=20)
            )


if __name__ == "__main__":
    unittest.main()
