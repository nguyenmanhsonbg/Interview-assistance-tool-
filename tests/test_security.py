import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.support import MigratedDatabaseFixture


class SecurityUnitTests(MigratedDatabaseFixture, unittest.TestCase):
    def test_pin_hash_rate_limit_session_and_expiry(self):
        from app.domain.errors import Unauthenticated
        from app.security import LocalSecurity

        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        delays = []
        security = LocalSecurity(
            self.database, clock=lambda: now[0], sleep=delays.append,
            session_idle_seconds=60, pbkdf2_iterations=10_000,
        )
        security.set_committee_pin("482916")
        with self.database.connection() as connection:
            stored = connection.execute(
                "SELECT value_text, protected_value FROM app_settings WHERE key='committee_pin'"
            ).fetchone()
        self.assertIsNone(stored["value_text"])
        self.assertNotIn(b"482916", stored["protected_value"])
        with self.assertRaises(Unauthenticated):
            security.authenticate_pin("wrong")
        self.assertTrue(delays)
        session = security.authenticate_pin("482916")
        security.verify_committee_session(session)
        now[0] += timedelta(seconds=61)
        with self.assertRaises(Unauthenticated):
            security.verify_committee_session(session)


class SecurityHTTPTests(unittest.TestCase):
    def setUp(self):
        from app.config import AppConfig
        from app.database import Database
        from app.migrations import MigrationRunner
        from app.responses import success_response
        from app.router import Router
        from app.security import LocalSecurity
        from app.server import create_server

        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        database = Database(root / "database" / "test.db")
        MigrationRunner(database, Path(__file__).resolve().parents[1] / "migrations").apply_all()
        self.security = LocalSecurity(database, pbkdf2_iterations=10_000)
        self.security.set_committee_pin("123456")
        self.session = self.security.authenticate_pin("123456")
        config = AppConfig(port=0, data_directory=root, web_directory=Path(__file__).resolve().parents[1] / "web")
        router = Router()
        router.add(
            "POST", r"/api/v1/committee-only",
            lambda request: success_response({"allowed": True}, request.request_id),
            access_mode="COMMITTEE",
        )
        self.server = create_server(config, router=router, security=self.security)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.temp.cleanup()

    def request(self, headers):
        request = urllib.request.Request(
            self.base + "/api/v1/committee-only", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_host_startup_token_and_committee_capability_are_enforced(self):
        status, payload = self.request({"Host": "attacker.invalid"})
        self.assertEqual(400, status)
        self.assertEqual("INVALID_HOST", payload["error"]["code"])
        status, payload = self.request({})
        self.assertEqual(401, status)
        status, payload = self.request({
            "X-Startup-Token": self.security.startup_token,
            "X-Committee-Session": self.session,
        })
        self.assertEqual(200, status)
        self.assertTrue(payload["data"]["allowed"])


if __name__ == "__main__":
    unittest.main()
