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

    def test_case_projection_exposes_active_ai_task_for_ui_recovery(self):
        import uuid

        from app.repositories.ai_tasks import AITaskRepository
        from app.services.case_service import CaseService

        service = CaseService(self.database)
        job_id, candidate_id = self.create_references(service)
        case = service.create_case(candidate_id, job_id)
        task_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            AITaskRepository(self.database).insert(
                connection,
                task_id=task_id,
                case_id=case["id"],
                assessment_attempt_id=None,
                assessment_snapshot_id=None,
                task_type="GENERATE_QUESTIONS",
                idempotency_key="ui-recovery-key",
                input_fingerprint="f" * 64,
                input_manifest={"caseId": case["id"]},
                provider="GEMINI",
                model="gemini-2.5-flash",
                prompt_key="question_generation",
                prompt_version="v1",
                schema_version="v1",
                max_retry=1,
            )

        self.assertEqual(task_id, service.get_case(case["id"])["activeTaskId"])


if __name__ == "__main__":
    unittest.main()
