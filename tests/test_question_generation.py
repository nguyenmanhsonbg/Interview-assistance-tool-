import unittest

from tests.support import MigratedDatabaseFixture


def ai_payload(count=5):
    return {
        "schemaVersion": "question-generation.v1",
        "operation": "QUESTION_GENERATION",
        "competencyMatrix": [
            {
                "key": "backend", "name": "Backend", "required": True,
                "priority": "REQUIRED", "jdEvidence": "API design",
                "cvEvidence": "Built APIs", "gap": "", "conflict": "",
            }
        ],
        "questions": [
            {
                "provisionalId": f"q-{index}", "displayOrder": index,
                "text": f"AI Question {index}", "competencyKey": "backend",
                "sourceKind": "AI", "purpose": "Assess reasoning",
                "questionType": "SCENARIO", "difficulty": "MEDIUM",
                "expectedEvidence": "Concrete example",
                "rubric": {f"score{score}": f"Level {score}" for score in range(5)},
                "isRequired": True, "estimatedSeconds": 120,
            }
            for index in range(1, count + 1)
        ],
        "gaps": [], "conflicts": [], "estimatedDurationSeconds": 900,
        "confidence": 0.8, "limitations": [],
    }


class QuestionGenerationTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        cases = CaseService(self.database)
        job = cases.create_job("J", "Engineer", "Senior")
        candidate = cases.create_candidate("C", "Candidate")
        self.case = cases.create_case(candidate["id"], job["id"])
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='QUESTIONS_GENERATING' WHERE id=?",
                (self.case["id"],),
            )

    def test_valid_ai_output_materializes_generated_draft_not_approved(self):
        from app.services.question_service import QuestionService

        result = QuestionService(self.database).materialize_generated(
            self.case["id"], ai_payload(5)
        )

        self.assertEqual("GENERATED", result["status"])
        self.assertEqual(5, len(result["questions"]))
        with self.database.connection() as connection:
            case_status = connection.execute(
                "SELECT status FROM interview_cases WHERE id=?", (self.case["id"],)
            ).fetchone()[0]
        self.assertEqual("QUESTIONS_GENERATED", case_status)

    def test_invalid_ai_output_does_not_create_question_set(self):
        from app.domain.errors import ValidationError
        from app.services.question_service import QuestionService

        invalid = ai_payload(4)
        with self.assertRaises(ValidationError):
            QuestionService(self.database).materialize_generated(self.case["id"], invalid)
        with self.database.connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0]
        self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main()
