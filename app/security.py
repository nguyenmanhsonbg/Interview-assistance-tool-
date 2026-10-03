from __future__ import annotations

import hashlib
import hmac
import secrets

from app.domain.errors import Unauthenticated


def generate_candidate_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_candidate_token(token: str, expected_hash: str | None) -> None:
    if not token or not expected_hash or not hmac.compare_digest(hash_token(token), expected_hash):
        raise Unauthenticated("Candidate session is invalid or expired")
