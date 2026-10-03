from __future__ import annotations

import json
import mimetypes
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.config import AppConfig
from app.responses import Response, error_response, success_response
from app.router import MethodNotAllowed, Request, RouteNotFound, Router


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; connect-src 'self'; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class ClawCVHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]):
        super().__init__(address, handler)
        self.shutdown_started = threading.Event()

    def shutdown(self) -> None:
        self.shutdown_started.set()
        super().shutdown()


def _health_handler(config: AppConfig):
    def handler(request: Request) -> Response:
        return success_response(
            {
                "status": "ok",
                "version": config.app_version,
                "database": "not-initialized",
                "aiConfigured": False,
            },
            request.request_id,
        )

    return handler


def create_server(config: AppConfig, *, router: Router | None = None) -> ClawCVHTTPServer:
    app_router = router or Router()
    app_router.add("GET", r"/api/v1/health", _health_handler(config))
    handler = _handler_factory(config, app_router)
    return ClawCVHTTPServer((config.host, config.port), handler)


def _handler_factory(config: AppConfig, router: Router) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "ClawCV"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self) -> None:
            request_id = self.headers.get("X-Request-Id") or str(uuid.uuid4())
            parsed = urlsplit(self.path)
            if not parsed.path.startswith("/api/v1/"):
                if self.command != "GET":
                    self._write_json(
                        error_response(
                            "METHOD_NOT_ALLOWED",
                            "Method not allowed",
                            request_id,
                            status=405,
                        ),
                        request_id,
                    )
                    return
                self._serve_static(parsed.path, request_id)
                return

            try:
                route, path_params = router.match(self.command, parsed.path)
            except MethodNotAllowed:
                self._write_json(
                    error_response(
                        "METHOD_NOT_ALLOWED", "Method not allowed", request_id, status=405
                    ),
                    request_id,
                )
                return
            except RouteNotFound:
                self._write_json(
                    error_response(
                        "RESOURCE_NOT_FOUND", "Resource not found", request_id, status=404
                    ),
                    request_id,
                )
                return

            body, failure = self._read_json_body(
                request_id, route.max_body or config.max_json_body
            )
            if failure is not None:
                self._write_json(failure, request_id)
                return
            request = Request(
                method=self.command,
                path=parsed.path,
                request_id=request_id,
                headers=self.headers,
                query=parse_qs(parsed.query, keep_blank_values=True),
                json_body=body,
                path_params=path_params,
            )
            try:
                response = route.handler(request)
            except Exception:
                response = error_response(
                    "INTERNAL_ERROR",
                    "The operation could not be completed",
                    request_id,
                    status=500,
                )
            self._write_json(response, request_id)

        def _read_json_body(
            self, request_id: str, maximum: int
        ) -> tuple[Any, Response | None]:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None or raw_length == "0":
                return None, None
            try:
                length = int(raw_length)
            except ValueError:
                return None, error_response(
                    "INVALID_JSON", "Invalid request body", request_id, status=400
                )
            if length < 0 or length > maximum:
                return None, error_response(
                    "REQUEST_TOO_LARGE", "Request body is too large", request_id, status=413
                )
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                return None, error_response(
                    "UNSUPPORTED_MEDIA_TYPE",
                    "Content-Type must be application/json",
                    request_id,
                    status=415,
                )
            try:
                decoded = self.rfile.read(length).decode("utf-8")
                return json.loads(decoded), None
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, error_response(
                    "INVALID_JSON", "Invalid JSON body", request_id, status=400
                )

        def _serve_static(self, path: str, request_id: str) -> None:
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            root = config.web_directory.resolve()
            candidate = (root / relative).resolve()
            if root not in candidate.parents or not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Request-Id", request_id)
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(content)

        def _write_json(self, response: Response, request_id: str) -> None:
            payload = b"" if response.body is None else json.dumps(
                response.body, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Request-Id", request_id)
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            if payload:
                self.wfile.write(payload)

    return RequestHandler


def run(config: AppConfig, *, open_browser: bool = True) -> None:
    config.ensure_directories()
    server = create_server(config)
    url = f"http://{config.host}:{server.server_address[1]}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
