from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_access_token
from .config import Settings, get_settings
from .errors import ForbiddenError, UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class UserClaims:
    id: str
    role: str
    raw: dict


def _claims_from_token(token: str, settings: Settings) -> UserClaims:
    payload = decode_access_token(settings, token)
    return UserClaims(id=str(payload["sub"]), role=str(payload.get("role", "user")), raw=payload)


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Authentication required", code="missing_token")
    return _claims_from_token(credentials.credentials, settings)


async def optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserClaims | None:
    if credentials is None:
        return None
    try:
        return _claims_from_token(credentials.credentials, settings)
    except UnauthorizedError:
        return None


async def require_admin(user: Annotated[UserClaims, Depends(require_user)]) -> UserClaims:
    if user.role not in {"admin", "owner"}:
        raise ForbiddenError("Administrator access required", code="admin_required")
    return user


async def require_internal_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    from .auth import constant_time_compare

    if not x_internal_token or not constant_time_compare(x_internal_token, settings.internal_token):
        raise UnauthorizedError("Invalid internal token", code="invalid_internal_token")
