import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.infrastructure.excel_question_answer import (
    export_question_answer_workbook,
    import_question_answer_workbook,
)
from tests.ai_fixtures import answer_evaluation_v2_payload, question_generation_payload


class FakePilotProvider:
    def generate_questions(self, payload):
        return question_generation_payload()

    def evaluate_answers(self, payload):
        return answer_evaluation_v2_payload(answered=True)

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
        self.application = create_application(
            config, provider=FakePilotProvider(), initial_pin="246810"
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
        data = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = dict(headers or {})
        if data is not None:
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
            {"snapshotId": snapshot_id}, headers=headers,
        )
        self.wait_task(evaluation_task["taskId"])
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


if __name__ == "__main__":
    unittest.main()
