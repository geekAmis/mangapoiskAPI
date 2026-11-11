from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .config import Settings
from .errors import UnauthorizedError

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
    except Exception:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def create_access_token(
    settings: Settings,
    *,
    subject: str,
    role: str = "user",
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    expires_in = (expires_minutes or settings.access_token_minutes) * 60
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid access token", code="invalid_token") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Wrong token type", code="invalid_token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_days)


def constant_time_compare(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
