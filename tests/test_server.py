import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class ServerSmokeTests(unittest.TestCase):
    def setUp(self):
        from app.config import AppConfig
        from app.responses import success_response
        from app.router import Router
        from app.server import create_server

        self.temp_dir = tempfile.TemporaryDirectory()
        repo_root = Path(__file__).resolve().parents[1]
        self.config = AppConfig(
            host="127.0.0.1",
            port=0,
            data_directory=Path(self.temp_dir.name),
            web_directory=repo_root / "web",
            max_json_body=64,
            max_upload_body=256,
        )
        router = Router()
        router.add(
            "POST",
            r"/api/v1/test-json",
            lambda request: success_response(request.json_body, request.request_id),
        )
        self.server = create_server(self.config, router=router)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=body,
            headers=headers or {},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_health_uses_envelope_request_id_and_localhost_binding(self):
        status, headers, body = self.request("/api/v1/health")
        payload = json.loads(body)

        self.assertEqual("127.0.0.1", self.server.server_address[0])
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual("ok", payload["data"]["status"])
        self.assertEqual(headers["X-Request-Id"], payload["requestId"])

    def test_static_index_is_served_without_directory_listing(self):
        status, headers, body = self.request("/")

        self.assertEqual(200, status)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"ClawCV", body)
        missing_status, _, _ = self.request("/missing-file")
        self.assertEqual(404, missing_status)

    def test_invalid_json_and_body_limit_are_rejected_before_handler(self):
        invalid_status, _, invalid_body = self.request(
            "/api/v1/test-json",
            method="POST",
            body=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        large_status, _, large_body = self.request(
            "/api/v1/test-json",
            method="POST",
            body=b"x" * 65,
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(400, invalid_status)
        self.assertEqual("INVALID_JSON", json.loads(invalid_body)["error"]["code"])
        self.assertEqual(413, large_status)
        self.assertEqual("REQUEST_TOO_LARGE", json.loads(large_body)["error"]["code"])

    def test_api_404_and_405_are_json_errors(self):
        missing_status, _, missing_body = self.request("/api/v1/missing")
        method_status, _, method_body = self.request(
            "/api/v1/health", method="POST", body=b"{}",
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(404, missing_status)
        self.assertEqual("RESOURCE_NOT_FOUND", json.loads(missing_body)["error"]["code"])
        self.assertEqual(405, method_status)
        self.assertEqual("METHOD_NOT_ALLOWED", json.loads(method_body)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
