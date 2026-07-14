"""JWT access / refresh token helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from jose import JWTError, jwt

ACCESS_COOKIE = "tgfw_access"
REFRESH_COOKIE = "tgfw_refresh"


def create_access_token(
    *,
    secret_key: str,
    subject: str,
    role: str,
    expires_minutes: int,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if extra:
        payload.update(extra)
    return cast(str, jwt.encode(payload, secret_key, algorithm="HS256"))


def create_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], jwt.decode(token, secret_key, algorithms=["HS256"]))
    if payload.get("type") != "access":
        msg = "invalid token type"
        raise JWTError(msg)
    return payload
