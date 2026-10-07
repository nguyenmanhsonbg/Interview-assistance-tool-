import hashlib
import json
import unittest

from app.domain.errors import StateConflict, ValidationError
from app.infrastructure.html_candidate_package import import_candidate_package
from tests.assessment_setup import create_approved_case
from tests.support import MigratedDatabaseFixture


def _safe_json(value: dict) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _response_html(question_package: bytes, *, answer_text: str = "A concrete answer", manifest=None, package_type="RESPONSE") -> bytes:
    package = import_candidate_package(question_package)
    payload = {
        "formatVersion": "candidate-html.v1",
        "packageType": package_type,
        "manifest": manifest or package.manifest,
        "questions": package.questions,
        "answers": [
            {
                "questionId": question["questionId"],
                "answerText": answer_text if question["displayOrder"] == 1 else "",
                "isAnswered": question["displayOrder"] == 1,
            }
            for question in package.questions
        ],
        "clientState": {"startedAt": "2026-10-07T10:00:00Z", "submittedAt": "2026-10-07T10:10:00Z"},
    }
    encoded = _safe_json(payload)
    return (
        '<!doctype html><html><body>'
        '<script id="candidate-package-payload" type="application/json">'
        + encoded
        + "</script></body></html>"
    ).encode("utf-8")


class HtmlCandidatePackageServiceTests(MigratedDatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.case, self.question_set, self.member_id = create_approved_case(self)

    def test_export_creates_candidate_safe_package_and_records_flow(self):
        from app.services.html_candidate_package_service import HtmlCandidatePackageService

        service = HtmlCandidatePackageService(self.database)
        exported = service.export_question_package(self.case["id"])
        package = import_candidate_package(exported.content)

        self.assertEqual("text/html; charset=utf-8", exported.content_type)
        self.assertTrue(exported.filename.endswith(".html"))
        self.assertEqual(exported.package_id, package.manifest["packageId"])
        self.assertEqual("QUESTION", package.package_type)
        self.assertEqual(9, len(package.questions))
        self.assertEqual([], package.answers)
        self.assertNotIn(b"expectedEvidence", exported.content)
        self.assertNotIn(b"rubric", exported.content)
        with self.database.connection() as connection:
            status = connection.execute(
                "SELECT refined_flow_status FROM interview_cases WHERE id=?",
                (self.case["id"],),
            ).fetchone()[0]
            action = connection.execute(
                "SELECT action FROM audit_logs WHERE entity_type='QUESTION_SET' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()[0]
        self.assertEqual("QUESTIONS_EXPORTED", status)
        self.assertEqual("QUESTION_SET_EXPORTED", action)

    def test_import_creates_html_snapshot_with_blank_answers_not_assessed(self):
        from app.services.html_candidate_package_service import HtmlCandidatePackageService

        service = HtmlCandidatePackageService(self.database)
        exported = service.export_question_package(self.case["id"])
        response = _response_html(exported.content)
        snapshot = service.import_response(
            self.case["id"], response, idempotency_key="html-import-1"
        )

        self.assertEqual("HTML_IMPORT", snapshot["sourceKind"])
        self.assertEqual(exported.package_id, snapshot["packageId"])
        self.assertEqual(hashlib.sha256(response).hexdigest(), snapshot["sourceFileSha256"])
        self.assertEqual("ANSWERS_IMPORTED", snapshot["refinedFlowStatus"])
        self.assertEqual("A concrete answer", snapshot["answers"][0]["answerText"])
        self.assertEqual("NOT_ASSESSED", snapshot["answers"][1]["assessmentStatus"])
        original = next(
            question for question in self.question_set["questions"]
            if question["id"] == snapshot["questions"][0]["questionId"]
        )
        self.assertEqual(original["questionText"], snapshot["questions"][0]["questionText"])
        with self.database.connection() as connection:
            actions = [
                row[0]
                for row in connection.execute(
                    "SELECT action FROM audit_logs WHERE entity_type='ASSESSMENT_SNAPSHOT' ORDER BY created_at"
                )
            ]
        self.assertIn("ASSESSMENT_ANSWERS_IMPORTED", actions)

    def test_replay_is_idempotent_and_changed_response_creates_new_version(self):
        from app.services.html_candidate_package_service import HtmlCandidatePackageService

        service = HtmlCandidatePackageService(self.database)
        exported = service.export_question_package(self.case["id"])
        first_response = _response_html(exported.content, answer_text="First")
        first = service.import_response(
            self.case["id"], first_response, idempotency_key="html-import-2"
        )
        replay = service.import_response(
            self.case["id"], first_response, idempotency_key="html-import-2"
        )
        second = service.import_response(
            self.case["id"], _response_html(exported.content, answer_text="Second"),
            idempotency_key="html-import-3",
        )

        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(2, second["versionNo"])
        self.assertNotEqual(first["id"], second["id"])
        with self.assertRaises(StateConflict):
            service.import_response(
                self.case["id"], _response_html(exported.content, answer_text="Second"),
                idempotency_key="html-import-2",
            )

    def test_rejects_wrong_question_set_version_fingerprint_draft_and_malformed_response(self):
        from app.services.html_candidate_package_service import HtmlCandidatePackageService

        service = HtmlCandidatePackageService(self.database)
        exported = service.export_question_package(self.case["id"])
        package = import_candidate_package(exported.content)
        for manifest in (
            {**package.manifest, "questionSetId": "wrong-set"},
            {**package.manifest, "questionSetVersion": 999},
            {**package.manifest, "questionSetFingerprint": "b" * 64},
        ):
            with self.assertRaises(StateConflict):
                service.import_response(
                    self.case["id"], _response_html(exported.content, manifest=manifest),
                    idempotency_key="bad-" + manifest["questionSetId"],
                )
        with self.assertRaises(ValidationError):
            service.import_response(
                self.case["id"], _response_html(exported.content, package_type="DRAFT"),
                idempotency_key="draft",
            )
        with self.assertRaises(ValidationError):
            service.import_response(
                self.case["id"], b"not html package", idempotency_key="malformed"
            )
        self.assertIsNone(service.get_snapshot(self.case["id"]))


if __name__ == "__main__":
    unittest.main()
