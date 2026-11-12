from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, Header
from manga_common.errors import ForbiddenError, UnauthorizedError

BLOCKED_ROLES = frozenset({"banned", "blocked", "deleted"})
MODERATOR_ROLES = frozenset({"admin", "owner", "moderator"})
_USER_NAME_MAX_LENGTH = 64
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_user_name(value: str | None) -> str:
    """Turn a forwarded display name into a safe single-line snapshot."""

    name = _CONTROL_CHARS.sub("", unquote(value or ""))
    name = " ".join(name.split())
    return (name or "Пользователь")[:_USER_NAME_MAX_LENGTH]


@dataclass(slots=True, frozen=True)
class CommentUser:
    id: uuid.UUID
    name: str
    role: str = "user"

    @property
    def is_moderator(self) -> bool:
        return self.role in MODERATOR_ROLES


def _parse_user(
    x_user_id: str | None,
    x_user_name: str | None,
    x_user_role: str | None,
) -> CommentUser | None:
    raw_id = (x_user_id or "").strip()
    if not raw_id:
        return None
    try:
        user_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    role = (x_user_role or "user").strip().lower() or "user"
    return CommentUser(id=user_id, name=clean_user_name(x_user_name), role=role)


async def require_comment_user(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_name: Annotated[str | None, Header(alias="X-User-Name")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
) -> CommentUser:
    """Read the authenticated identity forwarded by the gateway.

    The comments service never verifies a JWT itself.  Only the gateway may
    call it, protected by ``X-Internal-Token``; the gateway is responsible for
    populating these headers from verified claims.
    """

    user = _parse_user(x_user_id, x_user_name, x_user_role)
    if user is None:
        raise UnauthorizedError("Требуется авторизация", code="missing_user")
    if user.role in BLOCKED_ROLES:
        raise ForbiddenError("Учётная запись заблокирована", code="user_blocked")
    return user


async def optional_comment_user(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_name: Annotated[str | None, Header(alias="X-User-Name")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
) -> CommentUser | None:
    """Same as :func:`require_comment_user`, but anonymous reads are allowed."""

    return _parse_user(x_user_id, x_user_name, x_user_role)


async def require_moderator(
    user: Annotated[CommentUser, Depends(require_comment_user)],
) -> CommentUser:
    if not user.is_moderator:
        raise ForbiddenError("Требуются права модератора", code="moderator_required")
    return user
