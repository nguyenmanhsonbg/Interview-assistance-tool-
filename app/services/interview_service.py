from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path
from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound, StateConflict, ValidationError
from app.repositories.audit import append_audit
from app.repositories.evaluations import EvaluationRepository
from app.ai.provider import AIProvider
from app.ai.redaction import sanitize_structure, sanitize_text
from app.ai.schemas import SchemaRegistry
from app.services.ai_task_service import AITaskService


_EVIDENCE_STATUSES = {
    "VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "CONFLICTING",
    "NOT_MET", "NOT_ASSESSED",
}


class InterviewService:
    def __init__(
        self,
        database: Database,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.database = database
        self.provider_name = provider_name
        self.model_name = model_name
        self.repository = EvaluationRepository(database)
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        self.tasks = AITaskService(database, SchemaRegistry(schema_root))

    def start(self, case_id: str, member_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            case = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] == "LIVE_INTERVIEW_IN_PROGRESS":
                return {"caseStatus": case["status"]}
            if case["status"] != "INTERVIEW_BRIEF_READY":
                raise StateConflict("Case is not ready for a live interview")
            self._require_member(connection, case_id, member_id)
            brief_row = connection.execute(
                "SELECT id, brief_json FROM interview_briefs WHERE interview_case_id=? AND is_current=1",
                (case_id,),
            ).fetchone()
            if brief_row is None:
                raise StateConflict("Current Interview Brief is required")
            brief = json.loads(brief_row["brief_json"])
            questions = list(brief.get("requiredLiveQuestions", [])) + list(brief.get("additionalLiveQuestions", []))
            for sequence, question in enumerate(questions, start=1):
                connection.execute(
                    """INSERT INTO live_interview_records(
                        id, interview_case_id, interview_brief_id, sequence_no,
                        question_text, source_kind, asked_status
                    ) VALUES (?, ?, ?, ?, ?, 'BRIEF_RECOMMENDED', 'PLANNED')""",
                    (str(uuid.uuid4()), case_id, brief_row["id"], sequence, question),
                )
            connection.execute(
                "UPDATE interview_cases SET status='LIVE_INTERVIEW_IN_PROGRESS', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (case_id,),
            )
            append_audit(connection, actor_type="COMMITTEE", actor_ref_id=member_id,
                action="LIVE_INTERVIEW_STARTED", entity_type="INTERVIEW_CASE", entity_id=case_id,
                metadata={"plannedQuestionCount": len(questions)})
        return {"caseStatus": "LIVE_INTERVIEW_IN_PROGRESS"}

    def record(self, case_id: str, *, sequence_no: int, committee_member_id: str, asked_status: str, live_notes: str | None, score: int | None, evidence_status: str | None) -> dict[str, Any]:
        if asked_status not in {"ASKED", "SKIPPED"}:
            raise ValidationError("askedStatus must be ASKED or SKIPPED")
        if score is not None and (not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 4):
            raise ValidationError("score must be null or an integer from 0 to 4")
        if evidence_status is not None and evidence_status not in _EVIDENCE_STATUSES:
            raise ValidationError("Unsupported evidenceStatus")
        if asked_status == "SKIPPED" and (score is not None or evidence_status not in {None, "NOT_ASSESSED"}):
            raise ValidationError("Skipped questions cannot receive a score")
        with self.database.transaction() as connection:
            case = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] != "LIVE_INTERVIEW_IN_PROGRESS":
                raise StateConflict("Live interview is not in progress")
            self._require_member(connection, case_id, committee_member_id)
            record = connection.execute(
                "SELECT id, asked_status FROM live_interview_records WHERE interview_case_id=? AND sequence_no=?",
                (case_id, sequence_no),
            ).fetchone()
            if record is None:
                raise ResourceNotFound("Live interview sequence was not planned")
            connection.execute(
                """UPDATE live_interview_records SET committee_member_id=?, asked_status=?,
                   live_notes=?, score=?, evidence_status=?,
                   asked_at=CASE WHEN ?='ASKED' THEN COALESCE(asked_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')) ELSE asked_at END,
                   completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (committee_member_id, asked_status, live_notes, score, evidence_status, asked_status, record["id"]),
            )
            append_audit(connection, actor_type="COMMITTEE", actor_ref_id=committee_member_id,
                action="LIVE_QUESTION_SKIPPED" if asked_status == "SKIPPED" else "LIVE_QUESTION_RECORDED",
                entity_type="LIVE_INTERVIEW_RECORD", entity_id=record["id"],
                metadata={"sequenceNo": sequence_no, "previousStatus": record["asked_status"], "evidenceStatus": evidence_status})
        return self.repository.get_live_record(case_id, sequence_no)

    def complete(self, case_id: str, member_id: str, *, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError("Completion reason is required")
        with self.database.transaction() as connection:
            case = connection.execute("SELECT status FROM interview_cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ResourceNotFound("Interview case not found")
            if case["status"] == "LIVE_INTERVIEW_COMPLETED":
                return {"caseStatus": case["status"]}
            if case["status"] != "LIVE_INTERVIEW_IN_PROGRESS":
                raise StateConflict("Live interview is not in progress")
            self._require_member(connection, case_id, member_id)
            planned = connection.execute(
                "SELECT COUNT(*) FROM live_interview_records WHERE interview_case_id=? AND asked_status='PLANNED'",
                (case_id,),
            ).fetchone()[0]
            if planned:
                raise StateConflict("All planned live questions must be asked or skipped")
            connection.execute(
                "UPDATE interview_cases SET status='LIVE_INTERVIEW_COMPLETED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (case_id,),
            )
            append_audit(connection, actor_type="COMMITTEE", actor_ref_id=member_id,
                action="LIVE_INTERVIEW_COMPLETED", entity_type="INTERVIEW_CASE", entity_id=case_id,
                metadata={"reason": reason.strip()})
        return {"caseStatus": "LIVE_INTERVIEW_COMPLETED"}

    def list_records(self, case_id: str) -> list[dict[str, Any]]:
        return self.repository.list_live_records(case_id)

    def request_follow_up(self, case_id: str, *, idempotency_key: str) -> dict[str, Any]:
        records = self.list_records(case_id)
        with self.database.connection() as connection:
            case = connection.execute(
                """SELECT ic.status, c.full_name FROM interview_cases ic
                   JOIN candidates c ON c.id=ic.candidate_id WHERE ic.id=?""", (case_id,)
            ).fetchone()
            brief = connection.execute(
                "SELECT id FROM interview_briefs WHERE interview_case_id=? AND is_current=1",
                (case_id,),
            ).fetchone()
        if case is None:
            raise ResourceNotFound("Interview case not found")
        if case["status"] != "LIVE_INTERVIEW_IN_PROGRESS" or brief is None:
            raise StateConflict("Follow-up is only available during a live interview")
        manifest = {
            "schemaVersion": "ai-task-manifest.v1",
            "interviewCaseId": case_id,
            "interviewBriefId": brief["id"],
            "liveRecords": [
                {
                    "id": record["id"], "sequenceNo": record["sequenceNo"],
                    "askedStatus": record["askedStatus"],
                    "contentHash": hashlib.sha256(
                        (record["liveNotes"] or "").encode("utf-8")
                    ).hexdigest(),
                }
                for record in records
            ],
            "redactionPolicy": "SANITIZED_TEXT_ONLY",
        }
        fingerprint = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.tasks.enqueue(
            case_id, "SUGGEST_FOLLOW_UP", input_manifest=manifest,
            input_fingerprint=fingerprint, idempotency_key=idempotency_key,
            provider=self.provider_name, model=self.model_name,
        )

    def process_follow_up(self, task_id: str, provider: AIProvider) -> dict[str, Any]:
        task = self.tasks.repository.get(task_id)
        if task["taskType"] != "SUGGEST_FOLLOW_UP":
            raise StateConflict("Task is not a follow-up request")
        with self.database.connection() as connection:
            brief_row = connection.execute(
                """SELECT ib.brief_json, c.full_name FROM interview_briefs ib
                   JOIN interview_cases ic ON ic.id=ib.interview_case_id
                   JOIN candidates c ON c.id=ic.candidate_id WHERE ib.id=?""",
                (task["inputManifest"]["interviewBriefId"],),
            ).fetchone()
        if brief_row is None:
            raise ResourceNotFound("Interview Brief not found")
        records = self.list_records(task["interviewCaseId"])
        known_names = (brief_row["full_name"],)
        asked_questions = [
            record["questionText"] for record in records
            if record["askedStatus"] in {"ASKED", "SKIPPED"}
        ]
        payload = {
            "schemaVersion": "ai.input.v1", "operation": "FOLLOW_UP",
            "interviewBrief": sanitize_structure(
                json.loads(brief_row["brief_json"]), known_names=known_names
            ),
            "liveRecords": [
                {
                    "sequenceNo": record["sequenceNo"],
                    "questionText": sanitize_text(
                        record["questionText"], known_names=known_names
                    ),
                    "askedStatus": record["askedStatus"],
                    "liveNotes": sanitize_text(
                        record["liveNotes"] or "", known_names=known_names
                    ),
                    "score": record["score"],
                    "evidenceStatus": record["evidenceStatus"],
                }
                for record in records
            ],
            "remainingCompetencies": [],
        }
        return self.tasks.process(
            task_id, provider, payload_override=payload,
            context_override={"askedQuestions": asked_questions},
        )

    @staticmethod
    def _require_member(connection, case_id: str, member_id: str) -> None:
        member = connection.execute(
            "SELECT 1 FROM interview_case_committee_members WHERE id=? AND interview_case_id=?",
            (member_id, case_id),
        ).fetchone()
        if member is None:
            raise ValidationError("Committee member does not belong to this case")
