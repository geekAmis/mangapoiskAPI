from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from manga_common.errors import ValidationError
from manga_common.schemas import OkResponse
from manga_common.security import UserClaims, require_user
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/v1", tags=["notifications"])


def comments(request: Request):
    return request.app.state.comments


def notifier(request: Request):
    return request.app.state.notifier


def _headers(user: UserClaims) -> dict[str, str]:
    return {"X-User-Id": user.id, "X-User-Role": user.role}


class FollowRequest(BaseModel):
    manga_id: uuid.UUID
    manga_title: str = Field(min_length=1, max_length=255)
    poster_url: str | None = Field(default=None, max_length=2048)
    source: str | None = Field(default=None, max_length=64)

    @field_validator("manga_title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        return value.strip()


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=64)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class NotificationSettingsIn(BaseModel):
    in_app_enabled: bool = True
    web_push_enabled: bool = True
    max_pushes_per_hour: int = Field(default=5, ge=1, le=60)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)


@router.get("/notifications/follows")
async def list_follows(
    request: Request, user: UserClaims = Depends(require_user)
) -> Any:
    return await comments(request).follows(_headers(user))


@router.post("/notifications/follows")
async def follow_title(
    request: Request,
    payload: FollowRequest,
    user: UserClaims = Depends(require_user),
) -> Any:
    variant_ids: list[str] = []
    try:
        variants = await request.app.state.catalog.variants(str(payload.manga_id))
        variant_ids = [str(item.id) for item in variants.items]
    except Exception:
        # Follow still works if the catalogue is temporarily unavailable; the
        # canonical id is always added server-side by the comments service.
        variant_ids = []
    body = {
        "manga_id": str(payload.manga_id),
        "manga_title": payload.manga_title,
        "poster_url": payload.poster_url,
        "source": payload.source,
        "variant_ids": variant_ids,
    }
    return await comments(request).follow(body, _headers(user))


@router.get("/notifications/follows/{manga_id}")
async def follow_status(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> Any:
    return await comments(request).follow_status(str(manga_id), _headers(user))


@router.delete("/notifications/follows/{manga_id}", response_model=OkResponse)
async def unfollow_title(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> OkResponse:
    await comments(request).unfollow(str(manga_id), _headers(user))
    return OkResponse(message="Вы отписались от новых глав")


@router.get("/notifications/settings")
async def get_notification_settings(
    request: Request, user: UserClaims = Depends(require_user)
) -> Any:
    return await comments(request).notification_settings(_headers(user))


@router.put("/notifications/settings")
async def save_notification_settings(
    request: Request,
    payload: NotificationSettingsIn,
    user: UserClaims = Depends(require_user),
) -> Any:
    body = payload.model_dump()
    if (body["quiet_hours_start"] is None) != (body["quiet_hours_end"] is None):
        raise ValidationError(
            "Укажите начало и конец тихих часов вместе", code="invalid_quiet_hours"
        )
    return await comments(request).save_notification_settings(body, _headers(user))


@router.get("/notifications/push/config")
async def push_config(request: Request) -> dict[str, Any]:
    try:
        return await notifier(request).push_config()
    except Exception:
        return {
            "enabled": False,
            "public_key": None,
            "reason": "notifier_unavailable",
        }


@router.post("/notifications/push/subscribe")
async def push_subscribe(
    request: Request,
    payload: PushSubscribeIn,
    user: UserClaims = Depends(require_user),
) -> Any:
    return await notifier(request).subscribe(
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=request.headers.get("User-Agent"),
    )


@router.delete("/notifications/push/subscribe")
async def push_unsubscribe(
    request: Request,
    payload: PushUnsubscribeIn,
    user: UserClaims = Depends(require_user),
) -> Any:
    return await notifier(request).unsubscribe(user_id=user.id, endpoint=payload.endpoint)


@router.get("/notifications/push/status")
async def push_status(
    request: Request, user: UserClaims = Depends(require_user)
) -> Any:
    return await notifier(request).status(user.id)
