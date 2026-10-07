import unittest

from app.domain.errors import StateConflict, ValidationError
from app.infrastructure.excel_question_answer import (
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


class ExcelAssessmentServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, self.question_set, self.member_id = create_approved_case(self)

    def test_export_and_import_create_immutable_snapshot_without_candidate_pii(self):
        from app.services.excel_assessment_service import ExcelAssessmentService

        service = ExcelAssessmentService(self.database)
        exported = service.export_question_set(self.case["id"])
        self.assertEqual(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            exported.content_type,
        )
        self.assertNotIn(b"Candidate", exported.content)

        workbook = import_question_answer_workbook(exported.content)
        workbook.questions[0]["questionText"] = "Edited in Excel"
        workbook.questions[0]["answerText"] = "A concrete example"
        workbook.questions[0]["isAnswered"] = True
        filled = export_question_answer_workbook(workbook.metadata, workbook.questions)

        snapshot = service.import_answers(
            self.case["id"], filled, idempotency_key="excel-import-1"
        )
        self.assertEqual("EXCEL_IMPORT", snapshot["sourceKind"])
        self.assertEqual(snapshot["workbookSha256"], snapshot["sourceFileSha256"])
        self.assertIsNone(snapshot["packageId"])
        self.assertEqual("ANSWERS_IMPORTED", snapshot["refinedFlowStatus"])
        self.assertEqual("Edited in Excel", snapshot["questions"][0]["questionText"])
        self.assertEqual("NOT_ASSESSED", snapshot["answers"][1]["assessmentStatus"])

        original = next(
            question
            for question in self.question_set["questions"]
            if question["id"] == snapshot["questions"][0]["questionId"]
        )
        self.assertNotEqual("Edited in Excel", original["questionText"])

    def test_same_import_is_idempotent_and_changed_workbook_creates_new_version(self):
        from app.services.excel_assessment_service import ExcelAssessmentService

        service = ExcelAssessmentService(self.database)
        exported = service.export_question_set(self.case["id"])
        first = service.import_answers(
            self.case["id"], exported.content, idempotency_key="excel-import-2"
        )
        replay = service.import_answers(
            self.case["id"], exported.content, idempotency_key="excel-import-2"
        )
        self.assertEqual(first["id"], replay["id"])

        workbook = import_question_answer_workbook(exported.content)
        workbook.questions[0]["answerText"] = "Changed workbook"
        workbook.questions[0]["isAnswered"] = True
        changed = export_question_answer_workbook(workbook.metadata, workbook.questions)
        second = service.import_answers(
            self.case["id"], changed, idempotency_key="excel-import-3"
        )
        self.assertEqual(2, second["versionNo"])
        self.assertNotEqual(first["id"], second["id"])

        with self.assertRaises(StateConflict):
            service.import_answers(
                self.case["id"], changed, idempotency_key="excel-import-2"
            )

    def test_import_rejects_wrong_case_set_version_and_question_owner(self):
        from app.services.excel_assessment_service import ExcelAssessmentService

        service = ExcelAssessmentService(self.database)
        exported = service.export_question_set(self.case["id"])
        workbook = import_question_answer_workbook(exported.content)

        wrong_case = dict(workbook.metadata)
        wrong_case["case_id"] = "another-case"
        with self.assertRaises(StateConflict):
            service.import_answers(
                self.case["id"],
                export_question_answer_workbook(wrong_case, workbook.questions),
                idempotency_key="wrong-case",
            )

        wrong_set = dict(workbook.metadata)
        wrong_set["question_set_id"] = "another-set"
        with self.assertRaises(StateConflict):
            service.import_answers(
                self.case["id"],
                export_question_answer_workbook(wrong_set, workbook.questions),
                idempotency_key="wrong-set",
            )

        foreign_question = list(workbook.questions)
        foreign_question[0] = dict(foreign_question[0])
        foreign_question[0]["questionId"] = "foreign-question"
        with self.assertRaises(ValidationError):
            service.import_answers(
                self.case["id"],
                export_question_answer_workbook(workbook.metadata, foreign_question),
                idempotency_key="foreign-question",
            )


if __name__ == "__main__":
    unittest.main()
