from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlparse

from manga_common.errors import ValidationError
from manga_common.schemas import (
    IntegrationSecretOut,
    YandexCredentialsOut,
    YandexIntegrationOut,
    YandexIntegrationTestCheck,
    YandexIntegrationTestOut,
    YandexIntegrationUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .ads import mask_secret
from .config import ControlSettings
from .crypto import SecretBox
from .models import IntegrationSecret, IntegrationSetting
from .repository import audit

logger = logging.getLogger(__name__)

YANDEX_PROVIDER = "yandex"
YANDEX_SECRET_NAMES = ("client_id", "client_secret", "redirect_uri")
YANDEX_CALLBACK_PATH = "/api/v1/auth/yandex/callback"


def _clean_value(name: str, raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if any(character in value for character in "\r\n\t"):
        raise ValidationError(
            "Значение не должно содержать переводы строк", code="invalid_integration_value"
        )
    if name in {"client_id", "client_secret"} and len(value) < 8:
        raise ValidationError(
            "Ключ Яндекса слишком короткий — проверьте значение из Яндекс.Консоли.",
            code="invalid_integration_value",
        )
    return value


def _clean_redirect_uri(raw: str, *, production: bool) -> str:
    value = raw.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(
            "Redirect URI должен быть абсолютным http(s)-адресом",
            code="invalid_redirect_uri",
        )
    if production and parsed.scheme != "https":
        raise ValidationError(
            "В production redirect URI должен использовать HTTPS",
            code="invalid_redirect_uri",
        )
    if parsed.query or parsed.fragment:
        raise ValidationError(
            "Redirect URI не должен содержать query или fragment",
            code="invalid_redirect_uri",
        )
    if parsed.path.rstrip("/") != YANDEX_CALLBACK_PATH:
        raise ValidationError(
            f"Redirect URI должен оканчиваться на {YANDEX_CALLBACK_PATH}",
            code="invalid_redirect_uri",
        )
    return value


def _secret_out(row: IntegrationSecret | None) -> IntegrationSecretOut:
    if row is None:
        return IntegrationSecretOut()
    return IntegrationSecretOut(
        configured=True,
        hint=row.hint,
        updated_at=row.updated_at,
    )


def _latest(values: list[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


class IntegrationsService:
    """Encrypted third-party credentials managed from the admin panel.

    The same Fernet key as SSH/ad secrets is used.  Public/admin responses only
    expose ``configured``/``hint``/``updated_at``; plaintext is available only
    through :meth:`yandex_credentials`, an internal-token endpoint.
    """

    def __init__(
        self,
        settings: ControlSettings,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        box: SecretBox | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.box = box or SecretBox(settings.control_secret_key)

    async def _load(
        self, session: AsyncSession, provider: str = YANDEX_PROVIDER
    ) -> tuple[dict[str, IntegrationSecret], IntegrationSetting | None]:
        rows = await session.scalars(
            select(IntegrationSecret).where(IntegrationSecret.provider == provider)
        )
        setting = await session.scalar(
            select(IntegrationSetting).where(IntegrationSetting.provider == provider)
        )
        return {row.name: row for row in rows}, setting

    def _decrypt(self, row: IntegrationSecret | None) -> str | None:
        if row is None:
            return None
        try:
            return self.box.decrypt(row.value_encrypted)
        except Exception:
            logger.error("integration secret cannot be decrypted: %s/%s", row.provider, row.name)
            return None

    async def get_yandex(self) -> YandexIntegrationOut:
        async with self.session_factory() as session:
            secrets, setting = await self._load(session)
            redirect_row = secrets.get("redirect_uri")
            return YandexIntegrationOut(
                provider=YANDEX_PROVIDER,
                enabled=setting.enabled if setting is not None else bool(secrets),
                configured=all(name in secrets for name in YANDEX_SECRET_NAMES),
                client_id=_secret_out(secrets.get("client_id")),
                client_secret=_secret_out(secrets.get("client_secret")),
                redirect_uri=self._decrypt(redirect_row),
                redirect_uri_updated_at=redirect_row.updated_at if redirect_row else None,
                updated_at=_latest(
                    [row.updated_at for row in secrets.values()]
                    + [setting.updated_at if setting else None]
                ),
            )

    async def update_yandex(self, payload: YandexIntegrationUpdate) -> YandexIntegrationOut:
        fields = set(payload.model_fields_set)
        if not fields:
            raise ValidationError("Нет полей для обновления", code="empty_integration_update")

        async with self.session_factory() as session:
            secrets, setting = await self._load(session)
            changed: list[str] = []

            if "enabled" in fields and payload.enabled is not None:
                if setting is None:
                    setting = IntegrationSetting(
                        provider=YANDEX_PROVIDER, enabled=payload.enabled
                    )
                    session.add(setting)
                else:
                    setting.enabled = payload.enabled
                changed.append("enabled")

            for name in YANDEX_SECRET_NAMES:
                if name not in fields:
                    continue
                raw = getattr(payload, name)
                existing = secrets.get(name)
                if raw is None or not raw.strip():
                    if existing is not None:
                        await session.delete(existing)
                    changed.append(name)
                    continue
                if name == "redirect_uri":
                    cleaned = _clean_redirect_uri(
                        raw, production=self.settings.is_production
                    )
                else:
                    cleaned = _clean_value(name, raw)
                encrypted = self.box.encrypt(cleaned)
                hint = mask_secret(cleaned)
                if existing is None:
                    session.add(
                        IntegrationSecret(
                            provider=YANDEX_PROVIDER,
                            name=name,
                            value_encrypted=encrypted,
                            hint=hint,
                        )
                    )
                else:
                    existing.value_encrypted = encrypted
                    existing.hint = hint
                changed.append(name)

            if not changed:
                raise ValidationError(
                    "Нет изменений для сохранения", code="empty_integration_update"
                )

            await session.flush()
            # Only field names are audited; values and even hints are not.
            await audit(
                session,
                "integration.yandex.updated",
                details={"provider": YANDEX_PROVIDER, "fields": sorted(set(changed))},
            )
            await session.commit()
        return await self.get_yandex()

    async def delete_yandex(self) -> None:
        async with self.session_factory() as session:
            secrets, setting = await self._load(session)
            had_values = bool(secrets) or setting is not None
            for row in secrets.values():
                await session.delete(row)
            if setting is not None:
                await session.delete(setting)
            await audit(
                session,
                "integration.yandex.deleted",
                details={"provider": YANDEX_PROVIDER, "had_values": had_values},
            )
            await session.commit()

    async def test_yandex(self) -> YandexIntegrationTestOut:
        async with self.session_factory() as session:
            secrets, setting = await self._load(session)

        checks: list[YandexIntegrationTestCheck] = []
        for name, label in (
            ("client_id", "Client ID"),
            ("client_secret", "Client secret"),
            ("redirect_uri", "Redirect URI"),
        ):
            row = secrets.get(name)
            if row is None:
                checks.append(
                    YandexIntegrationTestCheck(
                        name=name, ok=False, message=f"{label}: не задан"
                    )
                )
                continue
            value = self._decrypt(row)
            if value is None:
                checks.append(
                    YandexIntegrationTestCheck(
                        name=name,
                        ok=False,
                        message=f"{label}: не удалось расшифровать (проверьте CONTROL_SECRET_KEY)",
                    )
                )
                continue
            if name == "redirect_uri":
                try:
                    _clean_redirect_uri(value, production=self.settings.is_production)
                except ValidationError as exc:
                    checks.append(
                        YandexIntegrationTestCheck(
                            name=name, ok=False, message=f"{label}: {exc.message}"
                        )
                    )
                    continue
            checks.append(
                YandexIntegrationTestCheck(
                    name=name, ok=True, message=f"{label}: задан"
                )
            )

        redirect_row = secrets.get("redirect_uri")
        redirect_uri = self._decrypt(redirect_row)
        enabled = setting.enabled if setting is not None else bool(secrets)
        ok = all(check.ok for check in checks)
        return YandexIntegrationTestOut(
            ok=ok,
            configured=ok,
            enabled=enabled,
            checks=checks,
            redirect_uri=redirect_uri,
            message=(
                "Конфигурация заполнена. Секреты не покидают сервер; реальный обмен "
                "кода проверяется только входом через Яндекс."
                if ok
                else "Конфигурация неполная или содержит ошибку. Исправьте отмеченные поля."
            ),
        )

    async def yandex_credentials(self) -> YandexCredentialsOut:
        """Internal-only plaintext bundle used by the gateway.

        This method is deliberately not exposed through a public route.  If the
        DB has at least one value, ``source='db'`` and the gateway must not fall
        back to environment variables, even when the bundle is incomplete.
        """

        async with self.session_factory() as session:
            secrets, setting = await self._load(session)

        if not secrets:
            return YandexCredentialsOut(source="none", enabled=False)

        values: dict[str, str | None] = {}
        for name in YANDEX_SECRET_NAMES:
            values[name] = self._decrypt(secrets.get(name))
        complete = all(values.values())
        return YandexCredentialsOut(
            source="db",
            enabled=(setting.enabled if setting is not None else True) and complete,
            client_id=values["client_id"],
            client_secret=values["client_secret"],
            redirect_uri=values["redirect_uri"],
            updated_at=_latest(
                [row.updated_at for row in secrets.values()]
                + [setting.updated_at if setting else None]
            ),
        )

    async def clear_provider(self, provider: str) -> None:  # pragma: no cover - reserved
        """Delete all values for a provider (future integrations)."""

        async with self.session_factory() as session:
            rows = await session.scalars(
                select(IntegrationSecret).where(IntegrationSecret.provider == provider)
            )
            for row in rows:
                await session.delete(row)
            setting = await session.scalar(
                select(IntegrationSetting).where(IntegrationSetting.provider == provider)
            )
            if setting is not None:
                await session.delete(setting)
            await session.commit()
