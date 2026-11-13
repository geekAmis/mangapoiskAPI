from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.config import get_settings
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import AppError, ValidationError, app_error_handler
from manga_common.schemas import YandexIntegrationUpdate
from services.control.app.api import router
from services.control.app.config import ControlSettings
from services.control.app.integrations import IntegrationsService
from services.control.app.models import AuditLog, IntegrationSecret, IntegrationSetting
from sqlalchemy import select

REDIRECT_URI = "https://api.example/api/v1/auth/yandex/callback"


@pytest.fixture
async def harness(tmp_path: Path):
    settings = ControlSettings(
        service_name="control-test",
        control_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'control.db').as_posix()}",
        control_secret_key="control-test-secret-that-is-long-enough",
        environment="development",
    )
    engine = create_engine(settings.control_dsn)
    await create_all(engine)
    service = IntegrationsService(settings, create_session_factory(engine))
    yield service, engine
    await engine.dispose()


async def _audit_actions(engine) -> list[AuditLog]:
    async with create_session_factory(engine)() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLog).order_by(AuditLog.created_at.asc())
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_yandex_values_are_encrypted_and_masked(harness) -> None:
    service, engine = harness
    created = await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="client-12345678",
            client_secret="secret-12345678",
            redirect_uri=REDIRECT_URI,
            enabled=True,
        )
    )

    assert created.configured is True
    assert created.enabled is True
    assert created.client_id.hint == "••••5678"
    assert created.client_secret.hint == "••••5678"
    assert created.redirect_uri == REDIRECT_URI
    serialized = created.model_dump_json()
    assert "client-12345678" not in serialized
    assert "secret-12345678" not in serialized

    async with create_session_factory(engine)() as session:
        rows = {
            row.name: row
            for row in (
                await session.scalars(select(IntegrationSecret))
            ).all()
        }
    assert rows["client_id"].value_encrypted != "client-12345678"
    assert rows["client_secret"].value_encrypted != "secret-12345678"
    assert service.box.decrypt(rows["client_secret"].value_encrypted) == "secret-12345678"
    assert service.box.decrypt(rows["redirect_uri"].value_encrypted) == REDIRECT_URI


@pytest.mark.asyncio
async def test_update_replaces_values_and_delete_removes_everything(harness) -> None:
    service, engine = harness
    await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="client-12345678",
            client_secret="secret-12345678",
            redirect_uri=REDIRECT_URI,
        )
    )
    replaced = await service.update_yandex(
        YandexIntegrationUpdate(client_secret="new-secret-9999")
    )
    assert replaced.client_secret.hint == "••••9999"
    assert replaced.client_id.hint == "••••5678"

    cleared = await service.update_yandex(YandexIntegrationUpdate(client_id=""))
    assert cleared.client_id.configured is False
    assert cleared.configured is False

    await service.delete_yandex()
    empty = await service.get_yandex()
    assert empty.configured is False
    assert empty.enabled is False
    async with create_session_factory(engine)() as session:
        assert (await session.scalars(select(IntegrationSecret))).all() == []
        assert (await session.scalars(select(IntegrationSetting))).all() == []

    actions = [entry.action for entry in await _audit_actions(engine)]
    assert "integration.yandex.updated" in actions
    assert "integration.yandex.deleted" in actions


@pytest.mark.asyncio
async def test_audit_never_contains_secret_values(harness) -> None:
    service, engine = harness
    await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="client-12345678",
            client_secret="secret-12345678",
            redirect_uri=REDIRECT_URI,
        )
    )
    await service.delete_yandex()
    payload = "\n".join(
        f"{entry.action} {entry.details}" for entry in await _audit_actions(engine)
    )
    assert "client-12345678" not in payload
    assert "secret-12345678" not in payload
    assert "••••" not in payload
    assert "integration.yandex.updated" in payload
    assert "integration.yandex.deleted" in payload


@pytest.mark.asyncio
async def test_test_endpoint_checks_shape_without_echoing_secrets(harness) -> None:
    service, _ = harness
    await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="client-12345678",
            client_secret="secret-12345678",
            redirect_uri=REDIRECT_URI,
            enabled=True,
        )
    )
    result = await service.test_yandex()
    assert result.ok is True
    assert result.configured is True
    assert result.enabled is True
    assert all(check.ok for check in result.checks)
    serialized = result.model_dump_json()
    assert "client-12345678" not in serialized
    assert "secret-12345678" not in serialized

    await service.update_yandex(YandexIntegrationUpdate(client_id=""))
    incomplete = await service.test_yandex()
    assert incomplete.ok is False
    assert any(not check.ok for check in incomplete.checks)


@pytest.mark.asyncio
async def test_credentials_are_db_only_and_respect_enabled(harness) -> None:
    service, _ = harness
    empty = await service.yandex_credentials()
    assert empty.source == "none"
    assert empty.enabled is False

    await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="db-client-12345678",
            client_secret="db-secret-12345678",
            redirect_uri=REDIRECT_URI,
            enabled=True,
        )
    )
    credentials = await service.yandex_credentials()
    assert credentials.source == "db"
    assert credentials.enabled is True
    assert credentials.client_id == "db-client-12345678"
    assert credentials.client_secret == "db-secret-12345678"

    await service.update_yandex(YandexIntegrationUpdate(enabled=False))
    disabled = await service.yandex_credentials()
    assert disabled.source == "db"
    assert disabled.enabled is False


@pytest.mark.asyncio
async def test_redirect_uri_shape_and_empty_update_are_validated(harness) -> None:
    service, _ = harness
    with pytest.raises(ValidationError) as wrong_path:
        await service.update_yandex(
            YandexIntegrationUpdate(redirect_uri="https://api.example/callback")
        )
    assert wrong_path.value.code == "invalid_redirect_uri"

    with pytest.raises(ValidationError) as empty:
        await service.update_yandex(YandexIntegrationUpdate())
    assert empty.value.code == "empty_integration_update"

    with pytest.raises(ValidationError):
        await service.update_yandex(YandexIntegrationUpdate(client_secret="short"))


@pytest.mark.asyncio
async def test_control_api_is_internal_only_and_credentials_are_internal(harness) -> None:
    service, _ = harness
    app = FastAPI()
    app.state.integrations = service
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    client = TestClient(app)

    unauthorized = client.get("/internal/integrations/yandex")
    assert unauthorized.status_code == 401

    headers = {"X-Internal-Token": get_settings().internal_token}
    saved = client.put(
        "/internal/integrations/yandex",
        headers=headers,
        json={
            "client_id": "client-12345678",
            "client_secret": "secret-12345678",
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert saved.status_code == 200
    assert "secret-12345678" not in saved.text
    assert saved.json()["client_secret"]["hint"] == "••••5678"

    credentials = client.get(
        "/internal/integrations/yandex/credentials", headers=headers
    )
    assert credentials.status_code == 200
    assert credentials.json()["source"] == "db"
    assert credentials.json()["client_secret"] == "secret-12345678"

    tested = client.post("/internal/integrations/yandex/test", headers=headers)
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert "secret-12345678" not in tested.text


@pytest.mark.asyncio
async def test_credentials_are_not_in_public_get(harness) -> None:
    service, _ = harness
    await service.update_yandex(
        YandexIntegrationUpdate(
            client_id="client-12345678",
            client_secret="secret-12345678",
            redirect_uri=REDIRECT_URI,
        )
    )
    payload = (await service.get_yandex()).model_dump()
    assert payload["client_id"]["hint"] == "••••5678"
    assert "value" not in payload["client_id"]
    assert payload["client_secret"]["hint"] == "••••5678"
