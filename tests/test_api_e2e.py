import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests.ai_fixtures import answer_evaluation_payload, follow_up_payload, question_generation_payload


class FakePilotProvider:
    def generate_questions(self, payload):
        return question_generation_payload()

    def evaluate_answers(self, payload):
        return answer_evaluation_payload(answered=True)

    def suggest_follow_up(self, payload):
        return follow_up_payload()


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

    def test_complete_pilot_workflow_over_http(self):
        headers = self.committee_headers()
        job = self.call("POST", "/api/v1/jobs", {
            "jobCode": "JOB-E2E", "positionTitle": "Backend Engineer", "targetLevel": "Senior",
        }, headers=headers)["job"]
        candidate = self.call("POST", "/api/v1/candidates", {
            "candidateCode": "CAND-E2E", "fullName": "Pilot Candidate",
        }, headers=headers)["candidate"]
        case = self.call("POST", "/api/v1/interview-cases", {
            "candidateId": candidate["id"], "jobId": job["id"],
            "committeeMembers": [{"displayName": "Lead", "role": "LEAD"}],
        }, headers=headers)["case"]
        member_id = case["committeeMembers"][0]["id"]

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
        self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/question-set/approve",
            {"questionSetId": question_set["id"], "memberId": member_id,
             "confirmation": "APPROVE_QUESTION_SET"}, headers=headers,
        )
        attempt = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/assessment",
            {"questionSetId": question_set["id"]}, headers=headers,
        )["attempt"]
        started = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/assessment/start",
            {"candidateCodeConfirmed": True, "committeePinVerified": True}, headers=headers,
        )["attempt"]
        self.assertEqual(
            401,
            self.error_status(
                "GET", "/api/v1/interview-cases",
                headers={"X-Committee-Session": self.session},
            ),
        )
        candidate_headers = {
            "X-Startup-Token": self.startup,
            "X-Candidate-Token": started["candidateToken"],
            "X-Idempotency-Key": "e2e-submit-once",
        }
        candidate_view = self.call(
            "GET", f"/api/v1/assessment-attempts/{attempt['id']}/questions",
            headers={"X-Candidate-Token": started["candidateToken"]},
        )
        first_question = candidate_view["questions"][0]
        self.call(
            "PUT", f"/api/v1/assessment-attempts/{attempt['id']}/answers/{first_question['id']}",
            {"text": "A concrete answer", "isAnswered": True, "clientRevision": 1},
            headers=candidate_headers,
        )
        submit_body = {
            "confirmation": "SUBMIT_ASSESSMENT",
            "answerRevisions": {
                question["id"]: 1 if question["id"] == first_question["id"] else 0
                for question in candidate_view["questions"]
            },
        }
        first_submit = self.call(
            "POST", f"/api/v1/assessment-attempts/{attempt['id']}/submit",
            submit_body, headers=candidate_headers,
        )
        replayed_submit = self.call(
            "POST", f"/api/v1/assessment-attempts/{attempt['id']}/submit",
            submit_body, headers=candidate_headers,
        )
        self.assertEqual(
            first_submit["attempt"]["submittedAt"],
            replayed_submit["attempt"]["submittedAt"],
        )
        self.assertEqual(
            401,
            self.error_status(
                "GET", f"/api/v1/assessment-attempts/{attempt['id']}/questions",
                headers={"X-Candidate-Token": started["candidateToken"]},
            ),
        )
        auth = self.call(
            "POST", "/api/v1/auth/committee-session", {"pin": "246810"},
            headers={"X-Startup-Token": self.startup},
        )
        self.session = auth["committeeSession"]
        headers = self.committee_headers()
        evaluation_task = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/ai/evaluate",
            {"attemptId": attempt["id"]}, headers=headers,
        )
        self.wait_task(evaluation_task["taskId"])

        brief = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}/interview-brief",
            headers=self.committee_headers(False),
        )["brief"]
        self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/live-interview/start",
            {"memberId": member_id}, headers=headers,
        )
        for sequence in range(1, 4):
            self.call(
                "POST", f"/api/v1/interview-cases/{case['id']}/live-interview/records",
                {"sequenceNo": sequence, "committeeMemberId": member_id,
                 "askedStatus": "ASKED", "liveNotes": f"Evidence {sequence}",
                 "score": 3, "evidenceStatus": "VERIFIED"}, headers=headers,
            )
        self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/live-interview/complete",
            {"memberId": member_id, "reason": "AGENDA_COMPLETE"}, headers=headers,
        )
        draft = self.call(
            "PUT", f"/api/v1/interview-cases/{case['id']}/final-evaluation",
            {"finalResult": "PASS", "summary": "Committee-owned decision",
             "strengths": [], "gaps": [], "risks": []}, headers=headers,
        )["evaluation"]
        final = self.call(
            "POST", f"/api/v1/interview-cases/{case['id']}/final-evaluation/finalize",
            {"evaluationId": draft["id"], "memberId": member_id,
             "confirmation": "FINALIZE_EVALUATION"}, headers=headers,
        )["evaluation"]
        self.assertEqual("FINAL", final["status"])
        overview = self.call(
            "GET", f"/api/v1/interview-cases/{case['id']}",
            headers=self.committee_headers(False),
        )["case"]
        self.assertEqual("EVALUATED", overview["status"])
        self.assertEqual(brief["id"], overview["currentBriefId"])


if __name__ == "__main__":
    unittest.main()
