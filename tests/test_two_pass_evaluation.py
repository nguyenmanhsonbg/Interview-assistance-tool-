import unittest
from pathlib import Path

from app.infrastructure.excel_question_answer import (
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from app.services.excel_assessment_service import ExcelAssessmentService
from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


def evidence_for(payload):
    questions = {item["questionId"]: item for item in payload["questions"]}
    per_answer = []
    for answer in payload["answers"]:
        answered = answer["isAnswered"]
        per_answer.append({
            "answerId": answer["answerId"],
            "questionId": answer["questionId"],
            "score": 3 if answered else None,
            "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
            "reasoning": "Evidence matches the rubric" if answered else "No answer provided",
            "evidenceFound": ["Concrete example"] if answered else [],
            "concerns": [],
            "cvConsistency": "CONSISTENT" if answered else "NOT_ASSESSED",
        })
    return {
        "schemaVersion": "answer-evidence.v1",
        "operation": "ANSWER_EVIDENCE_ANALYSIS",
        "perAnswerEvidence": per_answer,
        "competencyEvidence": [{
            "competencyKey": next(iter(questions.values()))["competencyKey"],
            "evidenceSummary": "Evidence was compared with the approved rubric",
            "evidenceStatus": "PARTIALLY_VERIFIED",
            "confidence": 0.8,
        }],
        "confidence": 0.8,
        "limitations": [],
    }


def synthesis_for(payload):
    evidence = payload["evidenceAnalysis"]
    return {
        "schemaVersion": "answer-evaluation.v2",
        "operation": "ANSWER_EVALUATION",
        "perAnswerEvaluations": [
            {
                "answerId": item["answerId"],
                "questionId": item["questionId"],
                "score": item["score"],
                "evidenceStatus": item["evidenceStatus"],
                "reasoning": item["reasoning"],
                "evidenceFound": item["evidenceFound"],
                "concerns": item["concerns"],
                "cvConsistency": item["cvConsistency"],
            }
            for item in evidence["perAnswerEvidence"]
        ],
        "competencyEvaluations": [
            {
                "competencyKey": item["competencyKey"],
                "summary": item["evidenceSummary"],
                "evidenceStatus": item["evidenceStatus"],
                "confidence": item["confidence"],
            }
            for item in evidence["competencyEvidence"]
        ],
        "strengths": ["Concrete answer evidence"],
        "gaps": [],
        "conflicts": [],
        "risks": [],
        "confidence": evidence["confidence"],
        "limitations": evidence["limitations"],
    }


class RecordingTwoPassProvider:
    def __init__(self, *, invalid_evidence=False, invalid_synthesis=False):
        self.calls = []
        self.invalid_evidence = invalid_evidence
        self.invalid_synthesis = invalid_synthesis

    def analyze_answer_evidence(self, payload):
        self.calls.append(("evidence", payload))
        return {} if self.invalid_evidence else evidence_for(payload)

    def synthesize_answer_evaluation(self, payload):
        self.calls.append(("synthesis", payload))
        return {} if self.invalid_synthesis else synthesis_for(payload)

    def evaluate_answers(self, payload):
        raise AssertionError("snapshot evaluation must not use the legacy provider method")


class TwoPassEvaluationTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, self.question_set, self.member_id = create_approved_case(self)
        excel = ExcelAssessmentService(self.database)
        exported = excel.export_question_set(self.case["id"])
        workbook = import_question_answer_workbook(exported.content)
        workbook.questions[0]["answerText"] = "A concrete answer"
        workbook.questions[0]["isAnswered"] = True
        self.snapshot = excel.import_answers(
            self.case["id"],
            export_question_answer_workbook(workbook.metadata, workbook.questions),
            idempotency_key="two-pass-import",
        )

    def service(self):
        from app.services.evaluation_service import EvaluationService

        return EvaluationService(
            self.database, Path(__file__).resolve().parents[1] / "schemas"
        )

    def test_snapshot_evaluation_runs_two_provider_phases_and_materializes_final(self):
        service = self.service()
        provider = RecordingTwoPassProvider()
        task = service.request_snapshot(
            self.case["id"], self.snapshot["id"], idempotency_key="two-pass-run"
        )

        completed = service.process(task["id"], provider)

        self.assertEqual("COMPLETED", completed["status"])
        self.assertEqual(["evidence", "synthesis"], [name for name, _ in provider.calls])
        self.assertEqual(self.snapshot["id"], provider.calls[1][1]["assessmentSnapshotId"])
        self.assertIn("evidenceAnalysis", provider.calls[1][1])
        result = service.current_ai_result(self.case["id"])
        self.assertEqual("answer-evaluation.v2", result["payload"]["schemaVersion"])
        self.assertEqual("AI_EVALUATED", service.refined_status(self.case["id"]))

    def test_invalid_evidence_stops_before_synthesis_and_creates_no_result(self):
        from app.domain.errors import ResourceNotFound

        service = self.service()
        provider = RecordingTwoPassProvider(invalid_evidence=True)
        task = service.request_snapshot(
            self.case["id"], self.snapshot["id"], idempotency_key="two-pass-invalid-evidence"
        )

        result = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", result["status"])
        self.assertEqual("EVIDENCE_ANALYSIS", result["phase"])
        self.assertEqual(["evidence"], [name for name, _ in provider.calls])
        with self.assertRaises(ResourceNotFound):
            service.current_ai_result(self.case["id"])

    def test_invalid_synthesis_does_not_materialize_result(self):
        from app.domain.errors import ResourceNotFound

        service = self.service()
        provider = RecordingTwoPassProvider(invalid_synthesis=True)
        task = service.request_snapshot(
            self.case["id"], self.snapshot["id"], idempotency_key="two-pass-invalid-synthesis"
        )

        result = service.process(task["id"], provider)

        self.assertEqual("PENDING_RETRY", result["status"])
        self.assertEqual("EVIDENCE_ANALYSIS", result["phase"])
        self.assertEqual(["evidence", "synthesis"], [name for name, _ in provider.calls])
        with self.assertRaises(ResourceNotFound):
            service.current_ai_result(self.case["id"])


if __name__ == "__main__":
    unittest.main()
