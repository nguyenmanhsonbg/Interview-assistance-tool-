import io
import unittest
import zipfile

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

    def test_manual_replacement_creates_new_version_without_overwrite(self):
        service = self.service()
        first = service.import_manual_text(self.case["id"], "JD", "First text")
        second = service.import_manual_text(self.case["id"], "JD", "Second text")

        self.assertEqual(1, first["versionNo"])
        self.assertEqual(2, second["versionNo"])
        versions = service.list_for_case(self.case["id"])
        old = next(item for item in versions if item["id"] == first["id"])
        self.assertFalse(old["isCurrent"])
        self.assertEqual("First text", old["extractedText"])


if __name__ == "__main__":
    unittest.main()
