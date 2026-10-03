from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any


def append_audit(
    connection: sqlite3.Connection,
    *,
    actor_type: str,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_ref_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    audit_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO audit_logs(
            id, actor_type, actor_ref_id, action, entity_type, entity_id,
            request_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id,
            actor_type,
            actor_ref_id,
            action,
            entity_type,
            entity_id,
            request_id,
            json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return audit_id
