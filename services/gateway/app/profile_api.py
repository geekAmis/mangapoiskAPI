from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from manga_common.profile_schemas import (
    AdminProfileReportOut,
    MyProfileOut,
    ProfileEventOut,
    ProfileReportIn,
    ProfileReportOut,
    ProfileReportResolveIn,
    ProfileUpdate,
    PublicProfileOut,
)
from manga_common.schemas import OkResponse
from manga_common.security import UserClaims, optional_user, require_admin, require_user

from .clients import LibraryClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

Handle = Annotated[str, Path(min_length=1, max_length=64)]


def _library(request: Request) -> LibraryClient:
    return request.app.state.library


def _authorization(request: Request) -> str:
    return request.headers.get("Authorization", "")


def _apply_profile_headers(response: Response, profile: PublicProfileOut) -> None:
    """Privacy-first caching/indexing.

    Profiles are noindex until the owner opts in.  Owner responses are never
    stored by shared caches; public cards expire quickly so a privacy change
    takes effect without a deploy.
    """

    # Owner responses contain exact timestamps, so they are never indexable
    # even when the public card is.  Crawlers only see the guest response.
    response.headers["X-Robots-Tag"] = (
        "index, follow" if profile.indexable and not profile.is_owner else "noindex, nofollow"
    )
    response.headers["Cache-Control"] = (
        "private, no-store" if profile.is_owner else "public, max-age=60"
    )


@router.get("/users/{handle}", response_model=PublicProfileOut)
async def public_profile(
    request: Request,
    response: Response,
    handle: Handle,
    timezone: str | None = Query(default=None, max_length=64),
    user: Annotated[UserClaims | None, Depends(optional_user)] = None,
) -> PublicProfileOut:
    profile = await _library(request).profile(
        handle,
        viewer_id=user.id if user is not None else None,
        timezone=timezone,
    )
    _apply_profile_headers(response, profile)
    return profile


@router.get("/me/profile", response_model=MyProfileOut)
async def my_profile(
    request: Request,
    timezone: str | None = Query(default=None, max_length=64),
    user: UserClaims = Depends(require_user),
) -> MyProfileOut:
    return await _library(request).my_profile(_authorization(request), timezone)


@router.patch("/me/profile", response_model=MyProfileOut)
async def update_my_profile(
    request: Request,
    payload: ProfileUpdate,
    user: UserClaims = Depends(require_user),
) -> MyProfileOut:
    return await _library(request).update_profile(_authorization(request), payload)


@router.get("/me/events", response_model=list[ProfileEventOut])
async def my_events(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    user: UserClaims = Depends(require_user),
) -> list[ProfileEventOut]:
    return await _library(request).my_events(_authorization(request), limit)


@router.post("/users/{handle}/report", response_model=ProfileReportOut)
async def report_profile(
    request: Request,
    handle: Handle,
    payload: ProfileReportIn,
    user: UserClaims = Depends(require_user),
) -> ProfileReportOut:
    return await _library(request).report_profile(
        _authorization(request), handle, payload.reason
    )


@router.post("/users/{handle}/block", response_model=OkResponse)
async def block_profile(
    request: Request,
    handle: Handle,
    user: UserClaims = Depends(require_user),
) -> OkResponse:
    await _library(request).block_profile(_authorization(request), handle, blocked=True)
    return OkResponse(message="Пользователь заблокирован")


@router.delete("/users/{handle}/block", response_model=OkResponse)
async def unblock_profile(
    request: Request,
    handle: Handle,
    user: UserClaims = Depends(require_user),
) -> OkResponse:
    await _library(request).block_profile(_authorization(request), handle, blocked=False)
    return OkResponse(message="Пользователь разблокирован")


@router.get("/admin/profile-reports", response_model=list[AdminProfileReportOut])
async def admin_profile_reports(
    request: Request,
    status: str = Query(default="open", pattern="^(open|resolved|dismissed|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserClaims = Depends(require_admin),
) -> list[AdminProfileReportOut]:
    return await _library(request).admin_profile_reports(
        _authorization(request), status=status, limit=limit
    )


@router.patch(
    "/admin/profile-reports/{report_id}", response_model=AdminProfileReportOut
)
async def admin_resolve_profile_report(
    request: Request,
    report_id: uuid.UUID,
    payload: ProfileReportResolveIn,
    user: UserClaims = Depends(require_admin),
) -> AdminProfileReportOut:
    return await _library(request).resolve_profile_report(
        _authorization(request), str(report_id), payload.status
    )
