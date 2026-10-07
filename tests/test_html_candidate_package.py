import json
import unittest

from app.domain.errors import ValidationError


def _manifest() -> dict:
    return {
        "formatVersion": "candidate-html.v1",
        "packageId": "package-1",
        "questionSetId": "set-1",
        "questionSetVersion": 2,
        "questionSetFingerprint": "a" * 64,
        "durationSeconds": 900,
        "questionCount": 2,
        "exportedAt": "2026-10-07T10:00:00Z",
    }


def _questions() -> list[dict]:
    return [
        {
            "questionId": "q-1",
            "displayOrder": 1,
            "questionText": "Explain <script>alert('x')</script> safely.",
            "questionType": "LONG_TEXT",
            "isRequired": True,
            "competencyKey": "hidden",
            "rubric": {"score0": "hidden"},
            "expectedEvidence": "hidden",
        },
        {
            "questionId": "q-2",
            "displayOrder": 2,
            "questionText": "Describe one concrete outcome.",
            "questionType": "SCENARIO",
            "isRequired": False,
        },
    ]


def _package_html(package_type: str, answers: list[dict], *, manifest=None) -> bytes:
    payload = {
        "formatVersion": "candidate-html.v1",
        "packageType": package_type,
        "manifest": manifest or _manifest(),
        "questions": [
            {
                "questionId": item["questionId"],
                "displayOrder": item["displayOrder"],
                "questionText": item["questionText"],
                "questionType": item["questionType"],
                "isRequired": item["isRequired"],
            }
            for item in _questions()
        ],
        "answers": answers,
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        '<!doctype html><html><body>'
        '<script id="candidate-package-payload" type="application/json">'
        + encoded
        + "</script></body></html>"
    ).encode("utf-8")


class HtmlCandidatePackageTests(unittest.TestCase):
    def test_question_export_round_trips_candidate_safe_self_contained_html(self):
        from app.infrastructure.html_candidate_package import (
            HTML_CONTENT_TYPE,
            export_question_package,
            import_candidate_package,
        )

        raw = export_question_package(_manifest(), _questions())
        parsed = import_candidate_package(raw)

        self.assertEqual("QUESTION", parsed.package_type)
        self.assertEqual(_manifest(), parsed.manifest)
        self.assertEqual(2, len(parsed.questions))
        self.assertEqual([], parsed.answers)
        self.assertEqual(64, len(parsed.package_sha256))
        self.assertEqual("text/html; charset=utf-8", HTML_CONTENT_TYPE)
        self.assertNotIn(b"competencyKey", raw)
        self.assertNotIn(b"rubric", raw)
        self.assertNotIn(b"expectedEvidence", raw)
        self.assertNotIn(b"JD", raw)
        self.assertNotIn(b"CV", raw)
        self.assertNotIn(b"http://", raw)
        self.assertNotIn(b"https://", raw)
        self.assertNotIn(b"import(", raw)
        self.assertIn(b"textContent", raw)
        self.assertIn(b"Blob", raw)
        self.assertIn(b"URL.createObjectURL", raw)

    def test_question_text_is_safe_inside_payload_and_visible_dom_text(self):
        from app.infrastructure.html_candidate_package import (
            export_question_package,
            import_candidate_package,
        )

        raw = export_question_package(_manifest(), _questions())
        self.assertNotIn(b"<script>alert('x')</script>", raw)
        parsed = import_candidate_package(raw)
        self.assertEqual(_questions()[0]["questionText"], parsed.questions[0]["questionText"])

    def test_draft_and_response_payloads_restore_and_normalize_answers(self):
        from app.infrastructure.html_candidate_package import import_candidate_package

        draft = import_candidate_package(_package_html(
            "DRAFT",
            [
                {"questionId": "q-1", "answerText": "Answer", "isAnswered": True},
                {"questionId": "q-2", "answerText": "", "isAnswered": False},
            ],
        ))
        response = import_candidate_package(_package_html(
            "RESPONSE",
            [
                {"questionId": "q-1", "answerText": "Answer", "isAnswered": True},
                {"questionId": "q-2", "answerText": "", "isAnswered": False},
            ],
        ))

        self.assertEqual("DRAFT", draft.package_type)
        self.assertEqual("RESPONSE", response.package_type)
        self.assertEqual("Answer", response.answers[0]["answerText"])
        self.assertEqual("NOT_ASSESSED", response.answers[1]["assessmentStatus"])

    def test_rejects_missing_marker_wrong_version_duplicate_and_unknown_answer(self):
        from app.infrastructure.html_candidate_package import import_candidate_package

        cases = [
            b"<html></html>",
            _package_html("QUESTION", [], manifest={**_manifest(), "formatVersion": "wrong"}),
            _package_html("RESPONSE", [
                {"questionId": "q-1", "answerText": "one", "isAnswered": True},
                {"questionId": "q-1", "answerText": "two", "isAnswered": True},
            ]),
            _package_html("RESPONSE", [
                {"questionId": "unknown", "answerText": "one", "isAnswered": True},
                {"questionId": "q-2", "answerText": "", "isAnswered": False},
            ]),
        ]
        for raw in cases:
            with self.assertRaises(ValidationError):
                import_candidate_package(raw)

    def test_rejects_inconsistent_answer_flag_unsupported_type_and_oversized_input(self):
        from app.infrastructure.html_candidate_package import (
            MAX_HTML_PACKAGE_BYTES,
            import_candidate_package,
        )

        inconsistent = _package_html("RESPONSE", [
            {"questionId": "q-1", "answerText": "", "isAnswered": True},
            {"questionId": "q-2", "answerText": "", "isAnswered": False},
        ])
        unsupported = _package_html("UNKNOWN", [])
        for raw in (inconsistent, unsupported, b"x" * (MAX_HTML_PACKAGE_BYTES + 1)):
            with self.assertRaises(ValidationError):
                import_candidate_package(raw)


if __name__ == "__main__":
    unittest.main()
