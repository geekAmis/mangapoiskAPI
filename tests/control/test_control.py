from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ConflictError
from services.control.app.config import ControlSettings
from services.control.app.crypto import SecretBox
from services.control.app.deployer import merge_deployed_services
from services.control.app.schemas import ServerCreate, ServerUpdate, ServiceSpec
from services.control.app.service import ControlService


def test_secret_box_roundtrip() -> None:
    box = SecretBox("unit-test-secret")
    encrypted = box.encrypt("super-secret-password")
    assert encrypted != "super-secret-password"
    assert box.decrypt(encrypted) == "super-secret-password"


def test_server_fields_reject_shell_injection() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ServerCreate(
            name="bad\n[Service]",
            host="127.0.0.1",
            username="root",
            password="secret",
        )
    with pytest.raises(ValidationError):
        ServerCreate(
            name="bad",
            host="127.0.0.1",
            username="root; rm -rf /",
            password="secret",
        )
    with pytest.raises(ValidationError):
        ServerCreate(
            name="bad",
            host="127.0.0.1",
            username="root",
            password="secret",
            bind_host="0.0.0.0\nExecStartPre=/bin/sh -c id",
        )


def test_partial_deploy_merges_inventory() -> None:
    assert merge_deployed_services(
        [("parser", 8101), ("catalog", 8102)], [("gateway", 8100)]
    ) == [("parser", 8101), ("catalog", 8102), ("gateway", 8100)]
    assert merge_deployed_services(
        [("parser", 8101), ("catalog", 8102)], [("parser", 8201)]
    ) == [("parser", 8201), ("catalog", 8102)]


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
            priority=10,
            services=[
                ServiceSpec(code="parser", port=8101),
                ServiceSpec(code="catalog", port=8102),
            ],
        )
    )
    assert created.name == "primary"
    assert created.priority == 10
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

    control_script = await service.deployer._build_script(
        await service._server_model(created.id), [("control", 8005)]
    )
    assert 'systemctl enable "mangapoisk-control.service"' in control_script
    assert "systemd-run" in control_script
    assert 'systemctl restart "mangapoisk-control.service"' not in control_script
    assert "ensurepip" in control_script
    assert "env/control.env" in control_script

    server_model = await service._server_model(created.id)
    base_env = service.deployer._env_file(server_model, "127.0.0.1", {})
    assert "ADMIN_PASSWORD" not in base_env
    assert "CONTROL_SECRET_KEY" not in base_env
    extras = service.deployer._service_env_files([("control", 8005)])
    assert "env/control.env" in extras
    assert "ADMIN_PASSWORD" in extras
    assert "CONTROL_SECRET_KEY" in extras

    with pytest.raises(ConflictError) as duplicate:
        await service.create(
            ServerCreate(
                name="primary-copy",
                host="127.0.0.1",
                username="root",
                password="another-secret",
            )
        )
    assert duplicate.value.code == "server_exists"
    assert "another-secret" not in str(duplicate.value.details)

    remote = await service.create(
        ServerCreate(
            name="edge",
            host="203.0.113.10",
            public_host="edge.example",
            username="root",
            password="secret",
            bind_host="0.0.0.0",
            priority=50,
            is_jump=True,
            services=[ServiceSpec(code="parser", port=8301)],
        )
    )
    await service.update(created.id, ServerUpdate(is_fallback=False))
    registry = await service.registry()
    assert registry.services["parser"][0].server_id == created.id
    assert registry.services["parser"][0].priority == 10
    edge_endpoint = next(
        item for item in registry.services["parser"] if item.server_id == remote.id
    )
    assert edge_endpoint.url == "http://edge.example:8301"

    await service.delete(created.id)
    await service.delete(remote.id)
    assert await service.servers() == []
    await engine.dispose()
