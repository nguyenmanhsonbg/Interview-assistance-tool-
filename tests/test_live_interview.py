import unittest

from tests.live_setup import create_brief_ready_case
from tests.support import MigratedDatabaseFixture


class LiveInterviewTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, _, self.member_id, _, self.brief = create_brief_ready_case(self)

    def test_start_record_skip_and_complete_preserve_sequence_and_attribution(self):
        from app.services.interview_service import InterviewService

        service = InterviewService(self.database)
        started = service.start(self.case["id"], self.member_id)
        self.assertEqual("LIVE_INTERVIEW_IN_PROGRESS", started["caseStatus"])
        self.assertEqual([1, 2, 3], [record["sequenceNo"] for record in service.list_records(self.case["id"])])

        first = service.record(
            self.case["id"], sequence_no=1, committee_member_id=self.member_id,
            asked_status="ASKED", live_notes="Contradicts the written answer",
            score=2, evidence_status="CONFLICTING",
        )
        service.record(
            self.case["id"], sequence_no=2, committee_member_id=self.member_id,
            asked_status="SKIPPED", live_notes="Time constraint",
            score=None, evidence_status="NOT_ASSESSED",
        )
        service.record(
            self.case["id"], sequence_no=3, committee_member_id=self.member_id,
            asked_status="ASKED", live_notes="Verified example", score=3,
            evidence_status="VERIFIED",
        )
        self.assertEqual(self.member_id, first["committeeMemberId"])
        self.assertEqual("CONFLICTING", first["evidenceStatus"])
        completed = service.complete(self.case["id"], self.member_id, reason="AGENDA_COMPLETE")
        self.assertEqual("LIVE_INTERVIEW_COMPLETED", completed["caseStatus"])

    def test_invalid_score_and_unknown_member_are_rejected(self):
        from app.domain.errors import ValidationError
        from app.services.interview_service import InterviewService

        service = InterviewService(self.database)
        service.start(self.case["id"], self.member_id)
        with self.assertRaises(ValidationError):
            service.record(
                self.case["id"], sequence_no=1, committee_member_id=self.member_id,
                asked_status="ASKED", live_notes="", score=5,
                evidence_status="VERIFIED",
            )
        with self.assertRaises(ValidationError):
            service.record(
                self.case["id"], sequence_no=1, committee_member_id="not-a-member",
                asked_status="ASKED", live_notes="", score=2,
                evidence_status="VERIFIED",
            )

    def test_follow_up_runs_as_persistent_task_without_notes_in_manifest(self):
        from tests.ai_fixtures import follow_up_payload
        from app.services.interview_service import InterviewService

        class Provider:
            def suggest_follow_up(self, payload):
                self.payload = payload
                return follow_up_payload()

        service = InterviewService(self.database)
        service.start(self.case["id"], self.member_id)
        service.record(
            self.case["id"], sequence_no=1, committee_member_id=self.member_id,
            asked_status="ASKED", live_notes="Sensitive live note", score=2,
            evidence_status="UNVERIFIED",
        )
        task = service.request_follow_up(self.case["id"], idempotency_key="follow-up-1")
        self.assertNotIn("Sensitive live note", str(task["inputManifest"]))
        provider = Provider()
        completed = service.process_follow_up(task["id"], provider)
        self.assertEqual("COMPLETED", completed["status"])
        self.assertEqual("Sensitive live note", provider.payload["liveRecords"][0]["liveNotes"])


if __name__ == "__main__":
    unittest.main()
