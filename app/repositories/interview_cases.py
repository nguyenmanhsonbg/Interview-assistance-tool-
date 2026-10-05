from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.domain.errors import ResourceNotFound
from app.repositories.audit import append_audit
from app.repositories.base import RepositoryBase


class InterviewCaseRepository(RepositoryBase):
    def insert(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        candidate_id: str,
        job_id: str,
        *,
        scheduled_at: str | None,
        duration_seconds: int,
        allow_incomplete_submit: bool,
        auto_submit_on_expiry: bool,
        materials_policy: str,
        internet_policy: str,
        tools_policy: str,
        committee_members: list[dict[str, str]],
    ) -> None:
        connection.execute(
            """INSERT INTO interview_cases(
                id, candidate_id, job_id, scheduled_at, assessment_duration_seconds,
                allow_incomplete_submit, auto_submit_on_expiry, materials_policy,
                internet_policy, tools_policy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                case_id, candidate_id, job_id, scheduled_at, duration_seconds,
                int(allow_incomplete_submit), int(auto_submit_on_expiry),
                materials_policy, internet_policy, tools_policy,
            ),
        )
        for order, member in enumerate(committee_members, start=1):
            connection.execute(
                """INSERT INTO interview_case_committee_members(
                    id, interview_case_id, display_name, role, display_order
                ) VALUES (?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), case_id, member["displayName"],
                    member.get("role", "MEMBER"), order,
                ),
            )
        append_audit(
            connection,
            actor_type="COMMITTEE",
            action="CASE_CREATED",
            entity_type="INTERVIEW_CASE",
            entity_id=case_id,
            metadata={"committeeMemberCount": len(committee_members)},
        )

    def get(self, case_id: str) -> dict[str, Any]:
        row = self.query_one(
            """SELECT ic.*, c.candidate_code, c.full_name,
                      j.job_code, j.position_title, j.target_level
               FROM interview_cases ic
               JOIN candidates c ON c.id = ic.candidate_id
               JOIN jobs j ON j.id = ic.job_id
               WHERE ic.id = ?""",
            (case_id,),
        )
        if row is None:
            raise ResourceNotFound("Interview case not found")
        members = self.query_all(
            """SELECT id, display_name, role, display_order
               FROM interview_case_committee_members
               WHERE interview_case_id = ? ORDER BY display_order""",
            (case_id,),
        )
        return _case_dict(row, members)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT ic.*, c.candidate_code, c.full_name,
                        j.job_code, j.position_title, j.target_level
                 FROM interview_cases ic
                 JOIN candidates c ON c.id = ic.candidate_id
                 JOIN jobs j ON j.id = ic.job_id"""
        parameters: tuple[str, ...] = ()
        if status:
            sql += " WHERE ic.status = ?"
            parameters = (status,)
        sql += " ORDER BY ic.scheduled_at, ic.created_at DESC"
        return [_case_dict(row, []) for row in self.query_all(sql, parameters)]


def _case_dict(row: sqlite3.Row, members: list[sqlite3.Row]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "candidateId": row["candidate_id"],
        "jobId": row["job_id"],
        "status": row["status"],
        "refinedFlowStatus": row["refined_flow_status"] or row["status"],
        "scheduledAt": row["scheduled_at"],
        "assessmentDurationSeconds": row["assessment_duration_seconds"],
        "allowIncompleteSubmit": bool(row["allow_incomplete_submit"]),
        "autoSubmitOnExpiry": bool(row["auto_submit_on_expiry"]),
        "materialsPolicy": row["materials_policy"],
        "internetPolicy": row["internet_policy"],
        "toolsPolicy": row["tools_policy"],
        "candidate": {
            "id": row["candidate_id"],
            "candidateCode": row["candidate_code"],
            "fullName": row["full_name"],
        },
        "job": {
            "id": row["job_id"],
            "jobCode": row["job_code"],
            "positionTitle": row["position_title"],
            "targetLevel": row["target_level"],
        },
        "committeeMembers": [
            {
                "id": member["id"],
                "displayName": member["display_name"],
                "role": member["role"],
                "displayOrder": member["display_order"],
            }
            for member in members
        ],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
