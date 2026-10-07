import io
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.support import MigratedDatabaseFixture


def make_docx(text="Hello DOCX", *, macro=False, malformed_xml=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        xml = "<broken" if malformed_xml else (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
        )
        archive.writestr("word/document.xml", xml)
        if macro:
            archive.writestr("word/vbaProject.bin", b"macro")
    return stream.getvalue()


class DocumentServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.services.case_service import CaseService

        case_service = CaseService(self.database)
        job = case_service.create_job("JOB-1", "Engineer", "Senior")
        candidate = case_service.create_candidate("CAND-1", "Candidate")
        self.case = case_service.create_case(candidate["id"], job["id"])

    def service(self):
        from app.services.document_service import DocumentService

        return DocumentService(self.database, self.data_root)

    def test_txt_and_docx_are_normalized_stored_and_confirmed(self):
        service = self.service()
        jd = service.import_file(
            self.case["id"], "JD", "..\\unsafe.txt", "text/plain", b"Role\r\nDetails\x00"
        )
        cv = service.import_file(
            self.case["id"],
            "CV",
            "candidate.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            make_docx("Experience"),
        )

        self.assertEqual("Role\nDetails", jd["extractedText"])
        self.assertEqual("Experience", cv["extractedText"])
        self.assertNotIn("unsafe", jd["storagePath"])
        self.assertTrue((self.data_root / jd["storagePath"]).is_file())
        service.confirm(jd["id"], jd["contentSha256"])
        confirmed = service.confirm(cv["id"], cv["contentSha256"])
        self.assertEqual("DOCUMENTS_READY", confirmed["caseStatus"])

    def test_docm_macro_malformed_and_large_input_are_safe_failures(self):
        from app.domain.errors import UnsupportedMediaType, ValidationError

        service = self.service()
        with self.assertRaises(UnsupportedMediaType):
            service.import_file(
                self.case["id"], "CV", "candidate.docm", "application/octet-stream", make_docx(macro=True)
            )
        malformed = service.import_file(
            self.case["id"],
            "CV",
            "candidate.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            make_docx(malformed_xml=True),
        )
        self.assertEqual("FAILED", malformed["extractionStatus"])
        with self.assertRaises(ValidationError):
            service.import_file(
                self.case["id"], "JD", "large.txt", "text/plain", b"x" * (7_500_001)
            )

    def test_pdf_uses_configured_extractor_and_auto_confirms_success(self):
        from app.services.document_service import DocumentService

        extractor = self.data_root / "pdftotext.exe"
        extractor.write_bytes(b"approved test executable placeholder")
        service = DocumentService(
            self.database,
            self.data_root,
            pdf_text_extractor_path=extractor,
        )
        pdf = b"%PDF-1.7\nsynthetic-pdf"
        with patch("app.services.document_service.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Nguyen Van Mạnh\r\nBackend Developer\r\n".encode(), stderr=b""
            )
            document = service.import_file(
                self.case["id"], "CV", "candidate.pdf", "application/pdf", pdf
            )

        self.assertEqual("SUCCEEDED", document["extractionStatus"])
        self.assertEqual("Nguyen Van Mạnh\nBackend Developer", document["extractedText"])
        self.assertTrue(document["isAiEligible"])
        self.assertIsNotNone(document["confirmedAt"])
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(str(extractor), command[0])
        self.assertEqual(["-layout", "-", "-"], command[1:])
        self.assertEqual(pdf, run.call_args.kwargs["input"])
        with self.database.connection() as connection:
            action = connection.execute(
                "SELECT action FROM audit_logs WHERE entity_id=? ORDER BY created_at DESC LIMIT 1",
                (document["id"],),
            ).fetchone()[0]
        self.assertEqual("DOCUMENT_TEXT_AUTO_CONFIRMED", action)

    def test_pdf_without_extractor_keeps_parse_failure_and_is_not_ai_eligible(self):
        document = self.service().import_file(
            self.case["id"], "CV", "candidate.pdf", "application/pdf", b"%PDF-1.7\nscan"
        )

        self.assertEqual("FAILED", document["extractionStatus"])
        self.assertFalse(document["isAiEligible"])
        self.assertIsNone(document["confirmedAt"])

    def test_pdf_header_can_follow_leading_whitespace(self):
        document = self.service().import_file(
            self.case["id"], "CV", "candidate.pdf", "application/pdf", b"\n%PDF-1.7\nscan"
        )

        self.assertEqual("FAILED", document["extractionStatus"])
        self.assertFalse(document["isAiEligible"])

    def test_pdf_extractor_failure_keeps_parse_failure(self):
        from app.services.document_service import DocumentService

        extractor = self.data_root / "pdftotext.exe"
        extractor.write_bytes(b"approved test executable placeholder")
        service = DocumentService(
            self.database,
            self.data_root,
            pdf_text_extractor_path=extractor,
        )
        with patch("app.services.document_service.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout=b"", stderr=b"parse failed"
            )
            document = service.import_file(
                self.case["id"], "CV", "candidate.pdf", "application/pdf", b"%PDF-1.7\nbroken"
            )

        self.assertEqual("FAILED", document["extractionStatus"])
        self.assertFalse(document["isAiEligible"])

    def test_manual_replacement_creates_new_version_without_overwrite(self):
        from app.domain.errors import StateConflict

        service = self.service()
        first = service.import_manual_text(self.case["id"], "JD", "First text")
        second = service.import_manual_text(self.case["id"], "JD", "Second text")

        self.assertEqual(1, first["versionNo"])
        self.assertEqual(2, second["versionNo"])
        versions = service.list_for_case(self.case["id"])
        old = next(item for item in versions if item["id"] == first["id"])
        self.assertFalse(old["isCurrent"])
        self.assertEqual("First text", old["extractedText"])
        with self.assertRaises(StateConflict):
            service.confirm(first["id"], first["contentSha256"])

    def test_document_replacement_is_allowed_before_attempt_starts_and_locked_after(self):
        from app.domain.errors import StateConflict
        from app.services.assessment_service import AssessmentService
        from app.services.question_service import QuestionService
        from tests.test_questions import valid_questions

        service = self.service()
        jd = service.import_manual_text(self.case["id"], "JD", "Role")
        cv = service.import_manual_text(self.case["id"], "CV", "Experience")
        service.confirm(jd["id"], jd["contentSha256"])
        service.confirm(cv["id"], cv["contentSha256"])
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='QUESTIONS_GENERATING' WHERE id=?",
                (self.case["id"],),
            )
        replacement = service.import_manual_text(self.case["id"], "CV", "Replacement")
        service.confirm(replacement["id"], replacement["contentSha256"])
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='DOCUMENTS_READY' WHERE id=?",
                (self.case["id"],),
            )
        question_set = QuestionService(self.database).create_manual_draft(
            self.case["id"], valid_questions()
        )
        with self.database.transaction() as connection:
            member_id = connection.execute(
                "SELECT id FROM interview_case_committee_members WHERE interview_case_id=?",
                (self.case["id"],),
            ).fetchone()
            if member_id is None:
                connection.execute(
                    """INSERT INTO interview_case_committee_members(
                        id, interview_case_id, display_name, role
                    ) VALUES ('lead', ?, 'Lead', 'LEAD')""",
                    (self.case["id"],),
                )
                member_id = ("lead",)
        questions = QuestionService(self.database)
        questions.approve(question_set["id"], member_id[0])
        assessment = AssessmentService(self.database)
        assessment.prepare(self.case["id"], question_set["id"])
        assessment.start(
            self.case["id"], candidate_code_confirmed=True,
            committee_authorized=True,
        )

        with self.assertRaises(StateConflict):
            service.import_manual_text(self.case["id"], "CV", "Too late")


if __name__ == "__main__":
    unittest.main()
