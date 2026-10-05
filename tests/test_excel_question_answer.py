import io
import zipfile
import unittest
from xml.etree import ElementTree


def _metadata() -> dict[str, str]:
    return {
        "format_version": "question-answer.v1",
        "case_id": "case-1",
        "question_set_id": "set-1",
        "question_set_version": "2",
        "duration_seconds": "900",
        "exported_at": "2026-10-05T10:00:00Z",
    }


def _question(number: int, *, answer: str = "", answered: bool = False) -> dict:
    return {
        "questionId": f"q-{number}",
        "displayOrder": number,
        "questionText": f"Question {number}\nwith context",
        "competencyKey": "backend",
        "sourceKind": "AI",
        "purpose": "Validate evidence",
        "questionType": "LONG_TEXT",
        "difficulty": "MEDIUM",
        "expectedEvidence": "Context, action, outcome",
        "rubric": {f"score{score}": f"Level {score}" for score in range(5)},
        "isRequired": True,
        "estimatedSeconds": 120,
        "answerText": answer,
        "isAnswered": answered,
    }


def _valid_questions() -> list[dict]:
    return [_question(number) for number in range(1, 6)]


def _replace_entry(raw: bytes, name: str, replacement: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(raw))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, replacement if item.filename == name else source.read(item.filename))
    source.close()
    return output.getvalue()


class ExcelQuestionAnswerTests(unittest.TestCase):
    def test_export_has_exact_sheets_headers_and_round_trips_semantically(self):
        from app.infrastructure.excel_question_answer import (
            QUESTION_HEADERS,
            export_question_answer_workbook,
            import_question_answer_workbook,
        )

        raw = export_question_answer_workbook(_metadata(), _valid_questions())
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            names = [node.attrib["name"] for node in workbook.iter() if node.tag.endswith("}sheet")]
            self.assertEqual(["metadata", "questions"], names)

        parsed = import_question_answer_workbook(raw)
        self.assertEqual(_metadata(), parsed.metadata)
        self.assertEqual(QUESTION_HEADERS, parsed.question_headers)
        self.assertEqual(_valid_questions(), parsed.questions)

    def test_rejects_wrong_version_sheet_shape_and_row_count(self):
        from app.domain.errors import ValidationError
        from app.infrastructure.excel_question_answer import (
            export_question_answer_workbook,
            import_question_answer_workbook,
        )

        wrong_version = _metadata()
        wrong_version["format_version"] = "question-answer.v2"
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(
                export_question_answer_workbook(wrong_version, _valid_questions())
            )
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(
                export_question_answer_workbook(_metadata(), _valid_questions()[:4])
            )

    def test_rejects_formula_cells_and_unsafe_package_entries(self):
        from app.domain.errors import ValidationError
        from app.infrastructure.excel_question_answer import (
            export_question_answer_workbook,
            import_question_answer_workbook,
        )

        raw = export_question_answer_workbook(_metadata(), _valid_questions())
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            sheet = archive.read("xl/worksheets/sheet2.xml")
        formula_sheet = sheet.replace(
            b'<ns0:c r="Q2"',
            b'<ns0:c r="Q2"><ns0:f>1+1</ns0:f></ns0:c><ns0:c r="Q2"',
            1,
        )
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(
                _replace_entry(raw, "xl/worksheets/sheet2.xml", formula_sheet)
            )

        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("xl/workbook.xml", b"<workbook/>")
            archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
            archive.writestr("xl/worksheets/sheet2.xml", b"<worksheet/>")
            archive.writestr("xl/externalLinks/link1.xml", b"external")
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(unsafe.getvalue())

    def test_rejects_duplicate_ids_invalid_enums_and_inconsistent_answer_flag(self):
        from app.domain.errors import ValidationError
        from app.infrastructure.excel_question_answer import (
            export_question_answer_workbook,
            import_question_answer_workbook,
        )

        duplicate = _valid_questions()
        duplicate[1]["questionId"] = duplicate[0]["questionId"]
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(export_question_answer_workbook(_metadata(), duplicate))

        invalid_enum = _valid_questions()
        invalid_enum[0]["questionType"] = "MULTI_CHOICE"
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(export_question_answer_workbook(_metadata(), invalid_enum))

        inconsistent = _valid_questions()
        inconsistent[0]["answerText"] = "answer without flag"
        with self.assertRaises(ValidationError):
            import_question_answer_workbook(export_question_answer_workbook(_metadata(), inconsistent))


if __name__ == "__main__":
    unittest.main()
