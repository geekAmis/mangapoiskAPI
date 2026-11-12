from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from manga_common.config import Settings, get_settings
from manga_common.db import create_all, create_engine, create_session_factory
from services.control.app.config import ControlSettings
from services.control.app.console import (
    MAX_OUTPUT_BYTES,
    ConsolePolicy,
    ConsoleRejected,
)
from services.control.app.schemas import ConsoleRequest, ServerCreate, ServiceSpec
from services.control.app.service import ControlService
from services.control.app.ssh import SSHCommandResult, SSHRunner, SSHTarget

SERVICES = {"gateway": 8100, "catalog": 8102, "control": 8005}


def policy() -> ConsolePolicy:
    return ConsolePolicy(SERVICES, "/opt/mangapoisk-reborn")


@pytest.mark.parametrize(
    "command",
    [
        "systemctl status mangapoisk-gateway",
        "systemctl status --no-pager mangapoisk-gateway.service",
        "systemctl is-active mangapoisk-catalog",
        "systemctl is-failed mangapoisk-control.service",
        "journalctl -u mangapoisk-gateway -n 50 --no-pager",
        "journalctl -u mangapoisk-catalog -n 500",
        "docker ps",
        "ss -ltnp",
        "df -h",
        "free -h",
        "uptime",
        "curl -s 127.0.0.1:8100/health",
        "curl -fsS localhost:8102/health",
        "ls -la /opt/mangapoisk-reborn",
    ],
)
def test_allowlisted_commands_are_accepted(command: str) -> None:
    invocation = policy().parse_command(command)
    assert invocation.kind == "command"
    assert invocation.argv


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("systemctl status mangapoisk-gateway; rm -rf /", "console_injection"),
        ("systemctl status mangapoisk-gateway | sh", "console_injection"),
        ("systemctl status mangapoisk-gateway && id", "console_injection"),
        ("systemctl status mangapoisk-gateway $(id)", "console_injection"),
        ("systemctl status mangapoisk-gateway `id`", "console_injection"),
        ("systemctl status mangapoisk-gateway > /tmp/x", "console_injection"),
        ("systemctl status mangapoisk-gateway\nrm -rf /", "console_injection"),
        ("sudo systemctl restart mangapoisk-gateway", "console_command_denied"),
        ("rm -rf /opt/mangapoisk-reborn", "console_command_denied"),
        ("dd if=/dev/zero of=/dev/sda", "console_command_denied"),
        ("mkfs.ext4 /dev/sda1", "console_command_denied"),
        ("docker system prune -af", "console_command_denied"),
        ("apt-get update", "console_command_denied"),
        ("cat /opt/mangapoisk-reborn/.env", "console_secret_denied"),
        ("ls -la /opt/mangapoisk-reborn/.env", "console_secret_denied"),
        ("cat /root/.ssh/id_rsa", "console_secret_denied"),
        ("systemctl status Project-Kontur", "console_unit_denied"),
        ("systemctl status alpine", "console_unit_denied"),
        ("journalctl -u Project-Kontur -n 10", "console_unit_denied"),
        ("journalctl -u mangapoisk-gateway -n 100000", "console_command_denied"),
        ("curl -s 127.0.0.1:9999/health", "console_port_denied"),
        ("curl -s 127.0.0.1:8100/admin", "console_command_denied"),
        ("ls -la /etc", "console_path_denied"),
        ("uptime; id", "console_injection"),
    ],
)
def test_rejected_commands(command: str, code: str) -> None:
    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_command(command)
    assert exc.value.code == code


def test_structured_service_actions_are_limited_to_inventory() -> None:
    invocation = policy().parse_action("service_restart", {"service": "gateway"})
    assert invocation.argv == ("systemctl", "restart", "mangapoisk-gateway.service")

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("service_restart", {"service": "Project-Kontur"})
    assert exc.value.code == "console_service_denied"

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("service_stop", {"service": "alpine"})
    assert exc.value.code == "console_service_denied"

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("service_restart", {"service": "gateway", "unit": "x"})
    assert exc.value.code == "console_params"


def test_port_change_validates_range_and_collisions() -> None:
    assert policy().parse_action(
        "port_change", {"service": "gateway", "port": 1024}
    ).params["port"] == 1024
    assert policy().parse_action(
        "port_change", {"service": "gateway", "port": 65535}
    ).params["port"] == 65535

    for port in (80, 1023, 65_536, "abc", True, 8100.5):
        with pytest.raises(ConsoleRejected) as exc:
            policy().parse_action("port_change", {"service": "gateway", "port": port})
        assert exc.value.code == "console_port"

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("port_change", {"service": "gateway", "port": 8102})
    assert exc.value.code == "console_port_in_use"


def test_add_service_only_known_mangapoisk_services() -> None:
    invocation = policy().parse_action("add_service", {"service": "media", "port": 8104})
    assert invocation.params == {"service": "media", "port": 8104}

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("add_service", {"service": "gateway", "port": 8104})
    assert exc.value.code == "console_service_exists"

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("add_service", {"service": "postgres", "port": 5432})
    assert exc.value.code == "console_service_denied"

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("add_service", {"service": "media", "port": 8100})
    assert exc.value.code == "console_port_in_use"


def test_deploy_action_only_uses_inventory_services() -> None:
    invocation = policy().parse_action("deploy", {"services": ["gateway"]})
    assert invocation.params["services"] == ["gateway"]

    with pytest.raises(ConsoleRejected) as exc:
        policy().parse_action("deploy", {"services": ["Project-Kontur"]})
    assert exc.value.code == "console_service_denied"


def test_request_rejects_command_and_action_together() -> None:
    with pytest.raises(ConsoleRejected) as exc:
        policy().parse(
            ConsoleRequest(command="uptime", action="service_restart", params={})
        )
    assert exc.value.code == "console_ambiguous"


class _FakeSSH:
    def __init__(self, result: SSHCommandResult) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def run_command(self, target, argv, *, jump=None, timeout=30.0, max_output_bytes=200_000):
        self.calls.append((target, tuple(argv), timeout, max_output_bytes))
        return self.result


async def _service(tmp_path):
    settings = ControlSettings(
        service_name="control-console-test",
        control_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'control.db').as_posix()}",
        control_secret_key="console-test-secret",
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
            services=[
                ServiceSpec(code="gateway", port=8100),
                ServiceSpec(code="catalog", port=8102),
            ],
        )
    )
    return service, created, engine


@pytest.mark.asyncio
async def test_executor_runs_allowlisted_command_and_audits(tmp_path) -> None:
    service, created, engine = await _service(tmp_path)
    fake = _FakeSSH(SSHCommandResult(exit_code=0, output="active\n"))
    service.ssh = fake  # type: ignore[assignment]

    result = await service.console(
        created.id, ConsoleRequest(command="systemctl is-active mangapoisk-gateway")
    )

    assert result.ok is True
    assert result.exit_code == 0
    assert result.output == "active\n"
    assert result.output_hash
    assert fake.calls[0][1] == ("systemctl", "is-active", "mangapoisk-gateway")
    assert fake.calls[0][2] == 30.0
    assert fake.calls[0][3] == MAX_OUTPUT_BYTES

    history = await service.console_history(created.id)
    assert len(history) == 1
    details = history[0].details
    assert details["admin"] == "admin"
    assert details["exit_code"] == 0
    assert details["output_hash"] == result.output_hash
    assert "output" not in details
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_timeout_is_reported_and_audited(tmp_path) -> None:
    service, created, engine = await _service(tmp_path)
    fake = _FakeSSH(
        SSHCommandResult(
            exit_code=-1,
            output="partial\n[console] timeout after 30s",
            timed_out=True,
        )
    )
    service.ssh = fake  # type: ignore[assignment]

    result = await service.console(
        created.id,
        ConsoleRequest(command="journalctl -u mangapoisk-gateway -n 50"),
    )

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code == -1
    history = await service.console_history(created.id)
    assert history[0].details["timed_out"] is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_change_port_updates_inventory_and_starts_deploy(tmp_path, monkeypatch) -> None:
    from services.control.app.schemas import DeployResponse

    service, created, engine = await _service(tmp_path)
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async def fake_deploy(server_id, services, *, update=True):
        captured["server_id"] = server_id
        captured["services"] = services
        return DeployResponse(job_id=job_id, status="queued")

    monkeypatch.setattr(service, "deploy", fake_deploy)
    response = await service.change_port(created.id, "gateway", 8200)
    assert response.job_id == job_id
    assert captured["services"][0].port == 8200
    servers = await service.servers()
    ports = {item.code: item.port for item in servers[0].services}
    assert ports == {"gateway": 8200, "catalog": 8102}
    await engine.dispose()


@pytest.mark.asyncio
async def test_add_service_appends_inventory_and_starts_deploy(tmp_path, monkeypatch) -> None:
    from services.control.app.schemas import DeployResponse

    service, created, engine = await _service(tmp_path)
    job_id = uuid.uuid4()

    async def fake_deploy(server_id, services, *, update=True):
        assert services[0].code == "media"
        return DeployResponse(job_id=job_id, status="queued")

    monkeypatch.setattr(service, "deploy", fake_deploy)
    response = await service.add_service(created.id, "media", 8104)
    assert response.job_id == job_id
    servers = await service.servers()
    assert {item.code for item in servers[0].services} == {"gateway", "catalog", "media"}
    await engine.dispose()


def test_rollback_script_restores_previous_release() -> None:
    import asyncio

    from services.control.app.deployer import Deployer

    deployer = Deployer(ControlSettings(service_name="rollback-test"), None, None, None, None)  # type: ignore[arg-type]
    server = SimpleNamespace(
        services=[
            SimpleNamespace(code="gateway", port=8100),
            SimpleNamespace(code="catalog", port=8102),
        ]
    )
    script = asyncio.run(deployer._build_rollback_script(server))
    assert "$ROOT/src.old" in script
    assert 'mv "$ROOT/src.old" "$ROOT/src"' in script
    assert "mangapoisk-gateway.service" in script
    assert "mangapoisk-catalog.service" in script
    assert "ROLLBACK_OK" in script


@pytest.mark.asyncio
async def test_executor_audits_rejected_injection_without_raw_command(tmp_path) -> None:
    service, created, engine = await _service(tmp_path)
    with pytest.raises(ConsoleRejected):
        await service.console(
            created.id,
            ConsoleRequest(command="systemctl status mangapoisk-gateway; rm -rf /"),
        )
    history = await service.console_history(created.id)
    assert len(history) == 1
    details = history[0].details
    assert details["rejected"] == "console_injection"
    assert "command" not in details
    assert details["command_hash"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_action_starts_control_job(tmp_path, monkeypatch) -> None:
    from services.control.app.schemas import DeployResponse

    service, created, engine = await _service(tmp_path)
    job_id = uuid.uuid4()

    async def fake_deploy(server_id, services, *, update=True):
        assert services[0].code == "gateway"
        assert update is False
        return DeployResponse(job_id=job_id, status="queued")

    monkeypatch.setattr(service, "deploy", fake_deploy)
    result = await service.console(
        created.id,
        ConsoleRequest(action="deploy", params={"services": ["gateway"], "update": False}),
    )
    assert result.ok is True
    assert result.job_id == job_id
    history = await service.console_history(created.id)
    assert history[0].details["job_id"] == str(job_id)
    await engine.dispose()


def test_control_console_endpoint_requires_internal_token() -> None:
    from manga_common.service import create_service_app
    from services.control.app.api import router

    settings = Settings(internal_token="test-internal-token")
    app = create_service_app(settings=settings, title="test-control", description="test")
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    response = client.post(
        f"/internal/servers/{uuid.uuid4()}/console", json={"command": "uptime"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_token"


def test_admin_console_endpoint_requires_admin() -> None:
    from manga_common.service import create_service_app
    from services.gateway.app.api import router

    settings = Settings(
        internal_token="test-internal-token",
        jwt_secret="j" * 64,
        admin_password="strong-admin-password",
    )
    app = create_service_app(settings=settings, title="test-gateway", description="test")
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    url = f"/api/v1/admin/servers/{uuid.uuid4()}/console"

    anonymous = client.post(url, json={"command": "uptime"})
    assert anonymous.status_code == 401

    from manga_common.auth import create_access_token

    user_token, _ = create_access_token(settings, subject="user-1", role="user")
    forbidden = client.post(
        url, json={"command": "uptime"}, headers={"Authorization": f"Bearer {user_token}"}
    )
    assert forbidden.status_code == 403


class _FakeChannel:
    def __init__(
        self, chunks: list[bytes], exit_code: int = 0, *, exit_ready: bool | None = None
    ) -> None:
        self.chunks = list(chunks)
        self.exit_code = exit_code
        self.exit_ready = exit_ready
        self.closed = False

    def set_combine_stderr(self, _value: bool) -> None:
        return None

    def settimeout(self, _value: float) -> None:
        return None

    def recv(self, _size: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        raise TimeoutError

    def recv_ready(self) -> bool:
        return bool(self.chunks)

    def exit_status_ready(self) -> bool:
        if self.exit_ready is not None:
            return self.exit_ready
        return not self.chunks

    def recv_exit_status(self) -> int:
        return self.exit_code

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, channel: _FakeChannel) -> None:
        self.channel = channel

    def exec_command(self, command: str, timeout: float | None = None):
        assert command == "uptime"
        return (
            SimpleNamespace(channel=SimpleNamespace(shutdown_write=lambda: None)),
            SimpleNamespace(channel=self.channel),
            None,
        )

    def close(self) -> None:
        return None


def test_ssh_run_command_caps_output(monkeypatch) -> None:
    channel = _FakeChannel([b"a" * 120, b"b" * 120])
    runner = SSHRunner()
    monkeypatch.setattr(runner, "connect", lambda target, jump=None: _FakeClient(channel))
    result = runner.run_command(
        SSHTarget(host="127.0.0.1", port=22, username="root", password="x"),
        ("uptime",),
        timeout=5,
        max_output_bytes=150,
    )
    assert result.truncated is True
    assert result.timed_out is False
    assert len(result.output.split("\n[console]")[0]) == 150
    assert "[console] output truncated" in result.output
    assert channel.closed is True


def test_ssh_run_command_times_out(monkeypatch) -> None:
    channel = _FakeChannel([], exit_ready=False)
    runner = SSHRunner()
    monkeypatch.setattr(runner, "connect", lambda target, jump=None: _FakeClient(channel))
    result = runner.run_command(
        SSHTarget(host="127.0.0.1", port=22, username="root", password="x"),
        ("uptime",),
        timeout=0.05,
        max_output_bytes=100,
    )
    assert result.timed_out is True
    assert result.exit_code == -1
    assert "[console] timeout" in result.output
    assert channel.closed is True
