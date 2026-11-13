from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_common.errors import NotFoundError, ValidationError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from .config import ControlSettings
from .crypto import SecretBox
from .models import AdProvider, AdSecret
from .repository import audit

logger = logging.getLogger(__name__)

AdProviderType = Literal["yandex", "adfox", "google", "custom_html", "custom_script"]
AdPlacement = Literal["header", "sidebar", "in-feed", "post-chapter", "mobile-sticky"]
AdAudience = Literal["guest", "authenticated", "both"]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# ---------------------------------------------------------------------------
# HTML sanitizer for custom banners
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = {
    "a",
    "abbr",
    "article",
    "aside",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "picture",
    "section",
    "small",
    "source",
    "span",
    "strong",
    "u",
    "ul",
}
_VOID_TAGS = {"br", "hr", "img", "source"}
_BLOCKED_TAGS = {
    "applet",
    "audio",
    "base",
    "button",
    "canvas",
    "embed",
    "form",
    "frame",
    "frameset",
    "iframe",
    "input",
    "link",
    "math",
    "meta",
    "noscript",
    "object",
    "option",
    "script",
    "select",
    "style",
    "svg",
    "template",
    "textarea",
    "video",
}
_GLOBAL_ATTRS = {"class", "id", "title", "role", "aria-label"}
_TAG_ATTRS = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt", "width", "height", "loading", "decoding", "srcset", "sizes"},
    "source": {"src", "srcset", "sizes", "type", "media"},
}
_SAFE_URL_PREFIXES = ("http://", "https://", "/", "#", "?", "./", "../", "mailto:")


def _safe_url(value: str, *, image: bool = False) -> str | None:
    cleaned = value.strip().replace("\x00", "")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(token in lowered for token in ("javascript:", "vbscript:", "data:")):
        return None
    if image:
        if lowered.startswith(("http://", "https://", "/", "./", "../")):
            return cleaned
        return None
    if lowered.startswith(_SAFE_URL_PREFIXES):
        return cleaned
    return None


def _safe_attr(tag: str, name: str, value: str) -> str | None:
    lowered_name = name.lower()
    if lowered_name.startswith("on"):
        return None
    if lowered_name.startswith("data-"):
        return value[:500]
    allowed = _GLOBAL_ATTRS | _TAG_ATTRS.get(tag, set())
    if lowered_name not in allowed:
        return None
    if lowered_name in {"href", "src"}:
        return _safe_url(value, image=lowered_name == "src")
    if lowered_name == "srcset":
        return value[:2000] if not re.search(r"(?:javascript|vbscript|data):", value, re.I) else None
    if lowered_name in {"width", "height"}:
        return value if value.isdigit() and len(value) <= 5 else None
    if lowered_name == "target":
        return value if value in {"_blank", "_self"} else None
    if lowered_name == "class":
        return " ".join(part for part in value.split() if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", part))[:512]
    if lowered_name == "id":
        return value if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) else None
    return value[:1000]


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._stack: list[tuple[str, bool]] = []

    def _skip_depth(self) -> bool:
        return any(not allowed for _, allowed in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS:
            if not self._skip_depth() and tag in _ALLOWED_TAGS:
                self._emit_start(tag, attrs, void=True)
            return
        allowed = tag in _ALLOWED_TAGS and not self._skip_depth()
        self._stack.append((tag, allowed))
        if allowed:
            self._emit_start(tag, attrs, void=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS:
            if not self._skip_depth() and tag in _ALLOWED_TAGS:
                self._emit_start(tag, attrs, void=True)
            return
        if not self._skip_depth() and tag in _ALLOWED_TAGS:
            self._emit_start(tag, attrs, void=False)
            self._parts.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        index = len(self._stack) - 1
        while index >= 0 and self._stack[index][0] != tag:
            index -= 1
        if index < 0:
            return
        while len(self._stack) > index:
            popped_tag, allowed = self._stack.pop()
            if allowed and popped_tag not in _VOID_TAGS:
                self._parts.append(f"</{popped_tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth():
            self._parts.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        return

    def _emit_start(
        self, tag: str, attrs: list[tuple[str, str | None]], *, void: bool
    ) -> None:
        rendered: list[str] = []
        for raw_name, raw_value in attrs:
            if raw_value is None:
                continue
            value = _safe_attr(tag, raw_name, raw_value)
            if value is None:
                continue
            rendered.append(f' {raw_name.lower()}="{escape(value, quote=True)}"')
        if tag == "a" and any('target="_blank"' in item for item in rendered):
            rendered = [item for item in rendered if not item.startswith(" rel=")]
            rendered.append(' rel="noopener noreferrer"')
        suffix = " /" if void and tag in {"br", "hr", "img", "source"} else ""
        self._parts.append(f"<{tag}{''.join(rendered)}{suffix}>")

    @property
    def result(self) -> str:
        while self._stack:
            tag, allowed = self._stack.pop()
            if allowed and tag not in _VOID_TAGS:
                self._parts.append(f"</{tag}>")
        return "".join(self._parts).strip()


def sanitize_ad_html(value: str) -> str:
    """Return a conservative, script-free subset of admin-provided HTML."""

    if not value:
        return ""
    parser = _Sanitizer()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        # HTMLParser is forgiving, but never trade a parse failure for raw HTML.
        return ""
    return parser.result[:100_000]


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "••••"
    return f"••••{value[-4:]}"


def _parse_minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def schedule_active(
    schedule_days: list[int] | None,
    schedule_start: str,
    schedule_end: str,
    timezone: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Check whether an ad schedule covers the current local time.

    Empty day lists mean every day; a range that crosses midnight (for example
    22:00–02:00) is treated as an overnight window.
    """

    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = (now or datetime.now(UTC)).astimezone(zone)
    if schedule_days and local.weekday() not in schedule_days:
        return False
    if not schedule_start or not schedule_end:
        return True
    start = _parse_minutes(schedule_start)
    end = _parse_minutes(schedule_end)
    current = local.hour * 60 + local.minute
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AdSecretOut(BaseModel):
    name: str
    configured: bool = True
    hint: str
    updated_at: datetime | None = None


class _AdFields(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("Название не должно быть пустым или содержать переводы строк")
        return cleaned

    @field_validator("schedule_start", "schedule_end", check_fields=False)
    @classmethod
    def _clean_time(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _TIME_RE.fullmatch(value):
            raise ValueError("Время должно быть в формате ЧЧ:ММ")
        return value

    @field_validator("schedule_days", check_fields=False)
    @classmethod
    def _clean_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        days = sorted({int(day) for day in value})
        if any(day < 0 or day > 6 for day in days):
            raise ValueError("День недели должен быть от 0 (понедельник) до 6")
        return days

    @field_validator("timezone", check_fields=False)
    @classmethod
    def _clean_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Неизвестный часовой пояс") from exc
        return cleaned


class AdProviderCreate(_AdFields):
    name: str = Field(min_length=1, max_length=128)
    type: AdProviderType
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    placement: AdPlacement
    audience: AdAudience = "both"
    frequency_cap: int = Field(default=0, ge=0, le=1000)
    format: str = Field(default="", max_length=32)
    width: int | None = Field(default=None, ge=0, le=4096)
    height: int | None = Field(default=None, ge=0, le=4096)
    schedule_days: list[int] = Field(default_factory=list)
    schedule_start: str = "00:00"
    schedule_end: str = "23:59"
    timezone: str = "Europe/Moscow"
    config: dict[str, Any] = Field(default_factory=dict)
    custom_html: str = Field(default="", max_length=100_000)
    custom_script: str = Field(default="", max_length=100_000)
    exclude_adult: bool = True
    hide_for_donors: bool = False
    require_consent: bool = False


class AdProviderUpdate(_AdFields):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    type: AdProviderType | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    placement: AdPlacement | None = None
    audience: AdAudience | None = None
    frequency_cap: int | None = Field(default=None, ge=0, le=1000)
    format: str | None = Field(default=None, max_length=32)
    width: int | None = Field(default=None, ge=0, le=4096)
    height: int | None = Field(default=None, ge=0, le=4096)
    schedule_days: list[int] | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None
    timezone: str | None = None
    config: dict[str, Any] | None = None
    custom_html: str | None = Field(default=None, max_length=100_000)
    custom_script: str | None = Field(default=None, max_length=100_000)
    exclude_adult: bool | None = None
    hide_for_donors: bool | None = None
    require_consent: bool | None = None


class AdProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    enabled: bool
    priority: int
    placement: str
    audience: str
    frequency_cap: int
    format: str
    width: int | None = None
    height: int | None = None
    schedule_days: list[int] = Field(default_factory=list)
    schedule_start: str
    schedule_end: str
    timezone: str
    config: dict[str, Any] = Field(default_factory=dict)
    custom_html: str = ""
    custom_script: str = ""
    exclude_adult: bool = True
    hide_for_donors: bool = False
    require_consent: bool = False
    secrets: list[AdSecretOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdPublicSlotOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    placement: str
    priority: int
    audience: str
    frequency_cap: int
    format: str
    width: int | None = None
    height: int | None = None
    content: str = ""
    content_type: Literal["html", "script", "none"] = "none"
    require_consent: bool = False
    # Public, non-secret provider parameters.  For Yandex RTB this carries
    # `block_id`; secrets live in ad_secrets and are never serialized here.
    config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _secret_out(secret: AdSecret) -> AdSecretOut:
    return AdSecretOut(
        name=secret.name,
        configured=True,
        hint=secret.hint,
        updated_at=secret.updated_at,
    )


def ad_out(row: AdProvider) -> AdProviderOut:
    return AdProviderOut(
        id=row.id,
        name=row.name,
        type=row.type,
        enabled=row.enabled,
        priority=row.priority,
        placement=row.placement,
        audience=row.audience,
        frequency_cap=row.frequency_cap,
        format=row.format,
        width=row.width,
        height=row.height,
        schedule_days=list(row.schedule_days or []),
        schedule_start=row.schedule_start,
        schedule_end=row.schedule_end,
        timezone=row.timezone,
        config=row.config or {},
        custom_html=row.custom_html or "",
        custom_script=row.custom_script or "",
        exclude_adult=row.exclude_adult,
        hide_for_donors=row.hide_for_donors,
        require_consent=row.require_consent,
        secrets=[_secret_out(secret) for secret in sorted(row.secrets, key=lambda item: item.name)],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class AdsService:
    def __init__(
        self,
        settings: ControlSettings,
        session_factory: async_sessionmaker[AsyncSession],
        box: SecretBox | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.box = box or SecretBox(settings.control_secret_key)

    def _public_text(self, row: AdProvider) -> str:
        return "\n".join(
            [
                row.custom_html or "",
                row.custom_script or "",
                json.dumps(row.config or {}, ensure_ascii=False),
            ]
        )

    def _assert_no_secret_in_public_content(
        self, content: str, secrets: list[AdSecret]
    ) -> None:
        for secret in secrets:
            try:
                plaintext = self.box.decrypt(secret.value_encrypted)
            except Exception:
                # A rotated master key must not block editing unrelated fields.
                continue
            if plaintext and plaintext in content:
                raise ValidationError(
                    "Секретный ключ нельзя хранить в публичном контенте (HTML/script/config). "
                    "Сначала удалите его из публичного поля.",
                    code="secret_in_public_content",
                )

    async def _get(self, session: AsyncSession, provider_id: uuid.UUID) -> AdProvider:
        row = await session.scalar(
            select(AdProvider)
            .options(selectinload(AdProvider.secrets))
            .where(AdProvider.id == provider_id)
        )
        if row is None:
            raise NotFoundError("Рекламная интеграция не найдена", code="ad_not_found")
        return row

    async def list(self) -> list[AdProviderOut]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(AdProvider)
                .options(selectinload(AdProvider.secrets))
                .order_by(AdProvider.priority.asc(), AdProvider.created_at.asc())
            )
            return [ad_out(row) for row in rows.unique().all()]

    async def create(self, payload: AdProviderCreate) -> AdProviderOut:
        values = payload.model_dump()
        values["custom_html"] = sanitize_ad_html(values.get("custom_html") or "")
        values["custom_script"] = values.get("custom_script") or ""
        async with self.session_factory() as session:
            row = AdProvider(**values)
            session.add(row)
            await session.flush()
            await audit(
                session,
                "ads.provider_created",
                details={
                    "provider_id": str(row.id),
                    "name": row.name,
                    "type": row.type,
                    "placement": row.placement,
                    "enabled": row.enabled,
                },
            )
            await session.commit()
            await session.refresh(row, attribute_names=["secrets"])
            return ad_out(row)

    async def update(self, provider_id: uuid.UUID, payload: AdProviderUpdate) -> AdProviderOut:
        values = payload.model_dump(exclude_unset=True)
        if "custom_html" in values and values["custom_html"] is not None:
            values["custom_html"] = sanitize_ad_html(values["custom_html"])
        if "custom_script" in values and values["custom_script"] is None:
            values["custom_script"] = ""
        async with self.session_factory() as session:
            row = await self._get(session, provider_id)
            public_update = json.dumps(
                {
                    key: value
                    for key, value in values.items()
                    if key in {"custom_html", "custom_script", "config"}
                },
                ensure_ascii=False,
                default=str,
            )
            self._assert_no_secret_in_public_content(public_update, row.secrets)
            for key, value in values.items():
                setattr(row, key, value)
            await session.flush()
            # Only field names are logged: config/custom markup may contain
            # operator-provided values that should not be copied into audit.
            await audit(
                session,
                "ads.provider_updated",
                details={
                    "provider_id": str(row.id),
                    "name": row.name,
                    "fields": sorted(values.keys()),
                },
            )
            await session.commit()
            await session.refresh(row, attribute_names=["secrets"])
            return ad_out(row)

    async def delete(self, provider_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            # _get eagerly loads secrets, so the ORM cascade deletes them even
            # on SQLite where ON DELETE CASCADE is not enabled by default.
            row = await self._get(session, provider_id)
            await session.delete(row)
            await audit(
                session,
                "ads.provider_deleted",
                details={
                    "provider_id": str(provider_id),
                    "name": row.name,
                    "type": row.type,
                    "placement": row.placement,
                },
            )
            await session.commit()

    async def set_secret(
        self, provider_id: uuid.UUID, name: str, value: str
    ) -> AdSecretOut:
        cleaned_name = name.strip()
        if not _SECRET_NAME_RE.fullmatch(cleaned_name):
            raise ValidationError(
                "Имя ключа может содержать только буквы, цифры, точку, дефис и подчёркивание",
                code="invalid_secret_name",
            )
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValidationError("Значение ключа не может быть пустым", code="empty_secret")
        if len(cleaned_value) > 20_000:
            raise ValidationError("Значение ключа слишком длинное", code="secret_too_long")
        async with self.session_factory() as session:
            row = await self._get(session, provider_id)
            if cleaned_value in self._public_text(row):
                raise ValidationError(
                    "Этот ключ уже присутствует в публичном контенте интеграции. "
                    "Удалите его из HTML/script/config перед сохранением как секрета.",
                    code="secret_in_public_content",
                )
            secret = next((item for item in row.secrets if item.name == cleaned_name), None)
            encrypted = self.box.encrypt(cleaned_value)
            hint = mask_secret(cleaned_value)
            if secret is None:
                secret = AdSecret(
                    provider_id=row.id,
                    name=cleaned_name,
                    value_encrypted=encrypted,
                    hint=hint,
                )
                session.add(secret)
            else:
                secret.value_encrypted = encrypted
                secret.hint = hint
            await session.flush()
            await audit(
                session,
                "ads.secret_set",
                details={
                    "provider_id": str(row.id),
                    "name": cleaned_name,
                    "hint": hint,
                },
            )
            await session.commit()
            await session.refresh(secret)
            return _secret_out(secret)

    async def delete_secret(self, provider_id: uuid.UUID, name: str) -> None:
        async with self.session_factory() as session:
            row = await self._get(session, provider_id)
            secret = next((item for item in row.secrets if item.name == name), None)
            if secret is None:
                raise NotFoundError("Ключ не найден", code="ad_secret_not_found")
            await session.delete(secret)
            await audit(
                session,
                "ads.secret_deleted",
                details={"provider_id": str(row.id), "name": name},
            )
            await session.commit()

    async def public_slots(
        self,
        *,
        audience: Literal["guest", "authenticated"],
        donor: bool = False,
        adult: bool = False,
        consent: bool = False,
    ) -> list[AdPublicSlotOut]:
        allowed_audiences = {"both", audience}
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(AdProvider)
                .options(selectinload(AdProvider.secrets))
                .where(AdProvider.enabled.is_(True))
                .order_by(AdProvider.priority.asc(), AdProvider.created_at.asc())
            )
            slots: list[AdPublicSlotOut] = []
            for row in rows.unique().all():
                if row.audience not in allowed_audiences:
                    continue
                if donor and row.hide_for_donors:
                    continue
                if adult and row.exclude_adult:
                    continue
                if row.require_consent and not consent:
                    continue
                if not schedule_active(
                    list(row.schedule_days or []),
                    row.schedule_start,
                    row.schedule_end,
                    row.timezone,
                ):
                    continue
                content = ""
                content_type: Literal["html", "script", "none"] = "none"
                if row.type == "custom_html":
                    content = sanitize_ad_html(row.custom_html or "")
                    if not content:
                        continue
                    content_type = "html"
                elif row.type == "custom_script":
                    content = row.custom_script or ""
                    if not content.strip():
                        continue
                    content_type = "script"
                elif not (row.config or row.secrets):
                    # A network provider without a block id or a secret is not
                    # ready; hide it instead of reserving an empty slot.
                    continue
                slots.append(
                    AdPublicSlotOut(
                        id=row.id,
                        name=row.name,
                        type=row.type,
                        placement=row.placement,
                        priority=row.priority,
                        audience=row.audience,
                        frequency_cap=row.frequency_cap,
                        format=row.format,
                        width=row.width,
                        height=row.height,
                        content=content,
                        content_type=content_type,
                        require_consent=row.require_consent,
                        config=row.config or {},
                    )
                )
            return slots
