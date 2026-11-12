from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ValidationError
from services.control.app.ads import (
    AdProviderCreate,
    AdProviderUpdate,
    AdsService,
    mask_secret,
    sanitize_ad_html,
    schedule_active,
)
from services.control.app.config import ControlSettings
from services.control.app.crypto import SecretBox
from services.control.app.models import AuditLog
from sqlalchemy import select


async def _service(tmp_path: Path) -> tuple[AdsService, object]:
    db_path = tmp_path / "ads.db"
    settings = ControlSettings(
        service_name="control-ads-test",
        control_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        control_secret_key="ads-unit-test-secret",
    )
    engine = create_engine(settings.control_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    return AdsService(settings, session_factory, SecretBox(settings.control_secret_key)), engine


def test_custom_html_sanitizer_removes_active_content() -> None:
    dirty = (
        '<div class="banner"><script>alert(1)</script>'
        '<img src="/banner.png" onerror="alert(2)" alt="ok">'
        '<a href="javascript:alert(3)" target="_blank">link</a>'
        "<iframe src=\"https://evil.example\"></iframe></div>"
    )

    cleaned = sanitize_ad_html(dirty)

    assert "<script" not in cleaned
    assert "onerror" not in cleaned
    assert "javascript:" not in cleaned
    assert "<iframe" not in cleaned
    assert '<img src="/banner.png" alt="ok" />' in cleaned
    assert 'target="_blank"' in cleaned
    assert 'rel="noopener noreferrer"' in cleaned
    assert "<div class=\"banner\">" in cleaned


def test_custom_html_sanitizer_escapes_text_and_blocks_unknown_tags() -> None:
    cleaned = sanitize_ad_html('<p>2 < 3 & 4 > 1</p><form action="/steal"><input></form>')

    assert "&lt; 3 &amp; 4 &gt;" in cleaned
    assert "<form" not in cleaned
    assert "<input" not in cleaned


def test_schedule_handles_days_and_overnight_window() -> None:
    thursday = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)  # 15:00 in Moscow

    assert schedule_active([3], "14:00", "16:00", "Europe/Moscow", now=thursday) is True
    assert schedule_active([0], "14:00", "16:00", "Europe/Moscow", now=thursday) is False
    assert schedule_active([], "22:00", "02:00", "Europe/Moscow", now=thursday) is False
    assert schedule_active([], "14:00", "16:00", "Europe/Moscow", now=thursday) is True
    assert schedule_active([], "00:00", "00:00", "Europe/Moscow", now=thursday) is True


def test_secret_mask_never_reveals_full_value() -> None:
    assert mask_secret("short") == "••••"
    assert mask_secret("synthetic-yandex-key-1234") == "••••1234"


@pytest.mark.asyncio
async def test_ad_crud_secret_masking_audience_and_audit(tmp_path: Path) -> None:
    service, engine = await _service(tmp_path)
    try:
        guest = await service.create(
            AdProviderCreate(
                name="Guest banner",
                type="custom_html",
                placement="header",
                audience="guest",
                format="728x90",
                width=728,
                height=90,
                custom_html=(
                    '<div class="qa-banner"><script>alert(1)</script>'
                    "<strong>Guest offer</strong></div>"
                ),
            )
        )
        auth = await service.create(
            AdProviderCreate(
                name="Auth network",
                type="yandex",
                placement="sidebar",
                audience="authenticated",
                priority=20,
            )
        )
        both = await service.create(
            AdProviderCreate(
                name="Shared in-feed",
                type="custom_html",
                placement="in-feed",
                audience="both",
                custom_html='<div class="qa-infeed">Shared</div>',
            )
        )
        disabled = await service.create(
            AdProviderCreate(
                name="Disabled",
                type="custom_html",
                placement="mobile-sticky",
                audience="both",
                enabled=False,
                custom_html='<div class="qa-disabled">Disabled</div>',
            )
        )
        adult = await service.create(
            AdProviderCreate(
                name="Adult-sensitive",
                type="custom_html",
                placement="post-chapter",
                audience="both",
                custom_html='<div class="qa-adult">Adult</div>',
            )
        )

        listed = await service.list()
        assert {item.name for item in listed} == {
            "Guest banner",
            "Disabled",
            "Shared in-feed",
            "Auth network",
            "Adult-sensitive",
        }
        # Lower priority number wins; the list is sorted by priority first.
        assert listed[0].name == "Auth network"

        # Custom HTML is sanitized on write and again on read.
        assert "<script" not in guest.custom_html
        assert "onerror" not in guest.custom_html

        guest_slots = await service.public_slots(audience="guest")
        guest_names = {slot.name for slot in guest_slots}
        assert guest_names == {"Guest banner", "Shared in-feed", "Adult-sensitive"}
        assert disabled.name not in guest_names
        assert all(slot.content_type == "html" for slot in guest_slots)

        auth_slots = await service.public_slots(audience="authenticated")
        auth_names = {slot.name for slot in auth_slots}
        # A network provider without a key is intentionally hidden, and the
        # guest-only slot must not leak into the authenticated audience.
        assert "Auth network" not in auth_names
        assert "Guest banner" not in auth_names
        assert {"Shared in-feed", "Adult-sensitive"} <= auth_names

        # Secrets are encrypted at rest, masked in admin output, and never in
        # the public payload.
        secret = await service.set_secret(auth.id, "api_key", "synthetic-yandex-key-1234")
        assert secret.hint == "••••1234"
        assert "synthetic-yandex-key-1234" not in str(secret.model_dump())

        # A key may not be pasted into public HTML/script/config.
        with pytest.raises(ValidationError) as leaked_key:
            await service.update(
                auth.id,
                AdProviderUpdate(
                    custom_html='<div data-key="synthetic-yandex-key-1234">leak</div>'
                ),
            )
        assert leaked_key.value.code == "secret_in_public_content"

        public_marker = await service.create(
            AdProviderCreate(
                name="Public marker",
                type="custom_html",
                placement="header",
                custom_html="<div>public-marker-9999</div>",
            )
        )
        with pytest.raises(ValidationError) as leaked_public:
            await service.set_secret(public_marker.id, "api_key", "public-marker-9999")
        assert leaked_public.value.code == "secret_in_public_content"
        await service.delete(public_marker.id)

        async with service.session_factory() as session:
            from services.control.app.models import AdSecret

            row = await session.scalar(
                select(AdSecret).where(AdSecret.provider_id == auth.id)
            )
            assert row is not None
            assert row.value_encrypted != "synthetic-yandex-key-1234"
            assert service.box.decrypt(row.value_encrypted) == "synthetic-yandex-key-1234"

        auth_slots = await service.public_slots(audience="authenticated")
        auth_names = {slot.name for slot in auth_slots}
        assert "Auth network" in auth_names
        public_payload = str([slot.model_dump(mode="json") for slot in auth_slots])
        assert "synthetic-yandex-key-1234" not in public_payload
        assert "••••1234" not in public_payload

        # Adult titles exclude providers with the default exclude_adult flag.
        adult_slots = await service.public_slots(audience="guest", adult=True)
        assert "Adult-sensitive" not in {slot.name for slot in adult_slots}

        # Donor entitlements hide flagged providers.
        await service.update(both.id, AdProviderUpdate(hide_for_donors=True))
        donor_slots = await service.public_slots(audience="guest", donor=True)
        assert "Shared in-feed" not in {slot.name for slot in donor_slots}

        # Toggle and update without restarting the service.
        updated = await service.update(disabled.id, AdProviderUpdate(enabled=True))
        assert updated.enabled is True

        await service.delete(adult.id)
        assert adult.name not in {item.name for item in await service.list()}

        # Audit records actions and never stores the raw secret.
        async with service.session_factory() as session:
            audit_rows = list(
                (await session.scalars(select(AuditLog).order_by(AuditLog.created_at.asc()))).all()
            )
        actions = [row.action for row in audit_rows]
        assert "ads.provider_created" in actions
        assert "ads.provider_updated" in actions
        assert "ads.provider_deleted" in actions
        assert "ads.secret_set" in actions
        audit_payload = str([row.details for row in audit_rows])
        assert "synthetic-yandex-key-1234" not in audit_payload
        secret_set = next(row for row in audit_rows if row.action == "ads.secret_set")
        assert secret_set.details["name"] == "api_key"
        assert secret_set.details["hint"] == "••••1234"

        await service.delete_secret(auth.id, "api_key")
        assert all(not item.secrets for item in await service.list() if item.id == auth.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_provider_removes_encrypted_secrets(tmp_path: Path) -> None:
    service, engine = await _service(tmp_path)
    try:
        provider = await service.create(
            AdProviderCreate(
                name="Delete me",
                type="custom_html",
                placement="header",
                custom_html="<div>temporary</div>",
            )
        )
        await service.set_secret(provider.id, "api_key", "synthetic-delete-key-9999")

        await service.delete(provider.id)

        from services.control.app.models import AdSecret

        async with service.session_factory() as session:
            leftover = await session.scalar(
                select(AdSecret).where(AdSecret.provider_id == provider.id)
            )
        assert leftover is None
        assert await service.list() == []
    finally:
        await engine.dispose()
