from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from app.responses import Response


class RouteNotFound(LookupError):
    pass


class MethodNotAllowed(LookupError):
    pass


@dataclass(slots=True)
class Request:
    method: str
    path: str
    request_id: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, list[str]] = field(default_factory=dict)
    json_body: Any = None
    raw_body: bytes | None = None
    path_params: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Request], Response]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler
    access_mode: str = "LOCALHOST"
    max_body: int | None = None
    body_mode: str = "json"


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(
        self,
        method: str,
        pattern: str,
        handler: Handler,
        *,
        access_mode: str = "LOCALHOST",
        max_body: int | None = None,
        body_mode: str = "json",
    ) -> None:
        if body_mode not in {"json", "binary", "none"}:
            raise ValueError("Unsupported route body mode")
        compiled = re.compile(f"^(?:{pattern})$")
        self._routes.append(
            Route(method.upper(), compiled, handler, access_mode, max_body, body_mode)
        )

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]]:
        path_matches: list[tuple[Route, re.Match[str]]] = []
        for route in self._routes:
            match = route.pattern.fullmatch(path)
            if match:
                path_matches.append((route, match))
                if route.method == method.upper():
                    return route, match.groupdict()
        if path_matches:
            raise MethodNotAllowed(path)
        raise RouteNotFound(path)

    def dispatch(self, request: Request) -> Response:
        route, path_params = self.match(request.method, request.path)
        request.path_params = path_params
        return route.handler(request)
