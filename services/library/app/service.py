from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from manga_common.auth import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    refresh_expiry,
    verify_password,
)
from manga_common.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from manga_common.schemas import (
    AnalyticsEventIn,
    AnalyticsIngestOut,
    AnalyticsRetentionOut,
    BookmarkOut,
    ProgressMergeItem,
    ProgressMergeOut,
    ProgressOut,
    ReaderSettings,
    StreakOut,
    TokenPair,
    UserOut,
    YandexCallbackOut,
    YandexCredentials,
    YandexDenyOut,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .analytics import compute_retention
from .config import LibrarySettings
from .models import User
from .repository import (
    add_bookmark,
    as_utc,
    consume_oauth_handoff,
    consume_oauth_state,
    create_oauth_handoff,
    create_oauth_state,
    create_refresh_token,
    create_user,
    delete_progress,
    find_refresh_token,
    get_progress,
    get_settings,
    get_user,
    get_user_by_email,
    get_user_by_yandex_id,
    insert_analytics_events,
    list_analytics_events,
    list_bookmarks,
    list_progress,
    list_reading_days,
    merge_progress,
    purge_expired_oauth_artifacts,
    record_reading_day,
    remove_bookmark,
    revoke_all_tokens,
    revoke_refresh_token,
    upsert_progress,
    upsert_settings,
)
from .streak import compute_streak
from .yandex import YandexOAuthClient, YandexProfile

logger = logging.getLogger(__name__)


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_next_path(raw: str | None) -> str:
    """Only allow same-site absolute paths after a successful login."""

    value = (raw or "/").strip()
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or len(value) > 512
    ):
        return "/"
    return value


def _safe_return_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Некорректный адрес возврата", code="invalid_return_url")
    return raw


def _finish_url(
    return_url: str,
    next_path: str,
    *,
    code: str | None = None,
    error: str | None = None,
) -> str:
    params: dict[str, str] = {}
    if code:
        params["code"] = code
    if error:
        params["error"] = error
    if next_path and next_path != "/":
        params["next"] = next_path
    if not params:
        return return_url
    separator = "&" if "?" in return_url else "?"
    return f"{return_url}{separator}{urlencode(params)}"


class LibraryService:
    def __init__(
        self,
        settings: LibrarySettings,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        yandex: YandexOAuthClient | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.yandex = yandex or YandexOAuthClient(settings)

    async def _issue_tokens(
        self,
        session: AsyncSession,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        access, expires_in = create_access_token(
            self.settings,
            subject=str(user.id),
            role=user.role,
            extra={"display_name": user.display_name, "username": user.display_name},
        )
        refresh = new_refresh_token()
        await create_refresh_token(
            session,
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=refresh_expiry(self.settings),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
            user=_user_out(user),
        )

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        async with self.session_factory() as session:
            if await get_user_by_email(session, email):
                raise ConflictError("Пользователь с таким email уже существует", code="email_taken")
            try:
                user = await create_user(
                    session,
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise ConflictError(
                    "Пользователь с таким email уже существует", code="email_taken"
                ) from exc
            tokens = await self._issue_tokens(
                session, user, user_agent=user_agent, ip_address=ip_address
            )
            await session.commit()
            return tokens

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        async with self.session_factory() as session:
            user = await get_user_by_email(session, email)
            if user is None or not user.is_active or not verify_password(password, user.password_hash):
                raise UnauthorizedError("Неверный email или пароль", code="invalid_credentials")
            if password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            tokens = await self._issue_tokens(
                session, user, user_agent=user_agent, ip_address=ip_address
            )
            await session.commit()
            return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = hash_refresh_token(refresh_token)
        async with self.session_factory() as session:
            stored = await find_refresh_token(session, token_hash)
            if stored is None:
                raise UnauthorizedError("Refresh token не найден", code="invalid_refresh_token")
            expires_at = as_utc(stored.expires_at)
            if stored.revoked_at is not None:
                raise UnauthorizedError("Refresh token отозван", code="refresh_revoked")
            if expires_at is None or expires_at <= datetime.now(UTC):
                raise UnauthorizedError("Refresh token истёк", code="refresh_expired")
            user = await get_user(session, stored.user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("Пользователь не найден", code="invalid_user")
            await revoke_refresh_token(session, stored)
            tokens = await self._issue_tokens(session, user)
            await session.commit()
            return tokens

    async def logout(self, refresh_token: str) -> None:
        token_hash = hash_refresh_token(refresh_token)
        async with self.session_factory() as session:
            stored = await find_refresh_token(session, token_hash)
            if stored is not None and stored.revoked_at is None:
                await revoke_refresh_token(session, stored)
                await session.commit()

    async def me(self, user_id: uuid.UUID) -> UserOut:
        async with self.session_factory() as session:
            user = await get_user(session, user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("Пользователь не найден", code="invalid_user")
            return _user_out(user)

    # ------------------------------------------------------------------
    # Yandex ID OAuth 2.0 (#67)
    # ------------------------------------------------------------------

    async def yandex_status(self) -> bool:
        return self.settings.yandex_oauth_enabled

    def _yandex_available(self, credentials: YandexCredentials | None) -> bool:
        if credentials is not None:
            return credentials.complete
        return self.settings.yandex_oauth_enabled

    async def yandex_start(
        self,
        *,
        return_url: str,
        next_path: str,
        browser_hash: str | None,
        credentials: YandexCredentials | None = None,
    ) -> str:
        if not self._yandex_available(credentials):
            raise ServiceUnavailableError(
                "Вход через Яндекс не настроен", code="yandex_not_configured"
            )
        return_url = _safe_return_url(return_url)
        next_path = _safe_next_path(next_path)
        state = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            await purge_expired_oauth_artifacts(session)
            await create_oauth_state(
                session,
                provider="yandex",
                state_hash=_token_hash(state),
                browser_hash=browser_hash,
                return_url=return_url,
                next_path=next_path,
                expires_at=now
                + timedelta(seconds=self.settings.yandex_state_ttl_seconds),
            )
            await session.commit()
        return self.yandex.authorize_url(state, credentials)

    async def yandex_callback(
        self,
        *,
        state: str,
        code: str,
        browser_hash: str | None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        credentials: YandexCredentials | None = None,
    ) -> YandexCallbackOut:
        if not self._yandex_available(credentials):
            raise ServiceUnavailableError(
                "Вход через Яндекс не настроен", code="yandex_not_configured"
            )

        # Consume the state before any network call: a failed Yandex exchange
        # must not leave a replayable state behind.
        async with self.session_factory() as session:
            stored = await consume_oauth_state(
                session,
                provider="yandex",
                state_hash=_token_hash(state),
                browser_hash=browser_hash,
            )
            if stored is None:
                raise ValidationError(
                    "Ссылка входа устарела или уже использована. Начните вход заново.",
                    code="oauth_state_invalid",
                )
            return_url = stored.return_url
            next_path = stored.next_path
            await session.commit()

        profile = await self.yandex.fetch_profile_for_code(code, credentials)

        handoff_code = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        is_new_user = False
        async with self.session_factory() as session:
            for attempt in range(2):
                try:
                    user, is_new_user = await self._resolve_yandex_user(session, profile)
                    await create_oauth_handoff(
                        session,
                        provider="yandex",
                        code_hash=_token_hash(handoff_code),
                        user_id=user.id,
                        expires_at=now
                        + timedelta(seconds=self.settings.yandex_handoff_ttl_seconds),
                        user_agent=user_agent,
                        ip_address=ip_address,
                    )
                    await session.commit()
                    break
                except IntegrityError as exc:
                    # Two callbacks can race on the unique email/yandex_id
                    # indexes.  Roll back and resolve again against the row
                    # that won the race.
                    await session.rollback()
                    if attempt == 1:
                        raise ConflictError(
                            "Не удалось связать аккаунт с Яндексом. Попробуйте ещё раз.",
                            code="yandex_link_conflict",
                        ) from exc

        return YandexCallbackOut(
            handoff_code=handoff_code,
            redirect_url=_finish_url(return_url, next_path),
            expires_in=self.settings.yandex_handoff_ttl_seconds,
            is_new_user=is_new_user,
        )

    async def yandex_deny(
        self, *, state: str, browser_hash: str | None
    ) -> YandexDenyOut:
        async with self.session_factory() as session:
            stored = await consume_oauth_state(
                session,
                provider="yandex",
                state_hash=_token_hash(state),
                browser_hash=browser_hash,
            )
            if stored is None:
                raise ValidationError(
                    "Ссылка входа устарела или уже использована. Начните вход заново.",
                    code="oauth_state_invalid",
                )
            await session.commit()
            return YandexDenyOut(
                redirect_url=_finish_url(
                    stored.return_url, stored.next_path, error="access_denied"
                )
            )

    async def yandex_exchange(
        self, *, code: str, user_agent: str | None = None, ip_address: str | None = None
    ) -> TokenPair:
        async with self.session_factory() as session:
            handoff = await consume_oauth_handoff(
                session,
                provider="yandex",
                code_hash=_token_hash(code),
            )
            if handoff is None:
                raise UnauthorizedError(
                    "Ссылка входа устарела или уже использована. Начните вход заново.",
                    code="handoff_invalid",
                )
            user = await get_user(session, handoff.user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("Пользователь не найден", code="invalid_user")
            tokens = await self._issue_tokens(
                session,
                user,
                user_agent=handoff.user_agent or user_agent,
                ip_address=handoff.ip_address or ip_address,
            )
            await session.commit()
            return tokens

    async def _resolve_yandex_user(
        self, session: AsyncSession, profile: YandexProfile
    ) -> tuple[User, bool]:
        by_yandex = await get_user_by_yandex_id(session, profile.yandex_id)
        if by_yandex is not None:
            if not by_yandex.is_active:
                raise ForbiddenError("Аккаунт отключён", code="account_disabled")
            return by_yandex, False

        by_email = await get_user_by_email(session, profile.email)
        if by_email is not None:
            if not by_email.is_active:
                raise ForbiddenError("Аккаунт отключён", code="account_disabled")
            if by_email.yandex_id and by_email.yandex_id != profile.yandex_id:
                raise ConflictError(
                    "Этот email уже привязан к другому аккаунту Яндекса.",
                    code="yandex_link_conflict",
                )
            if not by_email.yandex_id:
                # ``default_email`` is verified by Yandex, so linking an
                # existing password account by email is intentional.  Any
                # session created before ownership was proven is invalidated.
                by_email.yandex_id = profile.yandex_id
                await revoke_all_tokens(session, by_email.id)
                await session.flush()
            return by_email, False

        user = await create_user(
            session,
            email=profile.email,
            # A Yandex-only account gets an unguessable local password hash;
            # password login remains impossible until a password is set.
            password_hash=hash_password(secrets.token_urlsafe(48)),
            display_name=profile.display_name,
            yandex_id=profile.yandex_id,
            auth_provider="yandex",
        )
        return user, True

    async def bookmarks(self, user_id: uuid.UUID) -> list[BookmarkOut]:
        async with self.session_factory() as session:
            rows = await list_bookmarks(session, user_id)
            return [BookmarkOut.model_validate(row) for row in rows]

    async def add_bookmark(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> BookmarkOut:
        async with self.session_factory() as session:
            bookmark, created = await add_bookmark(session, user_id, manga_id)
            await session.commit()
            if created:
                logger.info("bookmark added", extra={"user_id": str(user_id)})
            return BookmarkOut.model_validate(bookmark)

    async def remove_bookmark(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            removed = await remove_bookmark(session, user_id, manga_id)
            await session.commit()
            return removed

    async def history(self, user_id: uuid.UUID, limit: int = 100) -> list[ProgressOut]:
        async with self.session_factory() as session:
            rows = await list_progress(session, user_id, limit=limit)
            return [ProgressOut.model_validate(row) for row in rows]

    async def progress(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> ProgressOut:
        async with self.session_factory() as session:
            row = await get_progress(session, user_id, manga_id)
            if row is None:
                raise NotFoundError("Прогресс не найден")
            return ProgressOut.model_validate(row)

    async def upsert_progress(
        self,
        user_id: uuid.UUID,
        *,
        manga_id: uuid.UUID,
        chapter_id: uuid.UUID,
        page: int,
        total_pages: int,
    ) -> ProgressOut:
        async with self.session_factory() as session:
            row = await upsert_progress(
                session,
                user_id=user_id,
                manga_id=manga_id,
                chapter_id=chapter_id,
                page=page,
                total_pages=total_pages,
            )
            await record_reading_day(session, user_id=user_id, read_at=datetime.now(UTC))
            await session.commit()
            return ProgressOut.model_validate(row)

    async def merge_local_progress(
        self,
        user_id: uuid.UUID,
        items: list[ProgressMergeItem],
        read_days: list[datetime] | None = None,
    ) -> ProgressMergeOut:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            merged, unchanged, ignored = await merge_progress(
                session,
                user_id=user_id,
                items=[
                    (
                        item.manga_id,
                        item.chapter_id,
                        item.page,
                        item.total_pages,
                        item.read_at,
                    )
                    for item in items
                ],
            )
            for moment in read_days or []:
                normalized = as_utc(moment)
                if normalized is not None:
                    await record_reading_day(
                        session, user_id=user_id, read_at=min(normalized, now)
                    )
            await session.commit()
            return ProgressMergeOut(merged=merged, unchanged=unchanged, ignored=ignored)

    async def streak(self, user_id: uuid.UUID, timezone: str | None) -> StreakOut:
        async with self.session_factory() as session:
            rows = await list_reading_days(session, user_id)
            return compute_streak(
                [row.last_read_at for row in rows],
                timezone=timezone,
                now=datetime.now(UTC),
            )

    async def ingest_analytics(self, events: list[AnalyticsEventIn]) -> AnalyticsIngestOut:
        rows = [
            {
                "event": event.event,
                "client_id": event.client_id,
                "surface": event.surface,
                "manga_id": event.manga_id,
                "chapter_id": event.chapter_id,
                "dedupe_key": event.dedupe_key,
                "created_at": datetime.now(UTC),
            }
            for event in events
        ]
        async with self.session_factory() as session:
            accepted, duplicates = await insert_analytics_events(session, rows)
            await session.commit()
            return AnalyticsIngestOut(accepted=accepted, duplicates=duplicates)

    async def analytics_retention(self, days: int = 30) -> AnalyticsRetentionOut:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            events = await list_analytics_events(
                session, since=now - timedelta(days=max(1, min(days, 90)) + 30)
            )
        return compute_retention(events, days=days, now=now)

    async def delete_progress(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            removed = await delete_progress(session, user_id, manga_id)
            await session.commit()
            return removed

    async def reader_settings(self, user_id: uuid.UUID) -> ReaderSettings:
        async with self.session_factory() as session:
            row = await get_settings(session, user_id)
            data = (row.data if row else {}) or {}
            return ReaderSettings.model_validate({**ReaderSettings().model_dump(), **data})

    async def save_reader_settings(
        self, user_id: uuid.UUID, settings: ReaderSettings
    ) -> ReaderSettings:
        async with self.session_factory() as session:
            await upsert_settings(session, user_id, settings.model_dump())
            await session.commit()
            return settings

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            await revoke_all_tokens(session, user_id)
            await session.commit()
