from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from manga_common.schemas import (
    AnalyticsEventsIn,
    AnalyticsIngestOut,
    AnalyticsRetentionOut,
    AnalyticsSurfacesOut,
    BookmarkCreate,
    BookmarkOut,
    LoginRequest,
    LogoutRequest,
    OkResponse,
    ProgressMergeOut,
    ProgressMergeRequest,
    ProgressOut,
    ProgressUpsert,
    ReaderSettings,
    RefreshRequest,
    RegisterRequest,
    StreakOut,
    TokenPair,
    UserOut,
)
from manga_common.security import UserClaims, require_internal_token, require_user

from .service import LibraryService

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_service(request: Request) -> LibraryService:
    return request.app.state.service


def _meta(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("X-Client-IP")
    ip = forwarded or (request.client.host if request.client else None)
    return request.headers.get("User-Agent"), ip


@router.post("/auth/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    service: LibraryService = Depends(get_service),
) -> TokenPair:
    user_agent, ip = _meta(request)
    return await service.register(
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
        user_agent=user_agent,
        ip_address=ip,
    )


@router.post("/auth/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    request: Request,
    service: LibraryService = Depends(get_service),
) -> TokenPair:
    user_agent, ip = _meta(request)
    return await service.login(
        email=str(payload.email),
        password=payload.password,
        user_agent=user_agent,
        ip_address=ip,
    )


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    service: LibraryService = Depends(get_service),
) -> TokenPair:
    return await service.refresh(payload.refresh_token)


@router.post("/auth/logout", response_model=OkResponse)
async def logout(
    payload: LogoutRequest,
    service: LibraryService = Depends(get_service),
) -> OkResponse:
    await service.logout(payload.refresh_token)
    return OkResponse(message="Вы вышли из аккаунта")


@router.get("/auth/me", response_model=UserOut)
async def me(
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> UserOut:
    return await service.me(uuid.UUID(user.id))


@router.get("/me/bookmarks", response_model=list[BookmarkOut])
async def bookmarks(
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> list[BookmarkOut]:
    return await service.bookmarks(uuid.UUID(user.id))


@router.post("/me/bookmarks", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
async def add_bookmark(
    payload: BookmarkCreate,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> BookmarkOut:
    return await service.add_bookmark(uuid.UUID(user.id), payload.manga_id)


@router.delete("/me/bookmarks/{manga_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark(
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> Response:
    await service.remove_bookmark(uuid.UUID(user.id), manga_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/history", response_model=list[ProgressOut])
async def history(
    limit: int = Query(default=100, ge=1, le=500),
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> list[ProgressOut]:
    return await service.history(uuid.UUID(user.id), limit=limit)


@router.get("/me/progress", response_model=list[ProgressOut])
async def progress_list(
    limit: int = Query(default=100, ge=1, le=500),
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> list[ProgressOut]:
    return await service.history(uuid.UUID(user.id), limit=limit)


@router.get("/me/progress/{manga_id}", response_model=ProgressOut)
async def progress_one(
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> ProgressOut:
    return await service.progress(uuid.UUID(user.id), manga_id)


@router.put("/me/progress", response_model=ProgressOut)
async def progress_upsert(
    payload: ProgressUpsert,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> ProgressOut:
    return await service.upsert_progress(
        uuid.UUID(user.id),
        manga_id=payload.manga_id,
        chapter_id=payload.chapter_id,
        page=payload.page,
        total_pages=payload.total_pages,
    )


@router.post("/me/progress/merge", response_model=ProgressMergeOut)
async def progress_merge(
    payload: ProgressMergeRequest,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> ProgressMergeOut:
    return await service.merge_local_progress(
        uuid.UUID(user.id), payload.items, payload.read_days
    )


@router.get("/me/streak", response_model=StreakOut)
async def streak(
    timezone: str | None = Query(default=None, max_length=64),
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> StreakOut:
    return await service.streak(uuid.UUID(user.id), timezone)


@router.post("/analytics/events", response_model=AnalyticsIngestOut)
async def analytics_events(
    payload: AnalyticsEventsIn,
    service: LibraryService = Depends(get_service),
) -> AnalyticsIngestOut:
    return await service.ingest_analytics(payload.events)


@router.get("/analytics/retention", response_model=AnalyticsRetentionOut)
async def analytics_retention(
    days: int = Query(default=30, ge=1, le=90),
    service: LibraryService = Depends(get_service),
) -> AnalyticsRetentionOut:
    return await service.analytics_retention(days)


@router.get("/analytics/surfaces", response_model=AnalyticsSurfacesOut)
async def analytics_surfaces(
    days: int = Query(default=30, ge=1, le=90),
    service: LibraryService = Depends(get_service),
) -> AnalyticsSurfacesOut:
    return await service.analytics_surfaces(days)


@router.delete("/me/progress/{manga_id}", status_code=status.HTTP_204_NO_CONTENT)
async def progress_delete(
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> Response:
    await service.delete_progress(uuid.UUID(user.id), manga_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/settings", response_model=ReaderSettings)
async def reader_settings(
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> ReaderSettings:
    return await service.reader_settings(uuid.UUID(user.id))


@router.put("/me/settings", response_model=ReaderSettings)
async def save_reader_settings(
    payload: ReaderSettings,
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> ReaderSettings:
    return await service.save_reader_settings(uuid.UUID(user.id), payload)


@router.post("/me/logout-all", response_model=OkResponse)
async def logout_all(
    user: UserClaims = Depends(require_user),
    service: LibraryService = Depends(get_service),
) -> OkResponse:
    await service.revoke_all(uuid.UUID(user.id))
    return OkResponse(message="Все сессии завершены")
