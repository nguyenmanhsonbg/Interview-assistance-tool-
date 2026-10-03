import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.assessment_setup import create_approved_case


class ApplicationHousekeepingTests(unittest.TestCase):
    def test_live_housekeeping_auto_submits_expired_attempt(self):
        from app.application import create_application
        from app.config import AppConfig
        from app.services.assessment_service import AssessmentService

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            application = create_application(
                AppConfig(
                    port=0,
                    data_directory=root,
                    web_directory=Path(__file__).resolve().parents[1] / "web",
                ),
                initial_pin="246810",
            )
            self.database = application.database
            application.start()
            try:
                case, question_set, _ = create_approved_case(self)
                service = AssessmentService(self.database)
                service.prepare(case["id"], question_set["id"])
                attempt = service.start(
                    case["id"],
                    candidate_code_confirmed=True,
                    committee_authorized=True,
                )
                expired = datetime.now(timezone.utc) - timedelta(seconds=1)
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE assessment_attempts SET expires_at=? WHERE id=?",
                        (expired.isoformat().replace("+00:00", "Z"), attempt["id"]),
                    )

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    current = service.get_for_case(case["id"])
                    if current["status"] == "ASSESSMENT_SUBMITTED":
                        break
                    time.sleep(0.05)
                self.assertEqual("ASSESSMENT_SUBMITTED", current["status"])
                self.assertEqual("TIME_EXPIRED", current["submitReason"])
            finally:
                application.stop()

    def test_materialization_failure_enters_manual_fallback_without_killing_task_processing(self):
        from app.application import create_application
        from app.config import AppConfig
        from app.services.case_service import CaseService
        from app.services.document_service import DocumentService
        from app.services.question_generation_service import QuestionGenerationService
        from tests.ai_fixtures import question_generation_payload

        class Provider:
            def generate_questions(self, payload):
                return question_generation_payload()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            application = create_application(
                AppConfig(port=0, data_directory=root), provider=Provider(), initial_pin="246810"
            )
            cases = CaseService(application.database)
            job = cases.create_job("MAT-J", "Engineer", "Senior")
            candidate = cases.create_candidate("MAT-C", "Candidate")
            case = cases.create_case(candidate["id"], job["id"])
            documents = DocumentService(application.database, root)
            jd = documents.import_manual_text(case["id"], "JD", "Role")
            cv = documents.import_manual_text(case["id"], "CV", "Experience")
            documents.confirm(jd["id"], jd["contentSha256"])
            documents.confirm(cv["id"], cv["contentSha256"])
            task = QuestionGenerationService(
                application.database, Path(__file__).resolve().parents[1] / "schemas"
            ).request(case["id"], idempotency_key="materialize-failure")
            processor = application.worker.service
            processor.questions.questions.materialize_generated = (
                lambda *_: (_ for _ in ()).throw(RuntimeError("simulated"))
            )

            result = processor.process(task["id"], Provider())

            self.assertEqual("COMPLETED", result["status"])
            self.assertEqual("AI_MATERIALIZATION_FAILED", result["errorCode"])
            with application.database.connection() as connection:
                status = connection.execute(
                    "SELECT status FROM interview_cases WHERE id=?", (case["id"],)
                ).fetchone()[0]
            self.assertEqual("QUESTION_GENERATION_FAILED", status)


if __name__ == "__main__":
    unittest.main()
