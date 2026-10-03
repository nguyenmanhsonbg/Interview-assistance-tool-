from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Response:
    status: int
    body: dict[str, Any] | None
    headers: dict[str, str] = field(default_factory=dict)


def success_response(
    data: Any, request_id: str, *, status: int = 200
) -> Response:
    return Response(
        status=status,
        body={"success": True, "data": data, "requestId": request_id},
    )


def error_response(
    code: str,
    message: str,
    request_id: str,
    *,
    status: int,
    details: dict[str, Any] | None = None,
) -> Response:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return Response(
        status=status,
        body={"success": False, "error": error, "requestId": request_id},
    )
