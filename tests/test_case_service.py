import sqlite3
import unittest

from tests.support import MigratedDatabaseFixture


class InterviewCaseServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def create_references(self, service):
        job = service.create_job("JOB-1", "Backend Engineer", "Senior")
        candidate = service.create_candidate("CAND-1", "Candidate A")
        return job["id"], candidate["id"]

    def test_case_defaults_committee_and_audit_are_created_atomically(self):
        from app.services.case_service import CaseService

        service = CaseService(self.database)
        job_id, candidate_id = self.create_references(service)
        case = service.create_case(
            candidate_id,
            job_id,
            committee_members=[
                {"displayName": "Lead", "role": "LEAD"},
                {"displayName": "Member", "role": "MEMBER"},
            ],
        )

        self.assertEqual("DRAFT", case["status"])
        self.assertEqual(900, case["assessmentDurationSeconds"])
        self.assertTrue(case["allowIncompleteSubmit"])
        self.assertEqual(2, len(case["committeeMembers"]))
        with self.database.connection() as connection:
            action = connection.execute(
                "SELECT action FROM audit_logs WHERE entity_id = ?", (case["id"],)
            ).fetchone()[0]
        self.assertEqual("CASE_CREATED", action)

    def test_two_leads_are_rejected_and_cancel_is_allowed_only_before_attempt(self):
        from app.domain.errors import StateConflict
        from app.services.case_service import CaseService

        service = CaseService(self.database)
        job_id, candidate_id = self.create_references(service)
        with self.assertRaises(sqlite3.IntegrityError):
            service.create_case(
                candidate_id,
                job_id,
                committee_members=[
                    {"displayName": "Lead 1", "role": "LEAD"},
                    {"displayName": "Lead 2", "role": "LEAD"},
                ],
            )

        case = service.create_case(candidate_id, job_id)
        cancelled = service.cancel_case(case["id"], "Candidate withdrew")
        self.assertEqual("CANCELLED", cancelled["status"])
        with self.assertRaises(StateConflict):
            service.cancel_case(case["id"], "again")


if __name__ == "__main__":
    unittest.main()
