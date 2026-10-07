from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from app.ai.factory import configured_ai_metadata
from app.ai.provider import AIProvider, ProviderError
from app.ai.schemas import SchemaRegistry
from app.ai.task_worker import AITaskWorker
from app.api import APIController
from app.config import AppConfig
from app.database import Database
from app.migrations import MigrationRunner
from app.router import Router
from app.security import LocalSecurity
from app.services.ai_task_service import AITaskService
from app.services.assessment_service import AssessmentService
from app.services.evaluation_service import EvaluationService
from app.services.interview_brief_service import InterviewBriefService
from app.services.interview_service import InterviewService
from app.services.question_generation_service import QuestionGenerationService


class _TaskProcessor:
    def __init__(
        self,
        database: Database,
        schema_root: Path,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.tasks = AITaskService(database, SchemaRegistry(schema_root))
        self.questions = QuestionGenerationService(
            database, schema_root, provider_name=provider_name, model_name=model_name
        )
        self.evaluations = EvaluationService(
            database, schema_root, provider_name=provider_name, model_name=model_name
        )
        self.briefs = InterviewBriefService(database)
        self.interviews = InterviewService(
            database, provider_name=provider_name, model_name=model_name
        )

    def process(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.evaluations.tasks.repository.get(task_id)
        try:
            if task["taskType"] == "GENERATE_QUESTIONS":
                return self.questions.process(task_id, provider)
            if task["taskType"] in {"EVALUATE_ASSESSMENT", "GENERATE_BRIEF"}:
                result = self.evaluations.process(task_id, provider)
                if (
                    result["status"] == "COMPLETED"
                    and task["taskType"] == "EVALUATE_ASSESSMENT"
                    and task.get("assessmentSnapshotId") is None
                ):
                    self.briefs.materialize_ai(task_id)
                return result
            if task["taskType"] == "SUGGEST_FOLLOW_UP":
                return self.interviews.process_follow_up(task_id, provider)
            return self.evaluations.tasks.process(task_id, provider)
        except Exception:
            return self.tasks.fail_materialization(task_id)


class _UnavailableProvider:
    def _raise(self) -> dict[str, Any]:
        raise ProviderError(
            "AI provider is not configured", code="AI_NOT_CONFIGURED", retryable=False
        )

    def generate_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._raise()

    def evaluate_answers(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._raise()

    def suggest_follow_up(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._raise()


@dataclass
class Application:
    config: AppConfig
    database: Database
    router: Router
    security: LocalSecurity
    task_service: AITaskService
    worker: AITaskWorker | None
    _housekeeping_stop: threading.Event | None = None
    _housekeeping_thread: threading.Thread | None = None

    def start(self) -> None:
        AssessmentService(self.database).recover_startup()
        recovery = self.task_service.recover_interrupted()
        if self.worker is not None:
            self.worker.start()
            for task_id in self.task_service.repository.pending_ids():
                self.worker.submit(task_id)
            for task_id in self.task_service.repository.recoverable_materialization_ids():
                self.worker.submit(task_id)
        self._housekeeping_stop = threading.Event()
        self._housekeeping_thread = threading.Thread(
            target=self._run_housekeeping,
            name="assessment-housekeeping",
            daemon=True,
        )
        self._housekeeping_thread.start()

    def submit_task(self, task_id: str) -> None:
        if self.worker is not None:
            self.worker.submit(task_id)

    def stop(self) -> None:
        if self._housekeeping_stop is not None:
            self._housekeeping_stop.set()
        if self._housekeeping_thread is not None:
            self._housekeeping_thread.join(2)
        self._housekeeping_thread = None
        self._housekeeping_stop = None
        if self.worker is not None:
            self.worker.stop()

    def _run_housekeeping(self) -> None:
        assert self._housekeeping_stop is not None
        assessments = AssessmentService(self.database)
        while not self._housekeeping_stop.wait(0.25):
            try:
                assessments.expire_due()
            except Exception:
                # A transient SQLite/filesystem issue is retried on the next tick;
                # it must not terminate server-authoritative expiry enforcement.
                continue


def create_application(
    config: AppConfig,
    *,
    provider: AIProvider | None = None,
    initial_pin: str | None = None,
) -> Application:
    config.ensure_directories()
    root = Path(__file__).resolve().parents[1]
    database = Database(config.database_path)
    MigrationRunner(database, root / "migrations").apply_all()
    security = LocalSecurity(database)
    if initial_pin and not security.is_pin_configured():
        security.set_committee_pin(initial_pin)
    schemas = SchemaRegistry(root / "schemas")
    task_service = AITaskService(database, schemas)
    provider_name, model_name = configured_ai_metadata(config)
    processor = _TaskProcessor(
        database,
        root / "schemas",
        provider_name=provider_name,
        model_name=model_name,
    )
    worker = AITaskWorker(processor, provider or _UnavailableProvider())
    router = Router()
    application = Application(config, database, router, security, task_service, worker)
    APIController(
        database, config.data_directory, root / "schemas", security,
        application.submit_task,
        ai_provider_name=provider_name,
        ai_model_name=model_name,
        pdf_text_extractor_path=config.pdf_text_extractor_path,
        pdf_text_extractor_timeout_seconds=config.pdf_text_extractor_timeout_seconds,
    ).register(router)
    return application
