from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import (
    AppError,
    UnauthorizedError,
    UpstreamError,
    ValidationError,
    app_error_handler,
)
from manga_common.schemas import (
    IntegrationSecretOut,
    TokenPair,
    UserOut,
    YandexCallbackOut,
    YandexCredentialsOut,
    YandexDenyOut,
    YandexIntegrationOut,
    YandexIntegrationTestCheck,
    YandexIntegrationTestOut,
    YandexIntegrationUpdate,
    YandexStartOut,
)
from manga_common.security import UserClaims, require_admin
from services.gateway.app.api import _reset_yandex_credentials_cache, router
from services.gateway.app.config import GatewaySettings
from services.gateway.app.middleware import RateLimitMiddleware

USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER = UserOut(
    id=USER_ID,
    email="reader@yandex.ru",
    display_name="Иван",
    role="user",
    created_at="2026-01-01T00:00:00Z",
)


class FakeControl:
    def __init__(self) -> None:
        self.credentials = YandexCredentialsOut(source="none", enabled=False)
        self.integration = YandexIntegrationOut(
            enabled=True,
            configured=True,
            client_id=IntegrationSecretOut(
                configured=True, hint="••••1234", updated_at="2026-01-01T00:00:00Z"
            ),
            client_secret=IntegrationSecretOut(
                configured=True, hint="••••5678", updated_at="2026-01-01T00:00:00Z"
            ),
            redirect_uri="https://web.test/api/v1/auth/yandex/callback",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.updates: list[YandexIntegrationUpdate] = []
        self.deleted = 0
        self.credentials_calls = 0

    async def yandex_credentials(self) -> YandexCredentialsOut:
        self.credentials_calls += 1
        return self.credentials

    async def yandex_integration(self) -> YandexIntegrationOut:
        return self.integration

    async def update_yandex_integration(
        self, payload: YandexIntegrationUpdate
    ) -> YandexIntegrationOut:
        self.updates.append(payload)
        return self.integration

    async def delete_yandex_integration(self) -> None:
        self.deleted += 1

    async def test_yandex_integration(self) -> YandexIntegrationTestOut:
        return YandexIntegrationTestOut(
            ok=True,
            configured=True,
            enabled=True,
            checks=[
                YandexIntegrationTestCheck(
                    name="client_id", ok=True, message="Client ID: задан"
                )
            ],
            redirect_uri="https://web.test/api/v1/auth/yandex/callback",
            message="ok",
        )


class FakeLibrary:
    def __init__(self) -> None:
        self.enabled = True
        self.start_payload: dict[str, Any] | None = None
        self.callback_payload: dict[str, Any] | None = None
        self.callback_result = YandexCallbackOut(
            handoff_code="handoff-code-1234567890",
            redirect_url="https://web.test/auth/yandex/finish?next=%2Flibrary",
            expires_in=60,
            is_new_user=False,
        )
        self.callback_error: Exception | None = None
        self.deny_payload: dict[str, Any] | None = None
        self.deny_error: Exception | None = None
        self.exchange_error: Exception | None = None
        self.exchange_codes: list[str] = []

    async def yandex_status(self) -> bool:
        return self.enabled

    async def yandex_start(self, payload: dict[str, Any]) -> YandexStartOut:
        self.start_payload = payload
        return YandexStartOut(
            authorize_url=(
                "https://oauth.yandex.ru/authorize?response_type=code"
                "&client_id=test-client&state=state-value"
            )
        )

    async def yandex_callback(self, payload: dict[str, Any]) -> YandexCallbackOut:
        self.callback_payload = payload
        if self.callback_error is not None:
            raise self.callback_error
        return self.callback_result

    async def yandex_deny(self, payload: dict[str, Any]) -> YandexDenyOut:
        self.deny_payload = payload
        if self.deny_error is not None:
            raise self.deny_error
        return YandexDenyOut(
            redirect_url="https://web.test/auth/yandex/finish?error=access_denied"
        )

    async def yandex_exchange(self, code: str) -> TokenPair:
        self.exchange_codes.append(code)
        if self.exchange_error is not None:
            raise self.exchange_error
        return TokenPair(
            access_token="project-access-token",
            refresh_token="project-refresh-token",
            expires_in=1800,
            user=USER,
        )


def _settings(**overrides: Any) -> GatewaySettings:
    values = {
        "service_name": "gateway-test",
        "public_web_url": "https://web.test",
        "public_api_url": "https://web.test",
        "yandex_client_id": "test-client",
        "yandex_client_secret": "test-secret",
        "yandex_redirect_uri": "https://web.test/api/v1/auth/yandex/callback",
        "yandex_state_ttl_seconds": 600,
    }
    values.update(overrides)
    return GatewaySettings(**values)


def _client(
    library: FakeLibrary,
    settings: GatewaySettings | None = None,
    control: FakeControl | None = None,
    *,
    admin: bool = False,
) -> TestClient:
    _reset_yandex_credentials_cache()
    app = FastAPI()
    app.state.settings = settings or _settings()
    app.state.library = library
    app.state.control = control or FakeControl()
    app.state.catalog = SimpleNamespace()
    app.state.parser = SimpleNamespace()
    app.state.media = SimpleNamespace()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    if admin:
        app.dependency_overrides[require_admin] = lambda: UserClaims(
            id="admin", role="admin", raw={"username": "admin"}
        )
    # HTTPS base URL so the Secure flow cookie is sent back on the callback.
    return TestClient(app, base_url="https://testserver")


def test_start_returns_503_when_provider_is_not_configured() -> None:
    library = FakeLibrary()
    client = _client(
        library,
        settings=_settings(
            yandex_client_id=None,
            yandex_client_secret=None,
            yandex_redirect_uri=None,
        ),
    )

    response = client.get("/api/v1/auth/yandex/start", follow_redirects=False)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "yandex_not_configured"
    assert "test-secret" not in response.text


def test_providers_endpoint_exposes_only_a_boolean() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.get("/api/v1/auth/providers")
    assert response.status_code == 200
    assert response.json() == {"yandex": True}
    assert "test-secret" not in response.text


def test_start_sets_http_only_flow_cookie_and_redirects() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/start?next=/library", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://oauth.yandex.ru/authorize")
    cookie_header = response.headers["set-cookie"]
    assert "mp_yandex_flow=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/api/v1/auth/yandex" in cookie_header
    assert "test-secret" not in response.text

    assert library.start_payload is not None
    assert library.start_payload["return_url"] == "https://web.test/auth/yandex/finish"
    assert library.start_payload["next_path"] == "/library"
    assert len(library.start_payload["browser_hash"]) == 64
    assert library.start_payload["credentials"] == {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "redirect_uri": "https://web.test/api/v1/auth/yandex/callback",
    }


def test_start_uses_capacitor_localhost_for_app_platform() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/start?client=app", follow_redirects=False
    )
    assert response.status_code == 302
    assert library.start_payload is not None
    assert (
        library.start_payload["return_url"]
        == "https://localhost/auth/yandex/finish"
    )


def test_start_sanitizes_open_redirect_next_path() -> None:
    library = FakeLibrary()
    client = _client(library)

    client.get(
        "/api/v1/auth/yandex/start?next=//evil.example/phish", follow_redirects=False
    )
    assert library.start_payload is not None
    assert library.start_payload["next_path"] == "/"


def test_callback_redirects_with_one_time_handoff_not_tokens() -> None:
    library = FakeLibrary()
    client = _client(library)
    client.get("/api/v1/auth/yandex/start", follow_redirects=False)
    flow_cookie = client.cookies.get("mp_yandex_flow")
    assert flow_cookie

    response = client.get(
        "/api/v1/auth/yandex/callback?code=auth-code&state=state-value",
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "code=handoff-code-1234567890" in location
    assert "access_token" not in location
    assert "refresh_token" not in location
    assert "auth-code" not in location
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "mp_yandex_flow=" in response.headers.get("set-cookie", "")

    assert library.callback_payload is not None
    assert library.callback_payload["code"] == "auth-code"
    assert library.callback_payload["state"] == "state-value"
    assert len(library.callback_payload["browser_hash"]) == 64
    assert library.callback_payload["user_agent"] == "testclient"
    assert library.callback_payload["credentials"]["client_id"] == "test-client"


def test_callback_state_error_is_a_redirect_not_a_500() -> None:
    library = FakeLibrary()
    library.callback_error = ValidationError(
        "state expired", code="oauth_state_invalid"
    )
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/callback?code=auth-code&state=state-value",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://web.test/auth/yandex/finish?error=state_invalid"
    )


def test_callback_upstream_error_is_sanitized() -> None:
    library = FakeLibrary()
    library.callback_error = UpstreamError(
        "yandex is down", code="yandex_unavailable"
    )
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/callback?code=auth-code&state=state-value",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://web.test/auth/yandex/finish?error=yandex_unavailable"
    )
    assert "yandex is down" not in response.text


def test_callback_without_code_is_invalid_request() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/callback?state=state-value", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("error=invalid_request")


def test_user_denied_callback_redirects_to_finish_error() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.get(
        "/api/v1/auth/yandex/callback?error=access_denied&state=state-value",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://web.test/auth/yandex/finish?error=access_denied"
    )
    assert library.deny_payload is not None
    assert library.deny_payload["state"] == "state-value"


def test_exchange_returns_normal_token_pair() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.post(
        "/api/v1/auth/yandex/exchange", json={"code": "handoff-code-1234567890"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "project-access-token"
    assert body["refresh_token"] == "project-refresh-token"
    assert body["user"]["email"] == "reader@yandex.ru"
    assert library.exchange_codes == ["handoff-code-1234567890"]


def test_exchange_rejects_used_or_expired_handoff() -> None:
    library = FakeLibrary()
    library.exchange_error = UnauthorizedError(
        "handoff expired", code="handoff_invalid"
    )
    client = _client(library)

    response = client.post(
        "/api/v1/auth/yandex/exchange", json={"code": "handoff-code-1234567890"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "handoff_invalid"


def test_exchange_validates_code_length() -> None:
    library = FakeLibrary()
    client = _client(library)

    response = client.post("/api/v1/auth/yandex/exchange", json={"code": "short"})
    assert response.status_code == 422


def test_db_credentials_win_over_env_bootstrap() -> None:
    library = FakeLibrary()
    control = FakeControl()
    control.credentials = YandexCredentialsOut(
        source="db",
        enabled=True,
        client_id="db-client",
        client_secret="db-secret",
        redirect_uri="https://db.test/api/v1/auth/yandex/callback",
    )
    client = _client(library, control=control)

    response = client.get("/api/v1/auth/yandex/start", follow_redirects=False)
    assert response.status_code == 302
    assert library.start_payload is not None
    assert library.start_payload["credentials"] == {
        "client_id": "db-client",
        "client_secret": "db-secret",
        "redirect_uri": "https://db.test/api/v1/auth/yandex/callback",
    }


def test_db_only_config_works_without_env() -> None:
    library = FakeLibrary()
    control = FakeControl()
    control.credentials = YandexCredentialsOut(
        source="db",
        enabled=True,
        client_id="db-client",
        client_secret="db-secret",
        redirect_uri="https://db.test/api/v1/auth/yandex/callback",
    )
    client = _client(
        library,
        settings=_settings(
            yandex_client_id=None,
            yandex_client_secret=None,
            yandex_redirect_uri=None,
        ),
        control=control,
    )

    assert client.get("/api/v1/auth/providers").json() == {"yandex": True}
    response = client.get("/api/v1/auth/yandex/start", follow_redirects=False)
    assert response.status_code == 302
    assert library.start_payload is not None
    assert library.start_payload["credentials"]["client_id"] == "db-client"


def test_disabled_db_provider_does_not_fall_back_to_env() -> None:
    library = FakeLibrary()
    control = FakeControl()
    control.credentials = YandexCredentialsOut(
        source="db",
        enabled=False,
        client_id="db-client",
        client_secret="db-secret",
        redirect_uri="https://db.test/api/v1/auth/yandex/callback",
    )
    client = _client(library, control=control)

    assert client.get("/api/v1/auth/providers").json() == {"yandex": False}
    response = client.get("/api/v1/auth/yandex/start", follow_redirects=False)
    assert response.status_code == 503
    assert library.start_payload is None


def test_credentials_are_cached_for_sixty_seconds() -> None:
    library = FakeLibrary()
    control = FakeControl()
    client = _client(library, control=control)

    client.get("/api/v1/auth/providers")
    client.get("/api/v1/auth/providers")
    assert control.credentials_calls == 1


def test_admin_get_is_masked_and_has_no_secrets() -> None:
    library = FakeLibrary()
    control = FakeControl()
    client = _client(library, control=control, admin=True)

    response = client.get("/api/v1/admin/integrations/yandex")
    assert response.status_code == 200
    body = response.json()
    assert body["client_secret"] == {
        "configured": True,
        "hint": "••••5678",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    assert "test-secret" not in response.text
    assert "db-secret" not in response.text


def test_admin_update_and_delete_are_proxied() -> None:
    library = FakeLibrary()
    control = FakeControl()
    client = _client(library, control=control, admin=True)

    update = client.put(
        "/api/v1/admin/integrations/yandex",
        json={
            "enabled": False,
            "client_id": "new-client-id",
            "redirect_uri": "https://web.test/api/v1/auth/yandex/callback",
        },
    )
    assert update.status_code == 200
    assert control.updates
    assert control.updates[0].enabled is False
    assert control.updates[0].client_id == "new-client-id"
    assert control.updates[0].client_secret is None

    deleted = client.delete("/api/v1/admin/integrations/yandex")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert control.deleted == 1


def test_admin_test_endpoint_never_echoes_secrets() -> None:
    library = FakeLibrary()
    client = _client(library, admin=True)

    response = client.post("/api/v1/admin/integrations/yandex/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "test-secret" not in response.text
    assert "client_secret" not in response.text


def test_admin_routes_require_an_admin_token() -> None:
    library = FakeLibrary()
    client = _client(library, admin=False)
    response = client.get("/api/v1/admin/integrations/yandex")
    assert response.status_code == 401


def test_oauth_paths_get_a_stricter_rate_limit() -> None:
    async def _app(scope, receive, send):  # pragma: no cover - never called
        return None

    middleware = RateLimitMiddleware(_app, oauth_limit=7)
    assert middleware._limit_for("/api/v1/auth/yandex/start") == 7
    assert middleware._limit_for("/api/v1/auth/yandex/callback") == 7
    assert middleware._limit_for("/api/v1/auth/yandex/exchange") == 7
    assert middleware._limit_for("/api/v1/manga") == 240
