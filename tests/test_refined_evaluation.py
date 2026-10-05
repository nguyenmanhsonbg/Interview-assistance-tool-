import json
from pathlib import Path
import unittest

from app.infrastructure.excel_question_answer import (
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from app.services.excel_assessment_service import ExcelAssessmentService
from tests.ai_fixtures import answer_evaluation_v2_payload
from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


class RefinedEvaluationProvider:
    def evaluate_answers(self, payload):
        self.payload = payload
        return answer_evaluation_v2_payload()


class RefinedEvaluationTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, self.question_set, self.member_id = create_approved_case(self)
        excel = ExcelAssessmentService(self.database)
        exported = excel.export_question_set(self.case["id"])
        workbook = import_question_answer_workbook(exported.content)
        workbook.questions[0]["answerText"] = "A private example with evidence"
        workbook.questions[0]["isAnswered"] = True
        self.snapshot = excel.import_answers(
            self.case["id"],
            export_question_answer_workbook(workbook.metadata, workbook.questions),
            idempotency_key="refined-evaluation-import",
        )

    def test_snapshot_evaluation_manifest_and_provider_payload_are_sanitized(self):
        from app.services.evaluation_service import EvaluationService

        service = EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )
        task = service.request_snapshot(
            self.case["id"], self.snapshot["id"], idempotency_key="refined-evaluation-1"
        )
        serialized = json.dumps(task["inputManifest"])
        self.assertNotIn("A private example", serialized)
        self.assertNotIn("answerText", serialized)
        self.assertEqual(self.snapshot["id"], task["assessmentSnapshotId"])
        self.assertEqual("AI_ANALYZING", service.refined_status(self.case["id"]))

        provider = RefinedEvaluationProvider()
        completed = service.process(task["id"], provider)
        self.assertEqual("COMPLETED", completed["status"])
        self.assertNotIn("Candidate", json.dumps(provider.payload))
        self.assertIn(
            "A private example with evidence",
            [answer["answerText"] for answer in provider.payload["answers"]],
        )
        self.assertNotIn("interviewBrief", provider.payload)
        self.assertNotIn("recommendedLiveQuestions", provider.payload)
        self.assertEqual("AI_EVALUATED", service.refined_status(self.case["id"]))

    def test_v2_result_is_versioned_on_force_rerun(self):
        from app.services.evaluation_service import EvaluationService

        service = EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )
        first = service.request_snapshot(
            self.case["id"], self.snapshot["id"], idempotency_key="refined-evaluation-2"
        )
        service.process(first["id"], RefinedEvaluationProvider())
        second = service.request_snapshot(
            self.case["id"], self.snapshot["id"],
            idempotency_key="refined-evaluation-3", force_rerun=True,
        )
        service.process(second["id"], RefinedEvaluationProvider())
        result = service.current_ai_result(self.case["id"])
        self.assertEqual("answer-evaluation.v2", result["payload"]["schemaVersion"])
        self.assertEqual(2, result["versionNo"])


if __name__ == "__main__":
    unittest.main()
