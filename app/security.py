from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from app.database import Database
from app.domain.errors import ForbiddenCapability, Unauthenticated, ValidationError


def generate_candidate_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_candidate_token(token: str, expected_hash: str | None) -> None:
    if not token or not expected_hash or not hmac.compare_digest(hash_token(token), expected_hash):
        raise Unauthenticated("Candidate session is invalid or expired")


class LocalSecurity:
    """Process-local capabilities plus a persisted salted Committee PIN hash."""

    def __init__(
        self,
        database: Database | None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        session_idle_seconds: int = 30 * 60,
        pbkdf2_iterations: int = 310_000,
    ) -> None:
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.session_idle_seconds = session_idle_seconds
        self.pbkdf2_iterations = pbkdf2_iterations
        self.startup_token = secrets.token_urlsafe(32)
        self._sessions: dict[str, datetime] = {}
        self._failed_pin_attempts = 0
        self._session_epoch = 0
        self._session_lock = threading.RLock()

    def set_committee_pin(self, pin: str) -> None:
        if not isinstance(pin, str) or not pin.isdigit() or not 4 <= len(pin) <= 12:
            raise ValidationError("Committee PIN must contain 4 to 12 digits")
        if self.database is None:
            raise RuntimeError("PIN persistence requires a database")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), salt, self.pbkdf2_iterations
        )
        protected = json.dumps(
            {
                "algorithm": "pbkdf2_sha256",
                "iterations": self.pbkdf2_iterations,
                "salt": salt.hex(),
                "digest": digest.hex(),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO app_settings(
                    key, value_type, value_text, protected_value, is_sensitive
                ) VALUES ('committee_pin', 'SECRET_REF', NULL, ?, 1)
                ON CONFLICT(key) DO UPDATE SET value_type='SECRET_REF', value_text=NULL,
                    protected_value=excluded.protected_value, is_sensitive=1,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                (protected,),
            )
        with self._session_lock:
            self._session_epoch += 1
            self._sessions.clear()
            self._failed_pin_attempts = 0

    def authenticate_pin(self, pin: str) -> str:
        with self._session_lock:
            authentication_epoch = self._session_epoch
        record = self._pin_record()
        salt = bytes.fromhex(record["salt"])
        actual = hashlib.pbkdf2_hmac(
            "sha256", str(pin).encode("utf-8"), salt, int(record["iterations"])
        )
        if not hmac.compare_digest(actual, bytes.fromhex(record["digest"])):
            with self._session_lock:
                self._failed_pin_attempts += 1
                delay = min(0.1 * (2 ** (self._failed_pin_attempts - 1)), 2.0)
            self.sleep(delay)
            raise Unauthenticated("Committee PIN is invalid")
        with self._session_lock:
            if authentication_epoch != self._session_epoch:
                raise Unauthenticated("Committee session was reset")
            self._failed_pin_attempts = 0
            session = secrets.token_urlsafe(32)
            self._sessions[hash_token(session)] = self.clock()
        return session

    def verify_committee_session(self, session: str) -> None:
        key = hash_token(session) if session else ""
        with self._session_lock:
            last_activity = self._sessions.get(key)
            now = self.clock()
            if last_activity is None or now - last_activity > timedelta(seconds=self.session_idle_seconds):
                self._sessions.pop(key, None)
                raise Unauthenticated("Committee session is invalid or expired")
            self._sessions[key] = now

    def lock(self, session: str) -> None:
        if session:
            with self._session_lock:
                self._sessions.pop(hash_token(session), None)

    def lock_all_committee_sessions(self) -> None:
        with self._session_lock:
            self._session_epoch += 1
            self._sessions.clear()

    def is_pin_configured(self) -> bool:
        if self.database is None:
            return False
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT 1 FROM app_settings WHERE key='committee_pin' AND is_sensitive=1"
            ).fetchone() is not None

    def authorize(self, access_mode: str, method: str, headers: Mapping[str, str]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        mutation = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        if access_mode == "LOCALHOST":
            return context
        if mutation:
            supplied = headers.get("X-Startup-Token", "")
            if not hmac.compare_digest(supplied, self.startup_token):
                raise Unauthenticated("Startup capability is invalid")
        if access_mode == "STARTUP":
            return context
        if access_mode == "COMMITTEE":
            session = headers.get("X-Committee-Session", "")
            self.verify_committee_session(session)
            context["committeeSession"] = session
            return context
        if access_mode == "CANDIDATE":
            token = headers.get("X-Candidate-Token", "")
            if not token:
                raise Unauthenticated("Candidate session is invalid or expired")
            context["candidateToken"] = token
            return context
        raise ForbiddenCapability("Route capability is not available")

    def _pin_record(self) -> dict[str, Any]:
        if self.database is None:
            raise Unauthenticated("Committee PIN is not configured")
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT protected_value FROM app_settings WHERE key='committee_pin' AND is_sensitive=1"
            ).fetchone()
        if row is None:
            raise Unauthenticated("Committee PIN is not configured")
        try:
            return json.loads(bytes(row["protected_value"]).decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            raise Unauthenticated("Committee PIN configuration is invalid") from error
