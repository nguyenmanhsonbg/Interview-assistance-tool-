import unittest

from tests.support import MigratedDatabaseFixture


def valid_questions(count=5):
    return [
        {
            "displayOrder": index,
            "questionText": f"Question {index}",
            "competencyKey": "backend",
            "sourceKind": "MANUAL",
            "purpose": "Assess backend reasoning",
            "questionType": "SCENARIO",
            "difficulty": "MEDIUM",
            "expectedEvidence": "Specific decisions and evidence",
            "rubric": {f"score{score}": f"Level {score}" for score in range(5)},
            "isRequired": True,
        }
        for index in range(1, count + 1)
    ]


class QuestionServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("J", "Engineer", "Senior")
        candidate = cases.create_candidate("C", "Candidate")
        self.case = cases.create_case(
            candidate["id"], job["id"],
            committee_members=[{"displayName": "Lead", "role": "LEAD"}],
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='DOCUMENTS_READY' WHERE id=?",
                (self.case["id"],),
            )

    def test_create_edit_and_approve_question_set_then_lock_it(self):
        from app.domain.errors import StateConflict
        from app.services.question_service import QuestionService

        service = QuestionService(self.database)
        question_set = service.create_manual_draft(
            self.case["id"], valid_questions(5), duration_seconds=900
        )
        edited = valid_questions(5)
        edited[0]["questionText"] = "Edited question"
        service.update_draft(question_set["id"], edited)
        member_id = self._lead_id()
        approved = service.approve(question_set["id"], member_id)

        self.assertEqual("APPROVED", approved["status"])
        self.assertEqual("Edited question", approved["questions"][0]["questionText"])
        with self.assertRaises(StateConflict):
            service.update_draft(question_set["id"], valid_questions(5))
        with self.database.connection() as connection:
            action = connection.execute(
                "SELECT action FROM audit_logs WHERE entity_id=? ORDER BY created_at DESC LIMIT 1",
                (question_set["id"],),
            ).fetchone()[0]
        self.assertEqual("QUESTION_SET_APPROVED", action)

    def test_question_count_duration_and_required_fields_are_validated(self):
        from app.domain.errors import ValidationError
        from app.services.question_service import QuestionService

        service = QuestionService(self.database)
        for count in (4, 9):
            with self.assertRaises(ValidationError):
                service.create_manual_draft(self.case["id"], valid_questions(count))
        with self.assertRaises(ValidationError):
            service.create_manual_draft(
                self.case["id"], valid_questions(5), duration_seconds=599
            )
        invalid = valid_questions(5)
        invalid[0]["expectedEvidence"] = ""
        with self.assertRaises(ValidationError):
            service.create_manual_draft(self.case["id"], invalid)

    def _lead_id(self):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT id FROM interview_case_committee_members WHERE interview_case_id=? AND role='LEAD'",
                (self.case["id"],),
            ).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
