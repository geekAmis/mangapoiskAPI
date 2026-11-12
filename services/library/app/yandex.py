from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from manga_common.config import Settings
from manga_common.errors import UpstreamError, ValidationError
from manga_common.schemas import YandexCredentials

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class YandexProfile:
    yandex_id: str
    email: str
    display_name: str
    real_name: str | None = None
    avatar_id: str | None = None


def _invalid_profile(message: str, code: str = "yandex_profile_invalid") -> ValidationError:
    return ValidationError(message, code=code)


def profile_from_payload(payload: dict[str, Any]) -> YandexProfile:
    """Map Yandex ``/info`` JSON into the fields the library stores.

    Only ``default_email`` is accepted: Yandex marks it as verified, while the
    ``emails`` list may contain addresses the user has not confirmed.  Missing
    or malformed values are rejected instead of silently creating an account
    without a usable email.
    """

    raw_id = payload.get("id")
    if raw_id is None or not str(raw_id).strip():
        raise _invalid_profile("Яндекс не вернул идентификатор пользователя")
    yandex_id = str(raw_id).strip()
    if len(yandex_id) > 64:
        raise _invalid_profile("Некорректный идентификатор пользователя Яндекса")

    raw_email = payload.get("default_email")
    email = str(raw_email).strip() if raw_email else ""
    if not email:
        raise _invalid_profile(
            "Яндекс не вернул подтверждённый email. Разрешите доступ к email и попробуйте снова.",
            code="yandex_email_missing",
        )
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise _invalid_profile(
            "Яндекс вернул некорректный email. Попробуйте войти ещё раз.",
            code="yandex_email_missing",
        ) from exc

    raw_display = payload.get("display_name") or payload.get("real_name") or ""
    display_name = str(raw_display).strip()[:64]
    if not display_name:
        display_name = email.split("@", 1)[0][:64] or "Читатель"

    real_name = payload.get("real_name")
    avatar_id = payload.get("avatar_id")
    return YandexProfile(
        yandex_id=yandex_id,
        email=email.lower(),
        display_name=display_name,
        real_name=str(real_name).strip()[:128] if real_name else None,
        avatar_id=str(avatar_id) if avatar_id else None,
    )


class YandexOAuthClient:
    """Server-side Yandex OAuth 2.0 client.

    The client secret is only ever sent in the token POST body.  This class
    deliberately never logs authorization codes, tokens or raw upstream
    payloads; errors are mapped to stable, user-safe codes.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    @property
    def enabled(self) -> bool:
        return self.settings.yandex_oauth_enabled

    def _credentials(self, credentials: YandexCredentials | None) -> YandexCredentials:
        if credentials is not None:
            if credentials.complete:
                return credentials
            # An explicitly supplied DB bundle wins over env even when it is
            # incomplete: never silently mix DB and .env credentials.
            raise ValidationError(
                "Конфигурация Яндекс ID неполная", code="yandex_not_configured"
            )
        if self.settings.yandex_oauth_enabled:
            return YandexCredentials(
                client_id=self.settings.yandex_client_id or "",
                client_secret=self.settings.yandex_client_secret or "",
                redirect_uri=self.settings.yandex_redirect_uri or "",
            )
        raise ValidationError(
            "Вход через Яндекс не настроен", code="yandex_not_configured"
        )

    def authorize_url(
        self, state: str, credentials: YandexCredentials | None = None
    ) -> str:
        resolved = self._credentials(credentials)
        params = {
            "response_type": "code",
            "client_id": resolved.client_id,
            "redirect_uri": resolved.redirect_uri,
            "state": state,
            "scope": self.settings.yandex_scope,
        }
        base = self.settings.yandex_authorize_url
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode(params)}"

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, **kwargs)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0), follow_redirects=False
        ) as client:
            return await client.request(method, url, **kwargs)

    async def exchange_code(
        self, code: str, credentials: YandexCredentials | None = None
    ) -> str:
        """Exchange an authorization code for a Yandex access token."""

        resolved = self._credentials(credentials)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": resolved.client_id,
            "client_secret": resolved.client_secret,
        }
        try:
            response = await self._request(
                "POST",
                self.settings.yandex_token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            logger.warning("yandex token endpoint timed out")
            raise UpstreamError(
                "Яндекс не ответил вовремя. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("yandex token endpoint is unavailable: %s", type(exc).__name__)
            raise UpstreamError(
                "Не удалось связаться с Яндексом. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc

        if response.status_code in {400, 401, 403}:
            logger.info("yandex rejected an authorization code: status=%s", response.status_code)
            raise ValidationError(
                "Код входа Яндекса недействителен или истёк. Начните вход заново.",
                code="yandex_code_invalid",
            )
        if response.status_code >= 400:
            logger.warning("yandex token endpoint returned %s", response.status_code)
            raise UpstreamError(
                "Яндекс временно недоступен. Попробуйте ещё раз.",
                code="yandex_unavailable",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Яндекс вернул некорректный ответ. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            logger.warning("yandex token response has no access_token")
            raise UpstreamError(
                "Яндекс вернул некорректный ответ. Попробуйте ещё раз.",
                code="yandex_unavailable",
            )
        return str(token)

    async def fetch_profile(
        self, access_token: str, credentials: YandexCredentials | None = None
    ) -> YandexProfile:
        try:
            response = await self._request(
                "GET",
                self.settings.yandex_profile_url,
                params={"format": "json"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TimeoutException as exc:
            logger.warning("yandex profile endpoint timed out")
            raise UpstreamError(
                "Яндекс не ответил вовремя. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("yandex profile endpoint is unavailable: %s", type(exc).__name__)
            raise UpstreamError(
                "Не удалось связаться с Яндексом. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc

        if response.status_code in {401, 403}:
            raise ValidationError(
                "Яндекс отклонил токен входа. Начните вход заново.",
                code="yandex_code_invalid",
            )
        if response.status_code >= 400:
            logger.warning("yandex profile endpoint returned %s", response.status_code)
            raise UpstreamError(
                "Яндекс временно недоступен. Попробуйте ещё раз.",
                code="yandex_unavailable",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Яндекс вернул некорректный профиль. Попробуйте ещё раз.",
                code="yandex_unavailable",
            ) from exc
        if not isinstance(payload, dict):
            raise _invalid_profile("Яндекс вернул некорректный профиль")
        return profile_from_payload(payload)

    async def fetch_profile_for_code(
        self, code: str, credentials: YandexCredentials | None = None
    ) -> YandexProfile:
        access_token = await self.exchange_code(code, credentials)
        return await self.fetch_profile(access_token, credentials)
