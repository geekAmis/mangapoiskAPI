from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from services.control.app.config import ControlSettings
from services.control.app.crypto import SecretBox
from services.control.app.schemas import ServerCreate, ServerUpdate, ServiceSpec
from services.control.app.service import ControlService


def test_secret_box_roundtrip() -> None:
    box = SecretBox("unit-test-secret")
    encrypted = box.encrypt("super-secret-password")
    assert encrypted != "super-secret-password"
    assert box.decrypt(encrypted) == "super-secret-password"


@pytest.mark.asyncio
async def test_server_crud_and_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "control.db"
    settings = ControlSettings(
        service_name="control-test",
        control_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        control_secret_key="control-test-secret",
    )
    engine = create_engine(settings.control_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = ControlService(settings, session_factory)

    created = await service.create(
        ServerCreate(
            name="primary",
            host="127.0.0.1",
            public_host="127.0.0.1",
            username="root",
            password="secret",
            bind_host="127.0.0.1",
            services=[
                ServiceSpec(code="parser", port=8101),
                ServiceSpec(code="catalog", port=8102),
            ],
        )
    )
    assert created.name == "primary"
    assert len(created.services) == 2

    servers = await service.servers()
    assert len(servers) == 1
    assert servers[0].host == "127.0.0.1"

    registry = await service.registry()
    assert "parser" in registry.services
    assert registry.services["parser"][0].url == "http://127.0.0.1:8101"

    updated = await service.update(
        created.id,
        ServerUpdate(is_fallback=True, services=[ServiceSpec(code="parser", port=8201)]),
    )
    assert updated.is_fallback is True
    assert updated.services[0].port == 8201

    script = await service.deployer._build_script(
        await service._server_model(created.id), [("parser", 8201)]
    )
    assert "DEPLOY_OK" in script
    assert "mangapoisp-parser" not in script
    assert "mangapoisk-parser.service" in script
    assert "8201" in script

    await service.delete(created.id)
    assert await service.servers() == []
    await engine.dispose()
