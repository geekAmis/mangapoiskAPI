from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from pydantic import ValidationError
from services.control.app.ai_supervisor import (
    MARKER_HEALTH,
    SUPERVISOR_MODEL,
    AISupervisor,
    SupervisorGuardError,
    SupervisorPolicy,
    audit_output,
    build_health_script,
    build_opencode_argv,
    build_prompt,
    build_remote_script,
    build_rollback_script,
    extract_changed_files,
    extract_shell_commands,
    is_full_deploy,
    parse_supervisor_output,
)
from services.control.app.config import ControlSettings
from services.control.app.deployer import Deployer
from services.control.app.repository import get_job, list_audit
from services.control.app.schemas import ServerCreate, ServiceSpec
from services.control.app.service import ControlService

SERVICES = [("catalog", 8102), ("gateway", 8100)]
POLICY = SupervisorPolicy()


def _prompt(**overrides):
    values = {
        "job_id": "job-123",
        "server_name": "primary-85",
        "server_host": "85.192.37.58",
        "services": SERVICES,
        "deploy_ok": True,
        "deploy_log": "HEALTH_OK catalog:8102\nHEALTH_OK gateway:8100\n",
        "policy": POLICY,
        "timeout_seconds": 900,
        "max_iterations": 2,
        "round_number": 1,
    }
    values.update(overrides)
    return build_prompt(**values)


def test_policy_allows_expected_diagnostics() -> None:
    for command in [
        "systemctl is-active mangapoisk-catalog.service",
        "systemctl status mangapoisk-catalog.service --no-pager",
        "systemctl restart mangapoisk-catalog.service",
        "journalctl -u mangapoisk-catalog.service -n 200 --no-pager",
        "curl -fsS http://127.0.0.1:8102/health",
        "curl -fsS --max-time 5 http://127.0.0.1:8102/health",
        "tail -n 100 /opt/mangapoisk-reborn/logs/ai-supervisor-job-123.log",
        "grep -n ERROR /opt/mangapoisk-reborn/logs/app.log",
        "df -h",
        "free -m",
    ]:
        assert POLICY.allows("shell", command), command


def test_policy_denies_foreign_services_and_destructive_commands() -> None:
    for command in [
        "systemctl restart Project-Kontur.service",
        "systemctl restart nginx",
        "systemctl stop mangapoisk-catalog.service",
        "systemctl disable mangapoisk-catalog.service",
        "systemctl daemon-reload",
        "rm -rf /opt/mangapoisk-reborn",
        "docker system prune -af",
        "apt-get upgrade -y",
        "cat /opt/mangapoisk-reborn/.env",
        "cat /opt/mangapoisk-reborn/logs/../../etc/shadow",
        "python -m py_compile /opt/mangapoisk-reborn/src/../../etc/foo.py",
        "pip install -r /opt/mangapoisk-reborn/src/services/../../evil/requirements.txt",
        "sqlite3 /opt/mangapoisk-reborn/data/catalog.db 'delete from titles'",
        "systemctl restart mangapoisk-catalog; systemctl restart nginx",
        "systemctl restart mangapoisk-catalog.service nginx",
        "journalctl -u mangapoisk-catalog -u nginx",
        "journalctl -u mangapoisk-catalog --unit nginx",
        "journalctl -u mangapoisk-catalog --user-unit nginx",
        "journalctl -u mangapoisk-catalog --vacuum-size=1G",
        "journalctl -u mangapoisk-catalog -f",
        "journalctl -u mangapoisk-catalog --follow",
        "tail -n 100 -f /opt/mangapoisk-reborn/logs/app.log",
        "sed -n -i 's/x/y/' /opt/mangapoisk-reborn/logs/app.log",
        "journalctl -u mangapoisk-catalog | grep error",
        "curl -fsS http://127.0.0.1:8102/health -o /tmp/out",
        "curl -fsS http://127.0.0.1:8102/internal/stats",
        "bash -c 'systemctl restart nginx'",
        "ufw disable",
        "iptables -F",
        "chmod 777 /opt/mangapoisk-reborn",
    ]:
        assert not POLICY.allows("shell", command), command


def test_policy_denies_secret_reads_and_writes() -> None:
    assert not POLICY.allows("read", "/opt/mangapoisk-reborn/.env")
    assert not POLICY.allows("read", ".env")
    assert not POLICY.allows("read", "env/control.env")
    assert not POLICY.allows("read", "/opt/mangapoisk-reborn/data/catalog.db")
    assert not POLICY.allows("read", "src/services/catalog/env/secret")
    assert not POLICY.allows("read", "src/services/catalog/data/file")
    assert not POLICY.allows("read", "src/services/catalog/foo.env")
    assert not POLICY.allows("read", "src/../../etc/passwd")
    assert not POLICY.allows("read", "src/id_rsa")
    assert not POLICY.allows("read", "src/app.key")
    assert not POLICY.allows("read", "src/secrets.yaml")
    assert not POLICY.allows("edit", "/opt/mangapoisk-reborn/.env")
    assert not POLICY.allows("edit", "/opt/mangapoisk-reborn/data/catalog.db")
    assert POLICY.allows("edit", "/opt/mangapoisk-reborn/src/services/catalog/app/main.py")
    assert POLICY.allows("read", "src/services/catalog/app/main.py")
    assert POLICY.allows(
        "read", "/opt/mangapoisk-reborn/run/ai-supervisor-job-123.md"
    )
    assert POLICY.allows("read", "run/ai-supervisor-job-123.md")


def test_config_is_fail_closed_and_uses_only_free_model() -> None:
    config = POLICY.build_config()
    assert config["model"] == SUPERVISOR_MODEL
    assert config["default_agent"] == "deploy-supervisor"
    assert config["update"] == "disable"
    assert config["permissions"][0] == {
        "action": "*",
        "resource": "*",
        "effect": "deny",
    }
    assert all(
        rule["action"] != "shell" or rule["effect"] in {"allow", "deny"}
        for rule in config["permissions"]
    )
    assert "deepseek-v4.1-flash-free" in json.dumps(config)
    assert "gpt-" not in json.dumps(config)
    assert "claude-" not in json.dumps(config)


def test_installer_config_matches_policy(repo_root: Path) -> None:
    text = (repo_root / "scripts/ops/install_opencode.sh").read_text(encoding="utf-8")
    block = text.split("# BEGIN MANAGED OPENCODE CONFIG", 1)[1].split(
        "# END MANAGED OPENCODE CONFIG", 1
    )[0]
    match = re.search(r"<<'JSON'\n(.*?)\nJSON", block, re.S)
    assert match is not None
    assert json.loads(match.group(1)) == POLICY.build_config()

    agent = text.split("<<'AGENTEOF'\n", 1)[1].split("\nAGENTEOF", 1)[0]
    assert agent.replace("@MAX_STEPS@", str(POLICY.max_steps)).strip() == (
        POLICY.build_agent_markdown().strip()
    )
    skill = text.split("<<'SKILLEOF'\n", 1)[1].split("\nSKILLEOF", 1)[0]
    assert skill.strip() == POLICY.build_skill_markdown().strip()


def test_installer_never_writes_secrets(repo_root: Path) -> None:
    text = (repo_root / "scripts/ops/install_opencode.sh").read_text(encoding="utf-8")
    assert "OPENCODE_API_KEY=" not in text
    assert "CONTROL_SECRET_KEY=" not in text
    assert "JWT_SECRET=" not in text
    assert "INTERNAL_TOKEN=" not in text


def test_prompt_contains_context_and_boundaries() -> None:
    prompt = _prompt(deploy_log="traceback: boom\nHEALTH_FAIL catalog:8102\n")
    assert "job-123" in prompt
    assert "primary-85" in prompt
    assert "mangapoisk-catalog" in prompt
    assert "mangapoisk-gateway" in prompt
    assert "traceback: boom" in prompt
    assert "Project-Kontur" in prompt
    assert "rm -rf" in prompt
    assert ".env" in prompt
    assert "untrusted" in prompt
    assert "AI_SUPERVISOR_RESULT" in prompt
    assert "1 / 2" in prompt


def test_prompt_rejects_foreign_service() -> None:
    with pytest.raises(SupervisorGuardError):
        _prompt(services=[("Project-Kontur", 1234)])


def test_remote_script_has_bounded_runner_and_markers() -> None:
    prompt = _prompt()
    script = build_remote_script(
        job_id="job-123",
        prompt=prompt,
        services=SERVICES,
        policy=POLICY,
        timeout_seconds=420,
    )
    assert "timeout" in script
    assert "opencode" in script
    assert SUPERVISOR_MODEL in script
    assert "deploy-supervisor" in script
    assert "--auto" in script
    assert "--format json" in script
    assert "--file" in script
    assert "AI_SUPERVISOR_START" in script
    assert "AI_SUPERVISOR_SKIPPED" in script
    assert "AI_SUPERVISOR_TIMEOUT" in script
    assert "AI_SUPERVISOR_EXIT" in script
    assert "Project-Kontur" not in script.split("cat > \"$PROMPT_FILE\"", 1)[0]


def test_remote_script_rejects_paid_model() -> None:
    with pytest.raises(SupervisorGuardError):
        build_opencode_argv(
            opencode_bin="opencode",
            prompt_file="/opt/mangapoisk-reborn/run/prompt.md",
            message="go",
            model="opencode/deepseek-v4-pro",
        )


def test_remote_script_rejects_unsafe_timeout() -> None:
    with pytest.raises(SupervisorGuardError):
        build_remote_script(
            job_id="job-123",
            prompt="x",
            services=SERVICES,
            policy=POLICY,
            timeout_seconds=10,
        )


def test_parse_recovered_report() -> None:
    output = """
AI_SUPERVISOR_START job=job-123
AI_SUPERVISOR_RESULT=recovered
AI_SUPERVISOR_SUMMARY=catalog restarted after a missing import
AI_SUPERVISOR_ACTIONS=read journal; fixed import; restarted catalog
AI_SUPERVISOR_EXIT=0
AI_SUPERVISOR_DONE
"""
    parsed = parse_supervisor_output(output)
    assert parsed["status"] == "recovered"
    assert parsed["summary"] == "catalog restarted after a missing import"
    assert parsed["actions"] == ["read journal", "fixed import", "restarted catalog"]
    assert parsed["exit_code"] == 0
    assert parsed["timed_out"] is False


def test_parse_timeout_and_skip() -> None:
    timeout = parse_supervisor_output(
        "AI_SUPERVISOR_START\nAI_SUPERVISOR_EXIT=124\nAI_SUPERVISOR_TIMEOUT\n"
    )
    assert timeout["status"] == "timeout"
    assert timeout["timed_out"] is True

    skipped = parse_supervisor_output(
        "AI_SUPERVISOR_SKIPPED free_model_unavailable\n"
    )
    assert skipped["status"] == "skipped"
    assert skipped["skipped_reason"] == "free_model_unavailable"

    quota = parse_supervisor_output(
        "Error: Free usage limit reached. Connect a provider.\nAI_SUPERVISOR_EXIT=1\n"
    )
    assert quota["status"] == "skipped"
    assert quota["skipped_reason"] == "free_usage_limit"


def test_audit_detects_forbidden_tool_command() -> None:
    event = json.dumps(
        {
            "type": "tool",
            "part": {
                "tool": "shell",
                "state": {"input": {"command": "systemctl restart Project-Kontur.service"}},
            },
        }
    )
    violations = audit_output(event, POLICY)
    assert violations
    assert "Project-Kontur" in violations[0]["command"]


def test_audit_allows_mangapoisk_restart() -> None:
    event = json.dumps(
        {
            "type": "tool",
            "part": {
                "tool": "shell",
                "state": {"input": {"command": "systemctl restart mangapoisk-catalog.service"}},
            },
        }
    )
    assert audit_output(event, POLICY) == []
    assert extract_shell_commands(event) == ["systemctl restart mangapoisk-catalog.service"]


def test_audit_allows_read_only_log_search_for_forbidden_words() -> None:
    for command in (
        "grep -n nginx /opt/mangapoisk-reborn/logs/app.log",
        'grep -n "/data/" /opt/mangapoisk-reborn/logs/app.log',
    ):
        event = json.dumps(
            {
                "type": "tool",
                "part": {
                    "tool": "shell",
                    "state": {"input": {"command": command}},
                },
            }
        )
        assert audit_output(event, POLICY) == []


def test_extract_changed_files() -> None:
    event = json.dumps(
        {
            "type": "tool",
            "part": {
                "tool": "edit",
                "state": {
                    "input": {
                        "filePath": "/opt/mangapoisk-reborn/src/services/catalog/app/main.py"
                    }
                },
            },
        }
    )
    assert extract_changed_files(event) == [
        "/opt/mangapoisk-reborn/src/services/catalog/app/main.py"
    ]


def test_full_deploy_detection() -> None:
    assert is_full_deploy([("catalog", 8102), ("gateway", 8100)], ["catalog", "gateway"])
    assert not is_full_deploy([("catalog", 8102)], ["catalog", "gateway"])
    assert not is_full_deploy([], ["catalog"])
    assert is_full_deploy(
        [(code, 8000) for code in ("parser", "catalog", "library", "media", "control", "gateway", "notifier", "replica", "comments", "scheduler")],
        [],
    )


def test_settings_reject_paid_model_and_bad_timeouts() -> None:
    with pytest.raises(ValidationError):
        ControlSettings(ai_supervisor_model="opencode/deepseek-v4-pro")
    with pytest.raises(ValidationError):
        ControlSettings(
            ai_supervisor_timeout_seconds=120,
            ai_supervisor_round_timeout_seconds=300,
        )
    with pytest.raises(ValidationError):
        ControlSettings(
            environment="production",
            deploy_root="/srv/mangapoisk-reborn",
            public_web_url="https://manga.example",
            public_api_url="https://manga.example",
        )


class FakeRunner:
    """Deterministic runner for the supervisor loop; no SSH and no network."""

    def __init__(
        self,
        *,
        health_ok: bool = True,
        health_after: bool | None = None,
        supervisor_output: str = "AI_SUPERVISOR_RESULT=healthy\n",
        supervisor_error: Exception | None = None,
        rollback_output: str = "AI_ROLLBACK_DONE\n",
    ) -> None:
        self.health_ok = health_ok
        self.health_after = health_after
        self.supervisor_output = supervisor_output
        self.supervisor_error = supervisor_error
        self.rollback_output = rollback_output
        self.calls: list[str] = []

    async def __call__(self, script: str, timeout: float, read_timeout: float):
        self.calls.append(script)
        if "AI_SUPERVISOR_START" in script:
            if self.supervisor_error is not None:
                raise self.supervisor_error
            if self.health_after is not None:
                self.health_ok = self.health_after
            return 0, self.supervisor_output
        if "AI_ROLLBACK" in script:
            return 0, self.rollback_output
        if MARKER_HEALTH in script:
            return 0, f"{MARKER_HEALTH}={1 if self.health_ok else 0}\n"
        return 0, ""


@pytest.mark.asyncio
async def test_dry_run_does_not_execute() -> None:
    runner = FakeRunner()
    supervisor = AISupervisor(policy=POLICY, dry_run=True)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=True,
        deploy_log="HEALTH_OK",
        run_script=runner,
    )
    assert report["status"] == "dry_run"
    assert runner.calls == []
    assert report["model"] == SUPERVISOR_MODEL


@pytest.mark.asyncio
async def test_supervisor_runs_after_healthy_deploy_by_default() -> None:
    runner = FakeRunner(health_ok=True, supervisor_output="AI_SUPERVISOR_RESULT=healthy\n")
    supervisor = AISupervisor(policy=POLICY)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=True,
        deploy_log="HEALTH_OK",
        run_script=runner,
    )
    assert report["status"] == "healthy"
    assert any("AI_SUPERVISOR_START" in call for call in runner.calls)


@pytest.mark.asyncio
async def test_supervisor_can_skip_when_healthy() -> None:
    runner = FakeRunner(health_ok=True)
    supervisor = AISupervisor(policy=POLICY, skip_when_healthy=True)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=True,
        deploy_log="HEALTH_OK",
        run_script=runner,
    )
    assert report["status"] == "healthy"
    assert all("AI_SUPERVISOR_START" not in call for call in runner.calls)


@pytest.mark.asyncio
async def test_supervisor_skips_gracefully_when_model_is_missing() -> None:
    runner = FakeRunner(
        health_ok=False,
        supervisor_output="AI_SUPERVISOR_SKIPPED free_model_unavailable\n",
    )
    supervisor = AISupervisor(policy=POLICY)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=False,
        deploy_log="HEALTH_FAIL",
        run_script=runner,
    )
    assert report["status"] == "skipped"
    assert report["skipped_reason"] == "free_model_unavailable"
    assert report["rollback"] is None


@pytest.mark.asyncio
async def test_supervisor_timeout_triggers_bounded_rollback() -> None:
    runner = FakeRunner(supervisor_error=TimeoutError("round timeout"), health_ok=False)
    supervisor = AISupervisor(
        policy=POLICY,
        timeout_seconds=120,
        round_timeout_seconds=60,
        max_iterations=1,
    )
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=False,
        deploy_log="HEALTH_FAIL",
        run_script=runner,
    )
    assert report["status"] == "timeout"
    assert report["timed_out"] is True
    assert report["rollback"]["attempted"] is True
    assert report["rollback"]["ok"] is True
    assert any("AI_ROLLBACK" in call for call in runner.calls)


@pytest.mark.asyncio
async def test_supervisor_timeout_on_healthy_deploy_does_not_rollback() -> None:
    runner = FakeRunner(supervisor_error=TimeoutError("round timeout"), health_ok=True)
    supervisor = AISupervisor(
        policy=POLICY,
        timeout_seconds=120,
        round_timeout_seconds=60,
        max_iterations=1,
    )
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=True,
        deploy_log="HEALTH_OK",
        run_script=runner,
    )
    assert report["status"] == "healthy"
    assert report["rollback"] is None
    assert all("AI_ROLLBACK" not in call for call in runner.calls)


@pytest.mark.asyncio
async def test_supervisor_recovers_failed_deploy() -> None:
    runner = FakeRunner(
        health_ok=False,
        health_after=True,
        supervisor_output=(
            "AI_SUPERVISOR_RESULT=recovered\n"
            "AI_SUPERVISOR_SUMMARY=restarted catalog\n"
            "AI_SUPERVISOR_ACTIONS=checked logs; restarted catalog\n"
        ),
    )
    supervisor = AISupervisor(policy=POLICY)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=False,
        deploy_log="HEALTH_FAIL",
        run_script=runner,
    )
    assert report["status"] == "recovered"
    assert report["summary"] == "restarted catalog"
    assert report["actions"] == ["checked logs", "restarted catalog"]
    assert report["rollback"] is None


@pytest.mark.asyncio
async def test_supervisor_forbidden_command_fails_and_rolls_back() -> None:
    event = json.dumps(
        {
            "type": "tool",
            "part": {
                "tool": "shell",
                "state": {"input": {"command": "systemctl restart Project-Kontur.service"}},
            },
        }
    )
    runner = FakeRunner(health_ok=False, supervisor_output=event + "\n")
    supervisor = AISupervisor(policy=POLICY)
    report = await supervisor.run(
        job_id="job-123",
        server_name="primary-85",
        server_host="85.192.37.58",
        services=SERVICES,
        deploy_ok=False,
        deploy_log="HEALTH_FAIL",
        run_script=runner,
    )
    assert report["status"] == "failed"
    assert report["guard_violations"]
    assert report["rollback"]["ok"] is True


def test_health_and_rollback_scripts_stay_in_scope() -> None:
    health = build_health_script(SERVICES, POLICY)
    rollback = build_rollback_script(SERVICES, POLICY)
    assert "mangapoisk-catalog.service" in health
    assert "mangapoisk-gateway.service" in health
    assert "Project-Kontur" not in health
    assert "nginx" not in health
    assert "mangapoisk-catalog.service" in rollback
    assert "mangapoisk-gateway.service" in rollback
    assert "sqlite3" not in rollback
    assert "data/" not in rollback
    assert "rm -rf" not in rollback


def test_fake_opencode_binary_receives_prompt_file(tmp_path: Path) -> None:
    fake = tmp_path / "fake_opencode.py"
    fake.write_text(
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "prompt = pathlib.Path(args[args.index('--file') + 1]).read_text(encoding='utf-8')\n"
        "pathlib.Path(__file__).with_suffix('.json').write_text(\n"
        "    json.dumps({'args': args, 'prompt': prompt}), encoding='utf-8')\n"
        "print('AI_SUPERVISOR_RESULT=healthy')\n"
        "print('AI_SUPERVISOR_SUMMARY=fake ok')\n",
        encoding="utf-8",
    )
    prompt_file = tmp_path / "brief.md"
    prompt = _prompt()
    prompt_file.write_text(prompt, encoding="utf-8")
    argv = build_opencode_argv(
        opencode_bin="opencode",
        prompt_file=str(prompt_file),
        message="follow the brief",
        title="deploy-supervisor job-123",
    )
    # Execute the fake "binary" through the Python interpreter so the test is
    # cross-platform; the arguments are exactly those the real CLI receives.
    completed = subprocess.run(
        [sys.executable, str(fake), *argv[1:]],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "AI_SUPERVISOR_RESULT=healthy" in completed.stdout
    captured = json.loads(fake.with_suffix(".json").read_text(encoding="utf-8"))
    assert captured["args"][:2] == ["run", "--agent"]
    assert SUPERVISOR_MODEL in captured["args"]
    assert "--auto" in captured["args"]
    assert "--format" in captured["args"]
    assert captured["prompt"] == prompt


def test_deployer_only_runs_supervisor_for_full_inventory() -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
        ai_supervisor_enabled=True,
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    server = SimpleNamespace(
        services=[SimpleNamespace(code="catalog"), SimpleNamespace(code="gateway")]
    )
    assert deployer._should_run_supervisor(server, [("catalog", 8102), ("gateway", 8100)])
    assert not deployer._should_run_supervisor(server, [("catalog", 8102)])
    settings.ai_supervisor_full_deploy_only = False
    assert deployer._should_run_supervisor(server, [("catalog", 8102)])


def test_control_unit_loads_operator_ai_override_last() -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
    )
    deployer = Deployer(settings, None, None, None, None)  # type: ignore[arg-type]
    unit = deployer._unit_file("/opt/mangapoisk-reborn", "mangapoisk", "127.0.0.1", "control", 8005)
    assert "EnvironmentFile=-/opt/mangapoisk-reborn/env/control.env" in unit
    assert "EnvironmentFile=-/opt/mangapoisk-reborn/env/ai-supervisor.env" in unit
    assert unit.index("ai-supervisor.env") > unit.index("control.env")
    gateway = deployer._unit_file(
        "/opt/mangapoisk-reborn", "mangapoisk", "127.0.0.1", "gateway", 8100
    )
    assert "ai-supervisor.env" not in gateway


@pytest.mark.asyncio
async def test_deploy_script_can_install_opencode_before_units() -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
        ai_supervisor_install_opencode=True,
    )

    class FakeControl:
        async def service_urls(self) -> dict[str, str]:
            return {}

    server = SimpleNamespace(
        bind_host="127.0.0.1",
        public_host="127.0.0.1",
        host="127.0.0.1",
        services=[SimpleNamespace(code="catalog")],
    )
    deployer = Deployer(settings, None, None, None, FakeControl())  # type: ignore[arg-type]
    script = await deployer._build_script(server, [("catalog", 8102)])
    assert "install_opencode.sh" in script
    assert "--skip-auth-check" in script
    assert "OPENCODE_INSTALL_OK" in script

    settings.ai_supervisor_install_opencode = False
    deployer = Deployer(settings, None, None, None, FakeControl())  # type: ignore[arg-type]
    script = await deployer._build_script(server, [("catalog", 8102)])
    assert "install_opencode.sh" not in script


@pytest.mark.asyncio
async def test_control_self_deploy_defers_restart_until_after_supervisor() -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
        ai_supervisor_enabled=True,
    )

    class FakeControl:
        async def service_urls(self) -> dict[str, str]:
            return {}

    server = SimpleNamespace(
        bind_host="127.0.0.1",
        public_host="127.0.0.1",
        host="127.0.0.1",
        services=[SimpleNamespace(code="control"), SimpleNamespace(code="gateway")],
    )
    deployer = Deployer(settings, None, None, None, FakeControl())  # type: ignore[arg-type]
    script = await deployer._build_script(server, [("control", 8005), ("gateway", 8100)])
    assert "--on-active=1500" in script
    assert "mangapoisk-control-restart-fallback" in script

    settings.ai_supervisor_enabled = False
    deployer = Deployer(settings, None, None, None, FakeControl())  # type: ignore[arg-type]
    script = await deployer._build_script(server, [("control", 8005), ("gateway", 8100)])
    assert "--on-active=5" in script


class _DeploySSH:
    def __init__(self, supervisor_output: str, deploy_code: int = 0) -> None:
        self.supervisor_output = supervisor_output
        self.deploy_code = deploy_code
        self.scripts: list[str] = []

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
        self.scripts.append(script)
        if "AI_SUPERVISOR_START" in script:
            lines = self.supervisor_output.splitlines()
        elif "AI_HEALTH_RESULT" in script:
            lines = ["AI_HEALTH_RESULT=1"]
        else:
            lines = ["HEALTH_OK catalog:8102", "HEALTH_OK gateway:8100"]
        for line in lines:
            if on_line:
                on_line(line)
        return self.deploy_code, "\n".join(lines)


class _DeployControl:
    async def service_urls(self) -> dict[str, str]:
        return {}

    async def health_check_all(self) -> list[object]:
        return []


async def _run_full_deploy(tmp_path: Path, settings: ControlSettings, ssh: _DeploySSH):
    db_path = tmp_path / "control.db"
    settings.control_database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
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
            services=[
                ServiceSpec(code="catalog", port=8102),
                ServiceSpec(code="gateway", port=8100),
            ],
        )
    )
    server = await service._server_model(created.id)
    deployer = Deployer(settings, session_factory, service.box, ssh, _DeployControl())
    job = await deployer.start(
        server, [("catalog", 8102), ("gateway", 8100)], update=True
    )
    row = None
    for _ in range(200):
        await asyncio.sleep(0.02)
        async with session_factory() as session:
            row = await get_job(session, job.id)
        if row is not None and row.status in {"done", "failed"}:
            break
    async with session_factory() as session:
        audits = await list_audit(session, 20)
    await deployer.close()
    await engine.dispose()
    return row, audits


@pytest.mark.asyncio
async def test_deployer_stores_supervisor_report_and_audit(tmp_path: Path) -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
        ai_supervisor_enabled=True,
    )
    ssh = _DeploySSH(
        "AI_SUPERVISOR_RESULT=healthy\n"
        "AI_SUPERVISOR_SUMMARY=all deployed services are healthy\n"
        "AI_SUPERVISOR_ACTIONS=checked units; checked health\n"
        '{"type":"tool","part":{"tool":"shell","state":{"input":'
        '{"command":"systemctl is-active mangapoisk-catalog.service"}}}}\n'
    )
    row, audits = await _run_full_deploy(tmp_path, settings, ssh)
    assert row is not None
    assert row.status == "done", row.error
    report = row.requested["supervisor"]
    assert report["status"] == "healthy"
    assert report["summary"] == "all deployed services are healthy"
    assert report["actions"] == ["checked units", "checked health"]
    assert report["shell_commands"] == ["systemctl is-active mangapoisk-catalog.service"]
    assert "== AI supervisor ==" in row.log
    assert any(item.action == "ai_supervisor.finished" for item in audits)


@pytest.mark.asyncio
async def test_required_supervisor_skip_fails_the_job(tmp_path: Path) -> None:
    settings = ControlSettings(
        service_name="control-test",
        control_secret_key="control-test-secret",
        ai_supervisor_enabled=True,
        ai_supervisor_required=True,
    )
    ssh = _DeploySSH("AI_SUPERVISOR_SKIPPED free_model_unavailable\n")
    row, _audits = await _run_full_deploy(tmp_path, settings, ssh)
    assert row is not None
    assert row.status == "failed"
    assert "required" in (row.error or "")
    assert row.requested["supervisor"]["status"] == "skipped"
