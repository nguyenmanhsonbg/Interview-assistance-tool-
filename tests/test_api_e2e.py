import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.infrastructure.excel_question_answer import (
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from app.infrastructure.html_candidate_package import import_candidate_package
from tests.ai_fixtures import (
    answer_evaluation_v2_payload,
    question_addition_payload,
    question_generation_payload,
    question_variant_payload,
)
from tests.test_questions import valid_questions


def response_html(question_package):
    package = import_candidate_package(question_package)
    payload = {
        "formatVersion": "candidate-html.v1",
        "packageType": "RESPONSE",
        "manifest": package.manifest,
        "questions": package.questions,
        "answers": [
            {
                "questionId": question["questionId"],
                "answerText": "A concrete answer from HTML" if question["displayOrder"] == 1 else "",
                "isAnswered": question["displayOrder"] == 1,
            }
            for question in package.questions
        ],
        "clientState": {"startedAt": "2026-10-07T10:00:00Z", "submittedAt": "2026-10-07T10:10:00Z"},
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        "<!doctype html><html><body>"
        '<script id="candidate-package-payload" type="application/json">'
        + encoded
        + "</script></body></html>"
    ).encode("utf-8")


class FakePilotProvider:
    def __init__(self):
        self.block_evidence = False
        self.evidence_started = threading.Event()
        self.release_evidence = threading.Event()
        self.variant_invalid = False
        self.variant_failure = False

    def generate_questions(self, payload):
        return question_generation_payload()

    def generate_question_variant(self, payload):
        if self.variant_failure:
            raise RuntimeError("deterministic variant provider failure")
        result = question_variant_payload()
        if self.variant_invalid:
            result.pop("variant")
        result["questionSetId"] = payload["questionSetId"]
        result["sourceQuestionId"] = payload["sourceQuestionId"]
        result["mode"] = payload["mode"]
        return result

    def generate_question_addition(self, payload):
        result = question_addition_payload(payload["targetCategory"])
        result["questionSetId"] = payload["questionSetId"]
        result["mode"] = payload["mode"]
        result["targetCategory"] = payload["targetCategory"]
        return result

    def evaluate_answers(self, payload):
        return answer_evaluation_v2_payload(answered=True)

    def analyze_answer_evidence(self, payload):
        from tests.test_two_pass_evaluation import evidence_for

        self.evidence_started.set()
        if self.block_evidence:
            self.release_evidence.wait(2)
        return evidence_for(payload)

    def synthesize_answer_evaluation(self, payload):
        from tests.test_two_pass_evaluation import synthesis_for

        return synthesis_for(payload)

    def suggest_follow_up(self, payload):
        return {"schemaVersion": "follow-up.v1", "operation": "FOLLOW_UP", "questions": [], "stopCondition": "none", "confidence": 0.5, "limitations": []}


class PilotE2ETests(unittest.TestCase):
    def setUp(self):
        from app.application import create_application
        from app.config import AppConfig
        from app.server import create_server

        self.temp = tempfile.TemporaryDirectory()
        config = AppConfig(
            port=0, data_directory=Path(self.temp.name),
            web_directory=Path(__file__).resolve().parents[1] / "web",
        )
        self.provider = FakePilotProvider()
        self.application = create_application(
            config, provider=self.provider, initial_pin="246810"
        )
        self.server = create_server(
            config, router=self.application.router, security=self.application.security
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.application.start()
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        bootstrap = self.call("GET", "/api/v1/bootstrap")
        self.startup = bootstrap["startupToken"]
        auth = self.call(
            "POST", "/api/v1/auth/committee-session", {"pin": "246810"},
            headers={"X-Startup-Token": self.startup},
        )
        self.session = auth["committeeSession"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.application.stop(); self.temp.cleanup()

    def call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = dict(headers or {})
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, method=method, data=data, headers=request_headers
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read()) if response.status != 204 else None
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{method} {path} -> {error.code}: {error.read()!r}") from error
        return None if payload is None else payload["data"]

    def call_binary(self, method, path, body=None, headers=None):
        request = urllib.request.Request(
            self.base + path, method=method, data=body, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{method} {path} -> {error.code}: {error.read()!r}") from error

    def committee_headers(self, mutation=True):
        headers = {"X-Committee-Session": self.session}
        if mutation:
            headers["X-Startup-Token"] = self.startup
        return headers

    def error_status(self, method, path, body=None, headers=None):
        data = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode("utf-8")
        request_headers = dict(headers or {})
        if data is not None and not isinstance(body, bytes):
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, method=method, data=data, headers=request_headers
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        return caught.exception.code

    def wait_task(self, task_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.call(
                "GET", f"/api/v1/tasks/{task_id}", headers=self.committee_headers(False)
            )
            if result["task"]["status"] in {"COMPLETED", "FAILED"}:
                self.assertEqual("COMPLETED", result["task"]["status"], result)
                return result
            time.sleep(0.02)
        self.fail("AI task did not complete")

    def wait_task_terminal(self, task_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.call(
                "GET", f"/api/v1/tasks/{task_id}", headers=self.committee_headers(False)
            )
            if result["task"]["status"] in {"COMPLETED", "FAILED"}:
                return result
            time.sleep(0.02)
        self.fail("AI task did not reach a terminal status")

    def create_manual_case(self, job_code, candidate_code):
        headers = self.committee_headers()
        job = self.call("POST", "/api/v1/jobs", {
            "jobCode": job_code, "positionTitle": "Backend Engineer", "targetLevel": "Senior",
        }, headers=headers)["job"]
        candidate = self.call("POST", "/api/v1/candidates", {
            "candidateCode": candidate_code, "fullName": "Variant Candidate",
        }, headers=headers)["candidate"]
        case = self.call("POST", "/api/v1/interview-cases", {
            "candidateId": candidate["id"], "jobId": job["id"],
            "committeeMembers": [{"displayName": "Lead", "role": "LEAD"}],
        }, headers=headers)["case"]
        with self.application.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='DOCUMENTS_READY' WHERE id=?",
                (case["id"],),
            )
        question_set = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set",
            {"operation": "MANUAL", "questions": valid_questions()}, headers=headers,
        )["questionSet"]
        return case, question_set

    def approve_question_set(self, case_id, question_set_id):
        member_id = self.call(
            "GET", f"/api/v1/interview-cases/{case_id}",
            headers=self.committee_headers(False),
        )["case"]["committeeMembers"][0]["id"]
        return self.call(
            "POST", f"/api/v1/interview-cases/{case_id}/question-set/approve",
            {"questionSetId": question_set_id, "memberId": member_id, "confirmation": "APPROVE_QUESTION_SET"},
            headers=self.committee_headers(),
        )

    def confirm_documents(self, case_id):
        for document_type, text in (
            ("JD", "Senior backend role"),
            ("CV", "Backend experience"),
        ):
            document = self.call(
                "POST", f"/api/v1/interview-cases/{case_id}/documents",
                {"documentType": document_type, "sourceKind": "MANUAL_TEXT", "text": text},
                headers=self.committee_headers(),
            )["document"]
            self.call(
                "POST",
                f"/api/v1/interview-cases/{case_id}/documents/{document['id']}/confirm",
                {"confirmed": True, "textSha256": document["contentSha256"]},
                headers=self.committee_headers(),
            )

    def test_question_addition_api_creates_reads_applies_and_discards(self):
        case, question_set = self.create_manual_case("JOB-ADDITION", "CAND-ADDITION")
        self.confirm_documents(case["id"])
        base = f"/api/v1/interview-cases/{case['id']}/question-set/question-additions"
        task = self.call(
            "POST", base,
            {
                "questionSetId": question_set["id"],
                "questionCategory": "APPLICATION",
                "mode": "AUTO_GROUP",
            },
            headers={**self.committee_headers(), "X-Idempotency-Key": "addition-api-key"},
        )
        self.assertEqual("APPLICATION", task["questionCategory"])
        completed = self.wait_task(task["taskId"])
        self.assertEqual("APPLICATION", completed["task"]["targetQuestionCategory"])
        self.assertIsNotNone(completed["task"]["additionProposalId"])

        listed = self.call(
            "GET", f"{base}?questionSetId={question_set['id']}&questionCategory=APPLICATION",
            headers=self.committee_headers(False),
        )
        proposal = listed["items"][0]
        self.assertNotIn("payload", proposal)
        detail = self.call(
            "GET", f"{base}/{proposal['id']}", headers=self.committee_headers(False)
        )
        applied = self.call(
            "POST", f"{base}/{proposal['id']}/apply",
            {
                "questionSetId": question_set["id"],
                "expectedQuestionSetUpdatedAt": question_set["updatedAt"],
                "expectedSourceFingerprint": detail["sourceFingerprint"],
            },
            headers=self.committee_headers(),
        )
        self.assertEqual(10, applied["question"]["displayOrder"])
        self.assertEqual("APPLIED", applied["proposal"]["status"])

        second = self.call(
            "POST", base,
            {
                "questionSetId": question_set["id"],
                "questionCategory": "FOUNDATION",
                "mode": "AUTO_GROUP",
            },
            headers={**self.committee_headers(), "X-Idempotency-Key": "addition-api-discard"},
        )
        self.wait_task(second["taskId"])
        foundation = self.call(
            "GET", f"{base}?questionSetId={question_set['id']}&questionCategory=FOUNDATION",
            headers=self.committee_headers(False),
        )["items"][0]
        discarded = self.call(
            "POST", f"{base}/{foundation['id']}/discard", headers=self.committee_headers()
        )
        self.assertEqual("DISCARDED", discarded["status"])

        self.assertEqual(
            401,
            self.error_status("POST", base, {
                "questionSetId": question_set["id"],
                "questionCategory": "APPLICATION",
                "mode": "AUTO_GROUP",
            }),
        )
        self.assertEqual(
            422,
            self.error_status(
                "POST", base,
                {
                    "questionSetId": question_set["id"],
                    "questionCategory": "APPLICATION",
                    "mode": "UNSUPPORTED",
                },
                headers=self.committee_headers(),
            ),
        )

    def test_question_variant_export_contains_only_explicitly_applied_prompt(self):
        case, question_set = self.create_manual_case("JOB-VARIANT-EXPORT", "CAND-VARIANT-EXPORT")
        question = question_set["questions"][0]
        path = f"/api/v1/interview-cases/{case['id']}/question-set/questions/{question['id']}/variants"
        task = self.call(
            "POST", path,
            {"questionSetId": question_set["id"], "mode": "USER_PROMPT", "prompt": "Tập trung vào trade-off"},
            headers={**self.committee_headers(), "X-Idempotency-Key": "variant-export-key"},
        )
        completed = self.wait_task(task["taskId"])
        proposal = self.call(
            "GET", f"{path}/{completed['task']['proposalId']}",
            headers=self.committee_headers(False),
        )
        refreshed = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/question-set",
            headers=self.committee_headers(False),
        )["questionSet"]
        self.call(
            "POST", f"{path}/{proposal['proposalId']}/apply",
            {
                "expectedQuestionSetUpdatedAt": refreshed["updatedAt"],
                "expectedSourceFingerprint": proposal["sourceFingerprint"],
            },
            headers=self.committee_headers(),
        )
        updated = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/question-set",
            headers=self.committee_headers(False),
        )["questionSet"]
        updated_question = updated["questions"][0]
        for field in ("id", "displayOrder", "competencyKey", "questionCategory", "questionType", "difficulty", "isRequired", "estimatedSeconds", "sourceKind"):
            self.assertEqual(question[field], updated_question[field], field)
        self.assertEqual(proposal["variant"]["questionText"], updated_question["questionText"])
        self.approve_question_set(case["id"], updated["id"])
        status, _, package = self.call_binary(
            "POST", f"/api/v1/interview-cases/{case['id']}/candidate-package/export",
            headers=self.committee_headers(),
        )
        self.assertEqual(200, status)
        exported = import_candidate_package(package)
        exported_question = next(item for item in exported.questions if item["questionId"] == question["id"])
        self.assertEqual(updated_question["questionText"], exported_question["questionText"])

    def test_question_variant_same_group_preserves_slot_and_proposal_can_be_discarded(self):
        case, question_set = self.create_manual_case("JOB-VARIANT-GROUP", "CAND-VARIANT-GROUP")
        question = question_set["questions"][0]
        path = f"/api/v1/interview-cases/{case['id']}/question-set/questions/{question['id']}/variants"
        task = self.call(
            "POST", path,
            {"questionSetId": question_set["id"], "mode": "SAME_GROUP"},
            headers={**self.committee_headers(), "X-Idempotency-Key": "variant-group-key"},
        )
        completed = self.wait_task(task["taskId"])
        proposal_path = f"{path}/{completed['task']['proposalId']}"
        proposal = self.call("GET", proposal_path, headers=self.committee_headers(False))
        self.assertEqual("SAME_GROUP", proposal["mode"])
        self.assertNotEqual(question["questionText"], proposal["variant"]["questionText"])
        active = self.call(
            "GET", path + "?questionSetId=" + question_set["id"],
            headers=self.committee_headers(False),
        )["items"]
        self.assertEqual([proposal["proposalId"]], [item["proposalId"] for item in active])
        self.call("POST", proposal_path + "/discard", headers=self.committee_headers())
        current = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/question-set",
            headers=self.committee_headers(False),
        )["questionSet"]["questions"][0]
        for field in ("id", "displayOrder", "competencyKey", "questionCategory", "questionType", "difficulty"):
            self.assertEqual(question[field], current[field], field)
        self.assertEqual(question["questionText"], current["questionText"])

    def test_question_variant_api_locks_approved_and_assessment_started_and_isolates_cases(self):
        case, question_set = self.create_manual_case("JOB-VARIANT-LOCK", "CAND-VARIANT-LOCK")
        question_id = question_set["questions"][0]["id"]
        path = f"/api/v1/interview-cases/{case['id']}/question-set/questions/{question_id}/variants"
        self.approve_question_set(case["id"], question_set["id"])
        self.assertEqual(
            409,
            self.error_status(
                "POST", path,
                {"questionSetId": question_set["id"], "mode": "SAME_GROUP"},
                headers=self.committee_headers(),
            ),
        )

        other_case, other_set = self.create_manual_case("JOB-VARIANT-ISOLATION", "CAND-VARIANT-ISOLATION")
        other_question_id = other_set["questions"][0]["id"]
        other_path = f"/api/v1/interview-cases/{other_case['id']}/question-set/questions/{other_question_id}/variants"
        self.assertEqual(404, self.error_status("GET", other_path + "/missing-proposal", headers=self.committee_headers(False)))
        with self.application.database.transaction() as connection:
            connection.execute(
                "INSERT INTO assessment_attempts(id, interview_case_id, question_set_id, status) VALUES (?, ?, ?, 'ASSESSMENT_IN_PROGRESS')",
                (str(uuid.uuid4()), other_case["id"], other_set["id"]),
            )
        self.assertEqual(
            409,
            self.error_status(
                "POST", other_path,
                {"questionSetId": other_set["id"], "mode": "SAME_GROUP"},
                headers=self.committee_headers(),
            ),
        )

    def test_question_variant_schema_and_provider_failures_are_visible_without_proposal(self):
        case, question_set = self.create_manual_case("JOB-VARIANT-FAIL", "CAND-VARIANT-FAIL")
        question_id = question_set["questions"][0]["id"]
        path = f"/api/v1/interview-cases/{case['id']}/question-set/questions/{question_id}/variants"
        self.provider.variant_invalid = True
        invalid_task = self.call(
            "POST", path,
            {"questionSetId": question_set["id"], "mode": "SAME_GROUP"},
            headers={**self.committee_headers(), "X-Idempotency-Key": "variant-invalid-key"},
        )
        invalid_result = self.wait_task_terminal(invalid_task["taskId"])
        self.assertEqual("FAILED", invalid_result["task"]["status"])
        self.assertEqual("AI_SCHEMA_VALIDATION_FAILED", invalid_result["task"]["errorCode"])
        self.assertEqual([], self.call("GET", path + "?questionSetId=" + question_set["id"], headers=self.committee_headers(False))["items"])

        self.provider.variant_invalid = False
        self.provider.variant_failure = True
        failed_task = self.call(
            "POST", path,
            {"questionSetId": question_set["id"], "mode": "SAME_GROUP"},
            headers={**self.committee_headers(), "X-Idempotency-Key": "variant-provider-failure-key"},
        )
        failed_result = self.wait_task_terminal(failed_task["taskId"])
        self.assertEqual("FAILED", failed_result["task"]["status"])
        self.assertEqual("AI_PROVIDER_UNEXPECTED_ERROR", failed_result["task"]["errorCode"])
        self.assertEqual([], self.call("GET", path + "?questionSetId=" + question_set["id"], headers=self.committee_headers(False))["items"])

    def test_question_variant_api_is_idempotent_and_requires_explicit_apply(self):
        headers = self.committee_headers()
        job = self.call("POST", "/api/v1/jobs", {
            "jobCode": "JOB-VARIANT", "positionTitle": "Backend Engineer", "targetLevel": "Senior",
        }, headers=headers)["job"]
        candidate = self.call("POST", "/api/v1/candidates", {
            "candidateCode": "CAND-VARIANT", "fullName": "Variant Candidate",
        }, headers=headers)["candidate"]
        case = self.call("POST", "/api/v1/interview-cases", {
            "candidateId": candidate["id"], "jobId": job["id"],
            "committeeMembers": [{"displayName": "Lead", "role": "LEAD"}],
        }, headers=headers)["case"]
        with self.application.database.transaction() as connection:
            connection.execute(
                "UPDATE interview_cases SET status='DOCUMENTS_READY' WHERE id=?",
                (case["id"],),
            )
        question_set = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set",
            {"operation": "MANUAL", "questions": valid_questions()}, headers=headers,
        )["questionSet"]
        question_id = question_set["questions"][0]["id"]
        variant_path = (
            f"/api/v1/interview-cases/{case['id']}/question-set/questions/"
            f"{question_id}/variants"
        )
        create_body = {
            "questionSetId": question_set["id"],
            "mode": "USER_PROMPT",
            "prompt": "Tập trung vào trade-off",
        }
        created = self.call(
            "POST", variant_path, create_body,
            headers={**headers, "X-Idempotency-Key": "variant-http-key"},
        )
        repeated = self.call(
            "POST", variant_path, create_body,
            headers={**headers, "X-Idempotency-Key": "variant-http-key"},
        )
        self.assertEqual(created["taskId"], repeated["taskId"])

        task = self.wait_task(created["taskId"])
        with self.application.database.connection() as connection:
            proposal_row = connection.execute(
                "SELECT id FROM question_variant_proposals WHERE source_question_id=?",
                (question_id,),
            ).fetchone()
        self.assertIsNotNone(proposal_row, task)
        proposal_id = proposal_row[0]
        proposal_path = f"{variant_path}/{proposal_id}"
        proposal = self.call("GET", proposal_path, headers=self.committee_headers(False))
        self.assertEqual("PROPOSED", proposal["status"])
        self.assertNotIn("payloadJson", proposal)
        self.assertNotIn("rawPayload", proposal)
        active = self.call(
            "GET",
            variant_path + "?questionSetId=" + question_set["id"],
            headers=self.committee_headers(False),
        )
        self.assertEqual([proposal_id], [item["proposalId"] for item in active["items"]])

        refreshed = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/question-set",
            headers=self.committee_headers(False),
        )["questionSet"]
        applied = self.call(
            "POST", f"{proposal_path}/apply",
            {
                "expectedQuestionSetUpdatedAt": refreshed["updatedAt"],
                "expectedSourceFingerprint": proposal["sourceFingerprint"],
            },
            headers=headers,
        )
        self.assertEqual("APPLIED", applied["proposal"]["status"])
        self.assertEqual(question_id, applied["question"]["id"])

    def test_question_variant_api_rejects_invalid_prompt_and_missing_committee(self):
        headers = self.committee_headers()
        path = "/api/v1/interview-cases/missing/question-set/questions/missing/variants"
        self.assertEqual(401, self.error_status("POST", path, {"mode": "SAME_GROUP"}))
        self.assertEqual(
            422,
            self.error_status(
                "POST", path,
                {"questionSetId": "missing", "mode": "USER_PROMPT", "prompt": " "}, headers=headers,
            ),
        )
        self.assertEqual(
            422,
            self.error_status(
                "POST", path,
                {"questionSetId": "missing", "mode": "USER_PROMPT", "prompt": "x" * 2001}, headers=headers,
            ),
        )
        self.assertEqual(
            422,
            self.error_status(
                "POST", path,
                {"questionSetId": "missing", "mode": "SAME_GROUP", "prompt": "not allowed"}, headers=headers,
            ),
        )

    def test_complete_excel_question_answer_evaluation_flow_over_http(self):
        headers = self.committee_headers()
        job = self.call("POST", "/api/v1/jobs", {
            "jobCode": "JOB-EXCEL", "positionTitle": "Backend Engineer", "targetLevel": "Senior",
        }, headers=headers)["job"]
        candidate = self.call("POST", "/api/v1/candidates", {
            "candidateCode": "CAND-EXCEL", "fullName": "Pilot Candidate",
        }, headers=headers)["candidate"]
        case = self.call("POST", "/api/v1/interview-cases", {
            "candidateId": candidate["id"], "jobId": job["id"],
            "committeeMembers": [{"displayName": "Lead", "role": "LEAD"}],
        }, headers=headers)["case"]

        for document_type, text in (("JD", "Build reliable backend systems"), ("CV", "Built Python services")):
            document = self.call(
                "POST", f"/api/v1/interview-cases/{case['id']}/documents",
                {"documentType": document_type, "sourceKind": "MANUAL_TEXT", "text": text},
                headers=headers,
            )["document"]
            self.call(
                "POST", f"/api/v1/interview-cases/{case['id']}/documents/{document['id']}/confirm",
                {"confirmed": True, "textSha256": document["contentSha256"]}, headers=headers,
            )

        generation = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set",
            {"operation": "GENERATE"}, headers=headers,
        )
        self.wait_task(generation["taskId"])
        question_set = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/question-set",
            headers=self.committee_headers(False),
        )["questionSet"]

        export_status, export_headers, exported_bytes = self.call_binary(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set/export",
            headers=headers,
        )
        self.assertEqual(200, export_status)
        self.assertIn("spreadsheetml.sheet", export_headers["Content-Type"])
        workbook = import_question_answer_workbook(exported_bytes)
        workbook.questions[0]["answerText"] = "A concrete answer from Excel"
        workbook.questions[0]["isAnswered"] = True
        completed_workbook = export_question_answer_workbook(workbook.metadata, workbook.questions)

        imported = self.call_binary(
            "POST", f"/api/v1/interview-cases/{case['id']}/assessment-snapshots/import",
            body=completed_workbook,
            headers={
                **headers,
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "X-Idempotency-Key": "excel-http-import-1",
            },
        )
        snapshot_response = json.loads(imported[2])["data"]["snapshot"]
        self.assertEqual(question_set["id"], snapshot_response["questionSetId"])
        snapshot_id = snapshot_response["id"]
        snapshot = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/assessment-snapshots/{snapshot_id}",
            headers=self.committee_headers(False),
        )["snapshot"]
        self.assertEqual("ANSWERS_IMPORTED", snapshot["refinedFlowStatus"])
        current_snapshot = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/assessment-snapshots/current",
            headers=self.committee_headers(False),
        )["snapshot"]
        self.assertEqual(snapshot_id, current_snapshot["id"])

        evaluation_task = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/ai/evaluate",
            {"snapshotId": snapshot_id},
            headers={**headers, "X-Idempotency-Key": "excel-evaluation-1"},
        )
        evaluation_result = self.wait_task(evaluation_task["taskId"])
        self.assertEqual("EVALUATION_SYNTHESIS", evaluation_result["task"]["phase"])
        result = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/ai/evaluation",
            headers=self.committee_headers(False),
        )["result"]
        self.assertEqual("answer-evaluation.v2", result["payload"]["schemaVersion"])
        self.assertNotIn("interviewBrief", result["payload"])
        self.assertEqual(404, self.error_status(
            "GET", f"/api/v1/interview-cases/{case['id']}/interview-brief",
            headers=self.committee_headers(False),
        ))

    def test_complete_html_candidate_package_flow_over_http(self):
        headers = self.committee_headers()
        job = self.call("POST", "/api/v1/jobs", {
            "jobCode": "JOB-HTML", "positionTitle": "Backend Engineer", "targetLevel": "Senior",
        }, headers=headers)["job"]
        candidate = self.call("POST", "/api/v1/candidates", {
            "candidateCode": "CAND-HTML", "fullName": "HTML Candidate",
        }, headers=headers)["candidate"]
        case = self.call("POST", "/api/v1/interview-cases", {
            "candidateId": candidate["id"], "jobId": job["id"],
            "committeeMembers": [{"displayName": "Lead", "role": "LEAD"}],
        }, headers=headers)["case"]
        for document_type, text in (("JD", "Build reliable backend systems"), ("CV", "Built Python services")):
            document = self.call(
                "POST", f"/api/v1/interview-cases/{case['id']}/documents",
                {"documentType": document_type, "sourceKind": "MANUAL_TEXT", "text": text},
                headers=headers,
            )["document"]
            self.call(
                "POST", f"/api/v1/interview-cases/{case['id']}/documents/{document['id']}/confirm",
                {"confirmed": True, "textSha256": document["contentSha256"]}, headers=headers,
            )
        question_set = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set",
            {"operation": "MANUAL", "questions": valid_questions(), "durationSeconds": 900},
            headers=headers,
        )["questionSet"]
        member_id = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}",
            headers=self.committee_headers(False),
        )["case"]["committeeMembers"][0]["id"]
        self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set/approve",
            {"questionSetId": question_set["id"], "memberId": member_id, "confirmation": "APPROVE_QUESTION_SET"},
            headers=headers,
        )

        export_status, export_headers, package_bytes = self.call_binary(
            "POST", f"/api/v1/interview-cases/{case['id']}/candidate-package/export",
            headers=headers,
        )
        self.assertEqual(200, export_status)
        self.assertEqual("text/html; charset=utf-8", export_headers["Content-Type"])
        self.assertIn(".html", export_headers["Content-Disposition"])
        self.assertEqual("QUESTION", import_candidate_package(package_bytes).package_type)

        response = response_html(package_bytes)
        imported = self.call_binary(
            "POST", f"/api/v1/interview-cases/{case['id']}/candidate-package/import",
            body=response,
            headers={**headers, "Content-Type": "text/html", "X-Idempotency-Key": "html-http-import-1"},
        )
        snapshot = json.loads(imported[2])["data"]["snapshot"]
        self.assertEqual("HTML_IMPORT", snapshot["sourceKind"])
        self.assertEqual("ANSWERS_IMPORTED", snapshot["refinedFlowStatus"])
        self.assertEqual("A concrete answer from HTML", snapshot["answers"][0]["answerText"])

        self.provider.block_evidence = True
        evaluation_headers = {**headers, "X-Idempotency-Key": "html-evaluation-1"}
        evaluation_task = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/ai/evaluate",
            {"snapshotId": snapshot["id"]}, headers=evaluation_headers,
        )
        self.assertTrue(self.provider.evidence_started.wait(1))
        duplicate_task = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/ai/evaluate",
            {"snapshotId": snapshot["id"]}, headers=evaluation_headers,
        )
        self.assertEqual(evaluation_task["taskId"], duplicate_task["taskId"])
        running = self.call(
            "GET", f"/api/v1/tasks/{evaluation_task['taskId']}",
            headers=self.committee_headers(False),
        )
        self.assertEqual("EVIDENCE_ANALYSIS", running["task"]["phase"])
        self.provider.release_evidence.set()
        evaluation_result = self.wait_task(evaluation_task["taskId"])
        self.assertEqual("EVALUATION_SYNTHESIS", evaluation_result["task"]["phase"])
        result = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/ai/evaluation",
            headers=self.committee_headers(False),
        )["result"]
        self.assertEqual("answer-evaluation.v2", result["payload"]["schemaVersion"])
        self.assertNotIn("candidate-package-payload", json.dumps(result["payload"]))
        self.assertEqual(422, self.error_status(
            "POST", f"/api/v1/interview-cases/{case['id']}/candidate-package/import",
            body=b"not html package", headers={**headers, "Content-Type": "text/html", "X-Idempotency-Key": "html-http-bad"},
        ))
        self.assertEqual(401, self.error_status(
            "POST", f"/api/v1/interview-cases/{case['id']}/candidate-package/export",
        ))


if __name__ == "__main__":
    unittest.main()
