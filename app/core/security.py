from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, ValueError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def digest_token(token: str, secret: str | bytes | None = None) -> str:
    raw = token.encode("utf-8")
    if secret:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        return hmac.new(key, raw, hashlib.sha256).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def is_expired(value: datetime | None) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= utcnow()


def constant_time_secret_match(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(expected.encode(), supplied.encode())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def utcnow() -> datetime:
    return datetime.now(UTC)


def expires_in(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)
