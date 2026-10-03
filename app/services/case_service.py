from __future__ import annotations

import uuid
from typing import Any

from app.database import Database
from app.domain.errors import ResourceNotFound, ValidationError
from app.domain.rules import require_text, require_transition
from app.repositories.audit import append_audit
from app.repositories.candidates import CandidateRepository
from app.repositories.interview_cases import InterviewCaseRepository
from app.repositories.jobs import JobRepository


class CaseService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.jobs = JobRepository(database)
        self.candidates = CandidateRepository(database)
        self.cases = InterviewCaseRepository(database)

    def create_job(
        self, job_code: str | None, position_title: str, target_level: str
    ) -> dict[str, Any]:
        position_title = require_text(position_title, "positionTitle")
        target_level = require_text(target_level, "targetLevel")
        normalized_code = job_code.strip() if isinstance(job_code, str) and job_code.strip() else None
        job_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            self.jobs.insert(connection, job_id, normalized_code, position_title, target_level)
        row = self.jobs.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return _job_dict(row)

    def create_candidate(self, candidate_code: str, full_name: str) -> dict[str, Any]:
        candidate_code = require_text(candidate_code, "candidateCode")
        full_name = require_text(full_name, "fullName")
        candidate_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            self.candidates.insert(connection, candidate_id, candidate_code, full_name)
        row = self.candidates.query_one("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
        return _candidate_dict(row)

    def list_jobs(self, query: str | None = None) -> list[dict[str, Any]]:
        return [_job_dict(row) for row in self.jobs.list(query)]

    def list_candidates(self, query: str | None = None) -> list[dict[str, Any]]:
        return [_candidate_dict(row) for row in self.candidates.list(query)]

    def create_case(
        self,
        candidate_id: str,
        job_id: str,
        *,
        scheduled_at: str | None = None,
        assessment_duration_seconds: int = 900,
        allow_incomplete_submit: bool = True,
        auto_submit_on_expiry: bool = True,
        materials_policy: str = "NOT_SPECIFIED",
        internet_policy: str = "NOT_SPECIFIED",
        tools_policy: str = "NOT_SPECIFIED",
        committee_members: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if assessment_duration_seconds <= 0:
            raise ValidationError("assessmentDurationSeconds must be positive")
        normalized_members: list[dict[str, str]] = []
        for member in committee_members or []:
            if member.get("role", "MEMBER") not in {"MEMBER", "LEAD"}:
                raise ValidationError("Committee member role must be MEMBER or LEAD")
            normalized_members.append(
                {
                    "displayName": require_text(member.get("displayName"), "displayName"),
                    "role": member.get("role", "MEMBER"),
                }
            )
        case_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            self.cases.insert(
                connection,
                case_id,
                candidate_id,
                job_id,
                scheduled_at=scheduled_at,
                duration_seconds=assessment_duration_seconds,
                allow_incomplete_submit=allow_incomplete_submit,
                auto_submit_on_expiry=auto_submit_on_expiry,
                materials_policy=require_text(materials_policy, "materialsPolicy"),
                internet_policy=require_text(internet_policy, "internetPolicy"),
                tools_policy=require_text(tools_policy, "toolsPolicy"),
                committee_members=normalized_members,
            )
        return self.cases.get(case_id)

    def get_case(self, case_id: str) -> dict[str, Any]:
        return self.cases.get(case_id)

    def list_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.cases.list(status)

    def cancel_case(self, case_id: str, reason: str) -> dict[str, Any]:
        require_text(reason, "reason")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM interview_cases WHERE id = ?", (case_id,)
            ).fetchone()
            if row is None:
                raise ResourceNotFound("Interview case not found")
            require_transition(
                row["status"],
                {"DRAFT", "DOCUMENTS_READY", "QUESTIONS_GENERATED", "READY_FOR_ASSESSMENT"},
                "CANCELLED",
            )
            connection.execute(
                "UPDATE interview_cases SET status='CANCELLED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (case_id,),
            )
            append_audit(
                connection,
                actor_type="COMMITTEE",
                action="CASE_CANCELLED",
                entity_type="INTERVIEW_CASE",
                entity_id=case_id,
                metadata={"reasonProvided": True},
            )
        return self.cases.get(case_id)


def _job_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"], "jobCode": row["job_code"],
        "positionTitle": row["position_title"], "targetLevel": row["target_level"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _candidate_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"], "candidateCode": row["candidate_code"],
        "fullName": row["full_name"], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
