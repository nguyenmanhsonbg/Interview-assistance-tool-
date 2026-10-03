import unittest
from pathlib import Path

from tests.live_setup import create_brief_ready_case
from tests.support import MigratedDatabaseFixture


def draft_payload(result="PASS"):
    return {
        "finalResult": result, "finalLevel": "Senior", "summary": "Committee decision",
        "strengths": ["Reasoning"], "gaps": ["Operations"], "risks": [],
        "finalComment": "Reviewed against evidence",
    }


class FinalEvaluationTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, _, self.lead_id, _, _ = create_brief_ready_case(self)
        from app.services.interview_service import InterviewService

        live = InterviewService(self.database)
        live.start(self.case["id"], self.lead_id)
        for sequence in range(1, 4):
            live.record(
                self.case["id"], sequence_no=sequence,
                committee_member_id=self.lead_id, asked_status="ASKED",
                live_notes=f"Evidence {sequence}", score=3,
                evidence_status="VERIFIED",
            )
        live.complete(self.case["id"], self.lead_id, reason="AGENDA_COMPLETE")

    def service(self):
        from app.services.evaluation_service import EvaluationService

        return EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )

    def test_only_lead_can_finalize_and_case_changes_after_final(self):
        from app.domain.errors import ForbiddenCapability

        service = self.service()
        draft = service.save_final_draft(self.case["id"], draft_payload())
        with self.database.transaction() as connection:
            member_id = "member-2"
            connection.execute(
                """INSERT INTO interview_case_committee_members(
                    id, interview_case_id, display_name, role, display_order
                ) VALUES (?, ?, 'Member', 'MEMBER', 2)""",
                (member_id, self.case["id"]),
            )
        with self.assertRaises(ForbiddenCapability):
            service.finalize(draft["id"], member_id, confirmation="FINALIZE_EVALUATION")
        final = service.finalize(
            draft["id"], self.lead_id, confirmation="FINALIZE_EVALUATION"
        )
        self.assertEqual("FINAL", final["status"])
        self.assertIsNotNone(final["decidedAt"])
        self.assertEqual("EVALUATED", service.case_status(self.case["id"]))

    def test_revision_preserves_final_version_and_requires_reason(self):
        from app.domain.errors import ValidationError

        service = self.service()
        first = service.save_final_draft(self.case["id"], draft_payload())
        first = service.finalize(
            first["id"], self.lead_id, confirmation="FINALIZE_EVALUATION"
        )
        with self.assertRaises(ValidationError):
            service.save_final_draft(self.case["id"], draft_payload("NEXT_ROUND"))
        revision = service.save_final_draft(
            self.case["id"], draft_payload("NEXT_ROUND"),
            revision_reason="New verified evidence",
        )
        self.assertEqual(2, revision["versionNo"])
        self.assertEqual(first["id"], revision["supersedesEvaluationId"])
        with self.database.connection() as connection:
            old = connection.execute(
                "SELECT status, final_result, is_current FROM evaluations WHERE id=?",
                (first["id"],),
            ).fetchone()
        self.assertEqual(("FINAL", "PASS", 0), tuple(old))


if __name__ == "__main__":
    unittest.main()
