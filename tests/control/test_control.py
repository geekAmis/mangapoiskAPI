from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ConflictError
from services.control.app.config import ControlSettings
from services.control.app.crypto import SecretBox
from services.control.app.deployer import Deployer, merge_deployed_services
from services.control.app.repository import create_job, get_job
from services.control.app.schemas import ServerCreate, ServerUpdate, ServiceSpec
from services.control.app.service import ControlService
from services.control.app.ssh import SSHRunHandle


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


def test_deployer_env_uses_https_public_urls() -> None:
    settings = ControlSettings(
        service_name="control-test",
        environment="production",
        public_web_url="https://85.192.37.58.nip.io:8443",
        public_api_url="https://85.192.37.58.nip.io:8443/api/v1",
        control_secret_key="control-test-secret",
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    env = deployer._env_file(None, "85.192.37.58", {})

    assert "PUBLIC_WEB_URL=https://85.192.37.58.nip.io:8443\n" in env
    assert "PUBLIC_API_URL=https://85.192.37.58.nip.io:8443/api/v1\n" in env
    assert "REGISTRY_URL=https://85.192.37.58.nip.io:8443/api/v1/registry\n" in env
    assert "CORS_ORIGINS=https://85.192.37.58.nip.io:8443," in env
    assert "PUBLIC_WEB_URL=http://" not in env


def test_deployer_env_normalizes_api_base() -> None:
    settings = ControlSettings(
        service_name="control-test",
        public_web_url="https://manga.example",
        public_api_url="https://manga.example",
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    env = deployer._env_file(None, "manga.example", {})

    assert "PUBLIC_API_URL=https://manga.example/api/v1\n" in env
    assert "REGISTRY_URL=https://manga.example/api/v1/registry\n" in env


def test_ssh_handle_cancellation_closes_channel() -> None:
    class FakeChannel:
        closed = False

        def close(self) -> None:
            self.closed = True

    channel = FakeChannel()
    handle = SSHRunHandle(channel=channel)  # type: ignore[arg-type]
    handle.cancel()

    assert handle.cancel_event.is_set()
    assert channel.closed is True


def test_deploy_health_timeout_is_configurable() -> None:
    settings = ControlSettings(
        service_name="control-test",
        deploy_health_timeout_seconds=30,
        deploy_health_poll_seconds=2,
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    block = deployer._health_block("catalog", 8102)

    assert "timeout=30s" in block
    assert "attempts=15" in block
    assert "seq 1 15" in block
    assert "HEALTH_WAIT" in block
    assert "HEALTH_OK" in block
    assert "HEALTH_FAIL" in block


def test_default_deploy_health_timeout_is_long_enough() -> None:
    settings = ControlSettings()
    assert 300 <= settings.deploy_health_timeout_seconds <= 600
    assert settings.deploy_stale_job_seconds > settings.deploy_health_timeout_seconds


@pytest.mark.asyncio
async def test_deployer_script_includes_pre_start_command() -> None:
    settings = ControlSettings(
        service_name="control-test",
        deploy_pre_start_command="python -m app.migrate",
        deploy_pre_start_timeout_seconds=42,
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    server = SimpleNamespace(bind_host="127.0.0.1", public_host="127.0.0.1", host="127.0.0.1")

    class FakeControl:
        async def service_urls(self) -> dict[str, str]:
            return {}

    deployer.control = FakeControl()  # type: ignore[assignment]
    script = await deployer._build_script(server, [("catalog", 8102)])

    assert "python -m app.migrate" in script
    assert "timeout 42 bash -lc" in script


@pytest.mark.asyncio
async def test_long_startup_progress_keeps_job_green(tmp_path: Path) -> None:
    db_path = tmp_path / "control.db"
    settings = ControlSettings(
        service_name="control-test",
        control_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        control_secret_key="control-test-secret",
        deploy_health_timeout_seconds=30,
        deploy_health_poll_seconds=1,
        deploy_stale_job_seconds=60,
    )
    engine = create_engine(settings.control_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = ControlService(settings, session_factory)
    created = await service.create(
        ServerCreate(
            name="primary",
            host="127.0.0.1",
            username="root",
            password="secret",
            bind_host="127.0.0.1",
            services=[ServiceSpec(code="catalog", port=8102)],
        )
    )
    server = await service._server_model(created.id)

    class FakeSSH:
        def run_script(
            self,
            target,
            script,
            *,
            jump=None,
            on_line=None,
            timeout=1800.0,
            read_timeout=900.0,
            handle=None,
        ):
            lines = [
                "HEALTH_WAIT catalog:8102 timeout=30s attempts=30",
                "HEALTH_WAIT catalog:8102 attempt=20/30",
                "HEALTH_OK catalog:8102 attempt=21",
            ]
            for line in lines:
                if on_line:
                    on_line(line)
            return 0, "\n".join(lines)

    class FakeControl:
        async def service_urls(self) -> dict[str, str]:
            return {}

        async def health_check_all(self) -> list[object]:
            return []

    deployer = Deployer(settings, session_factory, service.box, FakeSSH(), FakeControl())
    job = await deployer.start(server, [("catalog", 8102)], update=True)
    for _ in range(100):
        await asyncio.sleep(0.02)
        async with session_factory() as session:
            row = await get_job(session, job.id)
        if row is not None and row.status in {"done", "failed"}:
            break
    assert row is not None
    assert row.status == "done", row.error
    assert "HEALTH_WAIT" in row.log
    assert "HEALTH_OK" in row.log
    assert row.requested["health_timeout_seconds"] == 30
    await deployer.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_and_cancelled_jobs_are_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "control.db"
    settings = ControlSettings(
        service_name="control-test",
        control_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        control_secret_key="control-test-secret",
        deploy_stale_job_seconds=60,
    )
    engine = create_engine(settings.control_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = ControlService(settings, session_factory)
    created = await service.create(
        ServerCreate(
            name="primary",
            host="127.0.0.1",
            username="root",
            password="secret",
            services=[ServiceSpec(code="catalog", port=8102)],
        )
    )
    async with session_factory() as session:
        stale_job = await create_job(session, created.id, {"services": []})
        stale_job.status = "running"
        stale_job.last_output_at = datetime.now(UTC) - timedelta(seconds=120)
        await session.commit()
        stale_id = stale_job.id

    assert await service.reap_stale_jobs() == 1
    async with session_factory() as session:
        row = await get_job(session, stale_id)
    assert row is not None
    assert row.status == "failed"
    assert "stalled" in (row.error or "")

    async with session_factory() as session:
        cancellable = await create_job(session, created.id, {"services": []})
        cancellable.status = "running"
        cancellable.last_output_at = datetime.now(UTC)
        await session.commit()
        cancellable_id = cancellable.id
    assert await service.deployer.cancel_job(cancellable_id, "cancelled by test")
    async with session_factory() as session:
        row = await get_job(session, cancellable_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "cancelled by test"
    await engine.dispose()


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
