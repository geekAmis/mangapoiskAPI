from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import (
    ConflictError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from manga_common.schemas import YandexCredentials
from services.library.app.config import LibrarySettings
from services.library.app.migrations import ensure_runtime_schema
from services.library.app.models import User
from services.library.app.service import LibraryService
from services.library.app.yandex import (
    YandexOAuthClient,
    YandexProfile,
    profile_from_payload,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

REDIRECT_URI = "https://api.test/api/v1/auth/yandex/callback"
RETURN_URL = "https://web.test/auth/yandex/finish"
PROFILE = YandexProfile(
    yandex_id="123456789",
    email="reader@yandex.ru",
    display_name="Иван Читатель",
)


def _flow_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeYandex:
    def __init__(self, profile: YandexProfile | None = PROFILE, error: Exception | None = None):
        self.profile = profile
        self.error = error
        self.codes: list[str] = []

    def authorize_url(self, state: str, credentials=None) -> str:
        client_id = credentials.client_id if credentials else "test-client"
        return (
            "https://oauth.yandex.ru/authorize?response_type=code"
            f"&client_id={client_id}&redirect_uri={REDIRECT_URI}&state={state}"
            "&scope=login%3Aemail+login%3Ainfo+login%3Aavatar"
        )

    async def fetch_profile_for_code(self, code: str, credentials=None) -> YandexProfile:
        self.codes.append(code)
        if self.error is not None:
            raise self.error
        assert self.profile is not None
        return self.profile


class Harness:
    def __init__(self, service: LibraryService, engine: Any, settings: LibrarySettings):
        self.service = service
        self.engine = engine
        self.settings = settings
        self.session_factory = create_session_factory(engine)

    async def start(
        self,
        *,
        browser: str = "flow-secret",
        next_path: str = "/library",
        credentials=None,
    ) -> str:
        url = await self.service.yandex_start(
            return_url=RETURN_URL,
            next_path=next_path,
            browser_hash=_flow_hash(browser),
            credentials=credentials,
        )
        return parse_qs(urlparse(url).query)["state"][0]

    async def callback(
        self,
        state: str,
        *,
        code: str = "auth-code",
        browser: str = "flow-secret",
        credentials=None,
    ):
        return await self.service.yandex_callback(
            state=state,
            code=code,
            browser_hash=_flow_hash(browser),
            user_agent="pytest",
            ip_address="203.0.113.10",
            credentials=credentials,
        )


@pytest.fixture
async def harness(tmp_path: Path):
    db_path = tmp_path / "library-yandex.db"
    settings = LibrarySettings(
        service_name="library-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-test-secret-that-is-long-enough",
        yandex_client_id="test-client",
        yandex_client_secret="test-secret",
        yandex_redirect_uri=REDIRECT_URI,
    )
    engine = create_engine(settings.library_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    fake = FakeYandex()
    service = LibraryService(
        settings, create_session_factory(engine), yandex=fake  # type: ignore[arg-type]
    )
    harness = Harness(service, engine, settings)
    harness.fake = fake  # type: ignore[attr-defined]
    yield harness
    await engine.dispose()


async def _user_count(harness: Harness) -> int:
    async with harness.session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(User)) or 0)


async def _get_user(harness: Harness, email: str) -> User | None:
    async with harness.session_factory() as session:
        return await session.scalar(select(User).where(User.email == email))


@pytest.mark.asyncio
async def test_state_is_single_use_and_browser_bound(harness: Harness) -> None:
    state = await harness.start(browser="browser-a")

    with pytest.raises(ValidationError) as mismatch:
        await harness.callback(state, browser="browser-b")
    assert mismatch.value.code == "oauth_state_invalid"

    result = await harness.callback(state, browser="browser-a")
    assert result.handoff_code

    with pytest.raises(ValidationError) as replay:
        await harness.callback(state, browser="browser-a")
    assert replay.value.code == "oauth_state_invalid"


@pytest.mark.asyncio
async def test_expired_state_is_rejected(harness: Harness) -> None:
    state = await harness.start()
    async with harness.session_factory() as session:
        from services.library.app.models import OAuthState

        row = await session.scalar(select(OAuthState))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    with pytest.raises(ValidationError) as expired:
        await harness.callback(state)
    assert expired.value.code == "oauth_state_invalid"


@pytest.mark.asyncio
async def test_callback_creates_user_and_exchange_is_single_use(harness: Harness) -> None:
    state = await harness.start()
    result = await harness.callback(state, code="one-time-code")
    assert result.is_new_user is True
    assert result.redirect_url.startswith(RETURN_URL)

    tokens = await harness.service.yandex_exchange(code=result.handoff_code)
    assert tokens.user.email == "reader@yandex.ru"
    assert tokens.user.display_name == "Иван Читатель"
    assert tokens.access_token and tokens.refresh_token

    user = await _get_user(harness, "reader@yandex.ru")
    assert user is not None
    assert user.yandex_id == "123456789"
    assert user.auth_provider == "yandex"
    assert await _user_count(harness) == 1

    with pytest.raises(UnauthorizedError) as replay:
        await harness.service.yandex_exchange(code=result.handoff_code)
    assert replay.value.code == "handoff_invalid"


@pytest.mark.asyncio
async def test_expired_handoff_is_rejected(harness: Harness) -> None:
    state = await harness.start()
    result = await harness.callback(state)
    async with harness.session_factory() as session:
        from services.library.app.models import OAuthHandoffCode

        row = await session.scalar(select(OAuthHandoffCode))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    with pytest.raises(UnauthorizedError) as expired:
        await harness.service.yandex_exchange(code=result.handoff_code)
    assert expired.value.code == "handoff_invalid"


@pytest.mark.asyncio
async def test_existing_email_account_is_linked_without_duplicate(harness: Harness) -> None:
    registered = await harness.service.register(
        email="reader@yandex.ru",
        password="very-secret-password",
        display_name="Старое имя",
    )
    old_refresh = registered.refresh_token

    state = await harness.start()
    result = await harness.callback(state)
    assert result.is_new_user is False
    tokens = await harness.service.yandex_exchange(code=result.handoff_code)
    assert tokens.user.id == registered.user.id
    assert await _user_count(harness) == 1

    user = await _get_user(harness, "reader@yandex.ru")
    assert user is not None and user.yandex_id == "123456789"

    # Linking proves ownership: sessions created before the link are revoked.
    with pytest.raises(UnauthorizedError):
        await harness.service.refresh(old_refresh)

    # A second Yandex login resolves by yandex_id and still does not duplicate.
    state2 = await harness.start()
    result2 = await harness.callback(state2)
    assert result2.is_new_user is False
    tokens2 = await harness.service.yandex_exchange(code=result2.handoff_code)
    assert tokens2.user.id == registered.user.id
    assert await _user_count(harness) == 1


@pytest.mark.asyncio
async def test_conflicting_yandex_link_is_rejected(harness: Harness) -> None:
    await harness.service.register(
        email="reader@yandex.ru",
        password="very-secret-password",
        display_name="Читатель",
    )
    async with harness.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "reader@yandex.ru"))
        assert user is not None
        user.yandex_id = "different-yandex-id"
        await session.commit()

    state = await harness.start()
    with pytest.raises(ConflictError) as conflict:
        await harness.callback(state)
    assert conflict.value.code == "yandex_link_conflict"
    assert await _user_count(harness) == 1


@pytest.mark.asyncio
async def test_duplicate_yandex_id_is_prevented_by_unique_index(harness: Harness) -> None:
    await harness.service.register(
        email="first@example.com", password="very-secret-password", display_name="Первый"
    )
    await harness.service.register(
        email="second@example.com", password="very-secret-password", display_name="Второй"
    )
    async with harness.session_factory() as session:
        first = await session.scalar(select(User).where(User.email == "first@example.com"))
        second = await session.scalar(select(User).where(User.email == "second@example.com"))
        assert first is not None and second is not None
        first.yandex_id = "same-id"
        await session.commit()
        second.yandex_id = "same-id"
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_user_denied_flow_returns_error_redirect(harness: Harness) -> None:
    state = await harness.start()
    denied = await harness.service.yandex_deny(
        state=state, browser_hash=_flow_hash("flow-secret")
    )
    assert "error=access_denied" in denied.redirect_url
    assert "next=%2Flibrary" in denied.redirect_url

    with pytest.raises(ValidationError):
        await harness.service.yandex_deny(
            state=state, browser_hash=_flow_hash("flow-secret")
        )


@pytest.mark.asyncio
async def test_profile_mapping_requires_default_email() -> None:
    profile = profile_from_payload(
        {
            "id": 42,
            "default_email": "User@Yandex.RU",
            "display_name": "  Иван  ",
            "avatar_id": "abc",
        }
    )
    assert profile.yandex_id == "42"
    assert profile.email == "user@yandex.ru"
    assert profile.display_name == "Иван"
    assert profile.avatar_id == "abc"

    fallback = profile_from_payload({"id": "7", "default_email": "nick@yandex.ru"})
    assert fallback.display_name == "nick"

    with pytest.raises(ValidationError) as missing:
        profile_from_payload({"id": "7", "emails": ["other@yandex.ru"]})
    assert missing.value.code == "yandex_email_missing"

    with pytest.raises(ValidationError) as invalid:
        profile_from_payload({"id": "7", "default_email": "not-an-email"})
    assert invalid.value.code == "yandex_email_missing"


@pytest.mark.asyncio
async def test_httpx_code_exchange_and_profile_fetch(tmp_path: Path) -> None:
    settings = LibrarySettings(
        service_name="library-test",
        library_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'unused.db').as_posix()}",
        jwt_secret="library-test-secret-that-is-long-enough",
        yandex_client_id="test-client",
        yandex_client_secret="test-secret",
        yandex_redirect_uri=REDIRECT_URI,
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            seen["token_body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "yandex-access-token"})
        if request.url.path == "/info":
            seen["profile_auth"] = request.headers.get("Authorization")
            seen["profile_query"] = request.url.query.decode()
            return httpx.Response(
                200,
                json={
                    "id": "123",
                    "default_email": "reader@yandex.ru",
                    "display_name": "Иван",
                    "avatar_id": "avatar",
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yandex = YandexOAuthClient(settings, client=client)
    profile = await yandex.fetch_profile_for_code("auth-code")
    await client.aclose()

    assert profile.email == "reader@yandex.ru"
    assert "code=auth-code" in seen["token_body"]
    assert "client_secret=test-secret" in seen["token_body"]
    assert seen["profile_auth"] == "Bearer yandex-access-token"
    assert seen["profile_query"] == "format=json"
    assert "yandex-access-token" not in repr(profile)


@pytest.mark.asyncio
async def test_httpx_rejects_invalid_code(tmp_path: Path) -> None:
    settings = LibrarySettings(
        service_name="library-test",
        library_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'unused2.db').as_posix()}",
        jwt_secret="library-test-secret-that-is-long-enough",
        yandex_client_id="test-client",
        yandex_client_secret="test-secret",
        yandex_redirect_uri=REDIRECT_URI,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yandex = YandexOAuthClient(settings, client=client)
    with pytest.raises(ValidationError) as invalid:
        await yandex.exchange_code("expired-code")
    await client.aclose()
    assert invalid.value.code == "yandex_code_invalid"


@pytest.mark.asyncio
async def test_incomplete_db_credentials_do_not_fall_back_to_env(harness: Harness) -> None:
    with pytest.raises(ServiceUnavailableError) as incomplete:
        await harness.start(
            credentials=YandexCredentials(
                client_id="only-id", client_secret="", redirect_uri=REDIRECT_URI
            )
        )
    assert incomplete.value.code == "yandex_not_configured"


@pytest.mark.asyncio
async def test_library_works_with_db_only_credentials(tmp_path: Path) -> None:
    settings = LibrarySettings(
        service_name="library-test",
        library_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'db-only.db').as_posix()}",
        jwt_secret="library-test-secret-that-is-long-enough",
        # No YANDEX_* env at all: the gateway supplies DB values per request.
    )
    engine = create_engine(settings.library_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    service = LibraryService(
        settings,
        create_session_factory(engine),
        yandex=FakeYandex(),  # type: ignore[arg-type]
    )
    harness = Harness(service, engine, settings)
    credentials = YandexCredentials(
        client_id="db-client",
        client_secret="db-secret",
        redirect_uri=REDIRECT_URI,
    )

    state = await harness.start(credentials=credentials)
    result = await harness.callback(state, credentials=credentials)
    tokens = await service.yandex_exchange(code=result.handoff_code)
    assert tokens.user.email == "reader@yandex.ru"
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_secrets_in_callback_response_or_logs(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    state = await harness.start()
    result = await harness.callback(state, code="sensitive-auth-code")
    payload = result.model_dump_json()

    assert "test-secret" not in payload
    assert "sensitive-auth-code" not in payload
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "test-secret" not in caplog.text
    assert "sensitive-auth-code" not in caplog.text
    assert result.handoff_code not in caplog.text
