from __future__ import annotations

import base64
import binascii
import uuid
from typing import Any, Callable

from app.database import Database
from app.domain.errors import ResourceNotFound, ValidationError
from app.repositories.ai_tasks import AITaskRepository
from app.responses import Response, success_response
from app.router import Request, Router
from app.security import LocalSecurity
from app.services.application_query_service import ApplicationQueryService
from app.services.assessment_service import AssessmentService
from app.services.backup_service import BackupService
from app.services.case_service import CaseService
from app.services.document_service import DocumentService
from app.services.excel_assessment_service import ExcelAssessmentService
from app.services.evaluation_service import EvaluationService
from app.services.interview_brief_service import InterviewBriefService
from app.services.interview_service import InterviewService
from app.services.question_generation_service import QuestionGenerationService
from app.services.question_service import QuestionService


class APIController:
    def __init__(
        self,
        database: Database,
        data_root,
        schema_root,
        security: LocalSecurity,
        submit_task: Callable[[str], None],
        *,
        ai_provider_name: str | None = None,
        ai_model_name: str | None = None,
    ) -> None:
        self.database = database
        self.security = security
        self.submit_task = submit_task
        self.cases = CaseService(database)
        self.documents = DocumentService(database, data_root)
        self.excel_assessments = ExcelAssessmentService(database)
        self.questions = QuestionService(database)
        self.question_generation = QuestionGenerationService(
            database,
            schema_root,
            provider_name=ai_provider_name,
            model_name=ai_model_name,
        )
        self.assessments = AssessmentService(database)
        self.evaluations = EvaluationService(
            database,
            schema_root,
            provider_name=ai_provider_name,
            model_name=ai_model_name,
        )
        self.briefs = InterviewBriefService(database)
        self.interviews = InterviewService(
            database,
            provider_name=ai_provider_name,
            model_name=ai_model_name,
        )
        self.backups = BackupService(database, data_root)
        self.queries = ApplicationQueryService(database)
        self.tasks = AITaskRepository(database)

    def register(self, router: Router) -> None:
        committee = {"access_mode": "COMMITTEE"}
        router.add("POST", r"/api/v1/auth/committee-session", self.authenticate, access_mode="STARTUP")
        router.add("POST", r"/api/v1/auth/committee-pin", self.setup_pin, access_mode="STARTUP")
        router.add("POST", r"/api/v1/auth/lock", self.lock, **committee)
        router.add("GET", r"/api/v1/jobs", self.list_jobs, **committee)
        router.add("POST", r"/api/v1/jobs", self.create_job, **committee)
        router.add("GET", r"/api/v1/candidates", self.list_candidates, **committee)
        router.add("POST", r"/api/v1/candidates", self.create_candidate, **committee)
        router.add("GET", r"/api/v1/interview-cases", self.list_cases, **committee)
        router.add("POST", r"/api/v1/interview-cases", self.create_case, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)", self.get_case, **committee)
        router.add("DELETE", r"/api/v1/interview-cases/(?P<case_id>[^/]+)", self.delete_case, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/documents", self.list_documents, **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/documents", self.import_document, max_body=10 * 1024 * 1024, **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/documents/(?P<document_id>[^/]+)/confirm", self.confirm_document, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/question-set", self.get_question_set, **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/question-set", self.generate_question_set, **committee)
        router.add("PATCH", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/question-set", self.update_question_set, **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/question-set/approve", self.approve_question_set, **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/question-set/export", self.export_question_set, body_mode="none", **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/assessment-snapshots/import", self.import_assessment_snapshot, max_body=10 * 1024 * 1024, body_mode="binary", **committee)
        router.add("POST", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/ai/evaluate", self.evaluate_assessment, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/ai/evaluation", self.get_ai_evaluation, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/assessment-snapshots/current", self.get_assessment_snapshot, **committee)
        router.add("GET", r"/api/v1/interview-cases/(?P<case_id>[^/]+)/assessment-snapshots/(?P<snapshot_id>[^/]+)", self.get_assessment_snapshot, **committee)
        router.add("GET", r"/api/v1/tasks/(?P<task_id>[^/]+)", self.get_task, **committee)
        router.add("GET", r"/api/v1/settings", self.get_settings, **committee)
        router.add("PATCH", r"/api/v1/settings", self.update_settings, **committee)
        router.add("POST", r"/api/v1/backups", self.create_backup, **committee)
        router.add("POST", r"/api/v1/exports", self.create_export, **committee)

    def authenticate(self, request: Request) -> Response:
        session = self.security.authenticate_pin(_body(request).get("pin", ""))
        return _ok(request, {"committeeSession": session})

    def setup_pin(self, request: Request) -> Response:
        if self.security.is_pin_configured():
            raise ValidationError("Committee PIN is already configured")
        self.security.set_committee_pin(_body(request).get("pin", ""))
        return _ok(request, {"configured": True}, status=201)

    def lock(self, request: Request) -> Response:
        self.security.lock(request.context.get("committeeSession", ""))
        return _ok(request, {"locked": True})

    def list_jobs(self, request: Request) -> Response:
        items = self.cases.list_jobs(_query(request, "query"))
        return _ok(request, _page(items))

    def create_job(self, request: Request) -> Response:
        body = _body(request)
        job = self.cases.create_job(body.get("jobCode"), body.get("positionTitle"), body.get("targetLevel"))
        return _ok(request, {"job": job}, status=201)

    def list_candidates(self, request: Request) -> Response:
        return _ok(request, _page(self.cases.list_candidates(_query(request, "query"))))

    def create_candidate(self, request: Request) -> Response:
        body = _body(request)
        candidate = self.cases.create_candidate(body.get("candidateCode"), body.get("fullName"))
        return _ok(request, {"candidate": candidate}, status=201)

    def list_cases(self, request: Request) -> Response:
        return _ok(request, _page(self.cases.list_cases(_query(request, "status"))))

    def create_case(self, request: Request) -> Response:
        body = _body(request)
        case = self.cases.create_case(
            body.get("candidateId"), body.get("jobId"),
            scheduled_at=body.get("scheduledAt"),
            assessment_duration_seconds=body.get("assessmentDurationSeconds", 900),
            allow_incomplete_submit=body.get("allowIncompleteSubmit", True),
            auto_submit_on_expiry=body.get("autoSubmitOnExpiry", True),
            materials_policy=body.get("materialsPolicy", "NOT_SPECIFIED"),
            internet_policy=body.get("internetPolicy", "NOT_SPECIFIED"),
            tools_policy=body.get("toolsPolicy", "NOT_SPECIFIED"),
            committee_members=body.get("committeeMembers", []),
        )
        return _ok(request, {"case": case}, status=201)

    def get_case(self, request: Request) -> Response:
        case = self.cases.get_case(request.path_params["case_id"])
        return _ok(request, {"case": self.queries.case_overview(case)})

    def delete_case(self, request: Request) -> Response:
        body = _body(request)
        if body.get("confirmation") != "DELETE_CASE":
            raise ValidationError("Explicit case deletion confirmation is required")
        self.backups.backup_and_delete_case(
            request.path_params["case_id"],
            confirmation=body["confirmation"],
            reason=body.get("reason"),
        )
        return Response(status=204, body=None)

    def list_documents(self, request: Request) -> Response:
        return _ok(request, {"items": self.documents.list_for_case(request.path_params["case_id"])})

    def import_document(self, request: Request) -> Response:
        body = _body(request); case_id = request.path_params["case_id"]
        if body.get("sourceKind") == "MANUAL_TEXT":
            document = self.documents.import_manual_text(case_id, body.get("documentType"), body.get("text"))
        else:
            try:
                raw = base64.b64decode(body.get("contentBase64", ""), validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValidationError("contentBase64 is invalid") from error
            document = self.documents.import_file(case_id, body.get("documentType"), body.get("originalFilename", ""), body.get("mimeType", ""), raw)
        return _ok(request, {"document": document}, status=201)

    def confirm_document(self, request: Request) -> Response:
        body = _body(request)
        if body.get("confirmed") is not True:
            raise ValidationError("confirmed must be true")
        document = self.documents.confirm(request.path_params["document_id"], body.get("textSha256", ""))
        return _ok(request, {"document": document})

    def get_question_set(self, request: Request) -> Response:
        question_set = self.questions.get_for_case(request.path_params["case_id"])
        if question_set is None:
            raise ResourceNotFound("Question Set not found")
        return _ok(request, {"questionSet": question_set})

    def generate_question_set(self, request: Request) -> Response:
        body = _body(request)
        if body.get("operation", "GENERATE") == "MANUAL":
            question_set = self.questions.create_manual_draft(
                request.path_params["case_id"], body.get("questions", []),
                duration_seconds=body.get("durationSeconds", 900),
            )
            return _ok(request, {"questionSet": question_set}, status=201)
        task = self.question_generation.request(
            request.path_params["case_id"], idempotency_key=_idempotency(request, "questions"),
            question_policy=body.get("questionPolicy"),
        )
        self.submit_task(task["id"])
        return _ok(request, {"taskId": task["id"], "status": task["status"], "caseStatus": "QUESTIONS_GENERATING"}, status=202)

    def update_question_set(self, request: Request) -> Response:
        body = _body(request)
        return _ok(request, {"questionSet": self.questions.update_draft(body.get("questionSetId"), body.get("questions", []))})

    def approve_question_set(self, request: Request) -> Response:
        body = _body(request)
        if body.get("confirmation") != "APPROVE_QUESTION_SET":
            raise ValidationError("Explicit approval confirmation is required")
        return _ok(request, {"questionSet": self.questions.approve(body.get("questionSetId"), body.get("memberId")), "caseStatus": "QUESTIONS_APPROVED"})

    def export_question_set(self, request: Request) -> Response:
        exported = self.excel_assessments.export_question_set(request.path_params["case_id"])
        return Response(
            status=200,
            body=None,
            raw_body=exported.content,
            headers={
                "Content-Type": exported.content_type,
                "Content-Disposition": f'attachment; filename="{exported.filename}"',
            },
        )

    def import_assessment_snapshot(self, request: Request) -> Response:
        snapshot = self.excel_assessments.import_answers(
            request.path_params["case_id"],
            request.raw_body or b"",
            idempotency_key=_idempotency(request, "excel-import"),
        )
        return _ok(request, {"snapshot": snapshot}, status=201)

    def get_assessment(self, request: Request) -> Response:
        return _ok(request, {"attempt": self.assessments.get_for_case(request.path_params["case_id"])})

    def prepare_assessment(self, request: Request) -> Response:
        attempt = self.assessments.prepare(request.path_params["case_id"], _body(request).get("questionSetId"))
        return _ok(request, {"attempt": attempt}, status=201)

    def start_assessment(self, request: Request) -> Response:
        body = _body(request)
        attempt = self.assessments.start(request.path_params["case_id"], candidate_code_confirmed=body.get("candidateCodeConfirmed") is True, committee_authorized=body.get("committeePinVerified") is True)
        self.security.lock_all_committee_sessions()
        return _ok(request, {"attempt": attempt})

    def candidate_questions(self, request: Request) -> Response:
        return _ok(request, self.assessments.candidate_view(request.path_params["attempt_id"], request.context["candidateToken"]))

    def save_answer(self, request: Request) -> Response:
        body = _body(request)
        saved = self.assessments.save_answer(request.path_params["attempt_id"], request.path_params["question_id"], request.context["candidateToken"], text=body.get("text"), is_answered=body.get("isAnswered") is True, client_revision=body.get("clientRevision"))
        return _ok(request, saved)

    def submit_assessment(self, request: Request) -> Response:
        body = _body(request)
        if body.get("confirmation") != "SUBMIT_ASSESSMENT":
            raise ValidationError("Explicit submit confirmation is required")
        revisions = body.get("answerRevisions")
        if not isinstance(revisions, dict):
            raise ValidationError("answerRevisions is required for final submit")
        attempt = self.assessments.submit(
            request.path_params["attempt_id"],
            request.context["candidateToken"],
            expected_revisions=revisions,
            idempotency_key=_idempotency(request, "submit"),
        )
        return _ok(request, {"attempt": attempt})

    def evaluate_assessment(self, request: Request) -> Response:
        body = _body(request)
        snapshot_id = body.get("snapshotId")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValidationError("snapshotId is required")
        task = self.evaluations.request_snapshot(request.path_params["case_id"], snapshot_id, idempotency_key=_idempotency(request, "evaluation"), force_rerun=body.get("forceRerun") is True)
        self.submit_task(task["id"])
        return _ok(request, {"taskId": task["id"], "status": task["status"], "caseStatus": "AI_ANALYZING"}, status=202)

    def get_ai_evaluation(self, request: Request) -> Response:
        return _ok(request, {"result": self.evaluations.current_ai_result(request.path_params["case_id"])})

    def get_assessment_snapshot(self, request: Request) -> Response:
        return _ok(
            request,
            {"snapshot": self.excel_assessments.get_snapshot(
                request.path_params["case_id"], request.path_params.get("snapshot_id")
            )},
        )

    def get_task(self, request: Request) -> Response:
        task = self.tasks.get(request.path_params["task_id"])
        result = task.pop("result", None)
        safe_task = {key: task[key] for key in ("id", "taskType", "status", "assessmentSnapshotId", "createdAt", "startedAt", "finishedAt", "errorCode")}
        if safe_task["status"] == "COMPLETED" and safe_task["errorCode"] == "AI_MATERIALIZATION_FAILED":
            safe_task["status"] = "FAILED"
        if safe_task["status"] == "COMPLETED":
            case_status = (
                self.evaluations.refined_status(task["interviewCaseId"])
                if task.get("assessmentSnapshotId")
                else self.cases.get_case(task["interviewCaseId"])["status"]
            )
            materializing = (
                task["taskType"] == "GENERATE_QUESTIONS" and case_status == "QUESTIONS_GENERATING"
            ) or (
                task["taskType"] in {"EVALUATE_ASSESSMENT", "GENERATE_BRIEF"}
                and case_status == "AI_ANALYZING"
            )
            if materializing:
                safe_task["status"] = "RUNNING"
                safe_task["finishedAt"] = None
        safe_result = {"id": None, "resultType": None, "versionNo": None} if result is None else {key: result[key] for key in ("id", "resultType", "versionNo")}
        return _ok(request, {"task": safe_task, "result": safe_result})

    def get_brief(self, request: Request) -> Response:
        return _ok(request, {"brief": self.briefs.current(request.path_params["case_id"])})

    def create_brief(self, request: Request) -> Response:
        body = _body(request)
        brief = self.briefs.create_manual(request.path_params["case_id"], body.get("attemptId"), body.get("brief"), body.get("memberId"))
        return _ok(request, {"brief": brief, "caseStatus": "INTERVIEW_BRIEF_READY"}, status=201)

    def start_live(self, request: Request) -> Response:
        return _ok(request, self.interviews.start(request.path_params["case_id"], _body(request).get("memberId")))

    def list_live_records(self, request: Request) -> Response:
        return _ok(request, {"items": self.interviews.list_records(request.path_params["case_id"])})

    def record_live(self, request: Request) -> Response:
        body = _body(request)
        record = self.interviews.record(request.path_params["case_id"], sequence_no=body.get("sequenceNo"), committee_member_id=body.get("committeeMemberId"), asked_status=body.get("askedStatus"), live_notes=body.get("liveNotes"), score=body.get("score"), evidence_status=body.get("evidenceStatus"))
        return _ok(request, {"record": record}, status=201)

    def follow_up(self, request: Request) -> Response:
        task = self.interviews.request_follow_up(request.path_params["case_id"], idempotency_key=_idempotency(request, "follow-up"))
        self.submit_task(task["id"])
        return _ok(request, {"taskId": task["id"], "status": task["status"]}, status=202)

    def complete_live(self, request: Request) -> Response:
        body = _body(request)
        return _ok(request, self.interviews.complete(request.path_params["case_id"], body.get("memberId"), reason=body.get("reason")))

    def get_final_evaluation(self, request: Request) -> Response:
        return _ok(request, {"evaluation": self.evaluations.current_final_evaluation(request.path_params["case_id"])})

    def save_final_evaluation(self, request: Request) -> Response:
        body = _body(request)
        evaluation = self.evaluations.save_final_draft(request.path_params["case_id"], body, revision_reason=body.get("revisionReason"))
        return _ok(request, {"evaluation": evaluation})

    def finalize_evaluation(self, request: Request) -> Response:
        body = _body(request)
        evaluation = self.evaluations.finalize(body.get("evaluationId"), body.get("memberId"), confirmation=body.get("confirmation", ""))
        return _ok(request, {"evaluation": evaluation, "caseStatus": "EVALUATED"})

    def get_settings(self, request: Request) -> Response:
        return _ok(request, {"items": self.queries.settings(), "pinConfigured": self.security.is_pin_configured()})

    def update_settings(self, request: Request) -> Response:
        return _ok(request, {"items": self.queries.update_settings(_body(request).get("changes", []))})

    def create_backup(self, request: Request) -> Response:
        body = _body(request)
        backup = self.backups.create_backup(body.get("label", "manual"), include_documents=body.get("includeDocuments") is True)
        safe = {key: backup[key] for key in ("id", "status", "safePathSummary")}
        return _ok(request, {"backup": safe}, status=201)

    def create_export(self, request: Request) -> Response:
        body = _body(request)
        exported = self.backups.export_case(body.get("caseId"), include_documents=body.get("includeDocuments") is True)
        safe = {"id": exported["id"], "status": exported["status"], "safePathSummary": exported["path"].replace("\\", "/").rsplit("/", 1)[-1]}
        return _ok(request, {"export": safe}, status=201)


def _body(request: Request) -> dict[str, Any]:
    if not isinstance(request.json_body, dict):
        raise ValidationError("JSON request body must be an object")
    return request.json_body


def _ok(request: Request, data: Any, *, status: int = 200) -> Response:
    return success_response(data, request.request_id, status=status)


def _query(request: Request, name: str) -> str | None:
    values = request.query.get(name)
    return None if not values else values[0]


def _page(items: list[Any]) -> dict[str, Any]:
    return {"items": items, "page": 1, "pageSize": len(items), "total": len(items)}


def _idempotency(request: Request, operation: str) -> str:
    supplied = (
        request.headers.get("X-Idempotency-Key")
        or request.headers.get("Idempotency-Key")
    )
    return f"{operation}:{supplied or request.request_id or uuid.uuid4()}"
