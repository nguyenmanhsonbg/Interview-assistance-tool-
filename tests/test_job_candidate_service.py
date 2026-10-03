import sqlite3
import unittest

from tests.support import MigratedDatabaseFixture


class JobCandidateServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def test_create_and_filter_minimum_job_and_candidate_fields(self):
        from app.services.case_service import CaseService

        service = CaseService(self.database)
        job = service.create_job("JOB-1", "Backend Engineer", "Senior")
        candidate = service.create_candidate("CAND-1", "Nguyen Van A")

        self.assertEqual("Backend Engineer", job["positionTitle"])
        self.assertEqual("CAND-1", candidate["candidateCode"])
        self.assertEqual(1, len(service.list_jobs("Backend")))
        self.assertEqual(1, len(service.list_candidates("CAND-1")))

    def test_empty_values_and_duplicate_codes_are_rejected(self):
        from app.domain.errors import ValidationError
        from app.services.case_service import CaseService

        service = CaseService(self.database)
        with self.assertRaises(ValidationError):
            service.create_job("JOB-X", " ", "Senior")
        service.create_candidate("CAND-X", "Candidate")
        with self.assertRaises(sqlite3.IntegrityError):
            service.create_candidate("CAND-X", "Different Candidate")


if __name__ == "__main__":
    unittest.main()
