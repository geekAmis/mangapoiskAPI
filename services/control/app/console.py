"""Restricted server console.

The admin terminal is deliberately **not** a shell.  Every request is parsed
against a small allowlist and executed as an argv vector over SSH.  Anything
that looks like shell syntax, a secret, a non-MangaPoisk service or a
structured action outside the policy is rejected before a connection is made.

Audit records never contain command output or secret values; they keep the
command/action, exit code, duration and a SHA-256 hash of the output.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shlex
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, get_args

from manga_common.errors import UpstreamError, ValidationError

from .repository import audit, audit_out, list_console_audit
from .schemas import (
    AuditOut,
    ConsoleRequest,
    ConsoleResultOut,
    DeployResponse,
    ServiceCode,
    ServiceSpec,
)

if TYPE_CHECKING:
    from .config import ControlSettings
    from .service import ControlService

MAX_COMMAND_CHARS = 1000
MAX_OUTPUT_BYTES = 200_000
COMMAND_TIMEOUT_SECONDS = 30.0
MAX_JOURNAL_LINES = 500
MIN_PORT = 1024
MAX_PORT = 65_535

_UNIT_RE = re.compile(r"^mangapoisk-[a-z0-9][a-z0-9-]*(?:\.service)?$")
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ADMIN_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_PARAM_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_CURL_RE = re.compile(
    r"^(?:http://)?(?P<host>127\.0\.0\.1|localhost):(?P<port>\d{2,5})/health$"
)

# Characters that let a client escape an argv vector.  Rejecting them early is
# both a safety net and a clear UX signal ("console is not a shell").
_SHELL_META = frozenset(";|&$><`\\\"'\n\r\t(){}[]*?!#~")
_BLOCKED_TOKENS = frozenset(
    {
        "apt",
        "apt-get",
        "awk",
        "bash",
        "chmod",
        "chown",
        "crontab",
        "dd",
        "docker-compose",
        "env",
        "export",
        "find",
        "kill",
        "killall",
        "mkfs",
        "mount",
        "nc",
        "netcat",
        "nmap",
        "passwd",
        "perl",
        "pkill",
        "prune",
        "python",
        "python3",
        "reboot",
        "rm",
        "rmdir",
        "ruby",
        "scp",
        "sed",
        "sh",
        "shutdown",
        "ssh",
        "sudo",
        "tee",
        "umount",
        "useradd",
        "wget",
        "zsh",
    }
)
_SENSITIVE_MARKERS = (
    ".env",
    "authorized_keys",
    "id_rsa",
    "passwd",
    "password",
    "private_key",
    "secret",
    "token",
)

_ALLOWED_SERVICE_CODES = frozenset(get_args(ServiceCode))
_ACTIONS = frozenset(
    {
        "add_service",
        "deploy",
        "port_change",
        "rollback",
        "service_restart",
        "service_start",
        "service_stop",
    }
)
_SERVICE_ACTION_VERBS = {
    "service_start": "start",
    "service_stop": "stop",
    "service_restart": "restart",
}


class ConsoleRejected(ValidationError):
    """Raised when a console request falls outside the allowlist."""

    def __init__(self, message: str, *, code: str = "console_rejected") -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class ConsoleInvocation:
    kind: Literal["command", "action"]
    action: str
    argv: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    label: str = ""


def _normalize_admin(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate if _ADMIN_RE.fullmatch(candidate) else "admin"


class ConsolePolicy:
    """Pure allowlist parser; no I/O and no SSH credentials."""

    def __init__(
        self,
        services: dict[str, int],
        deploy_root: str = "/opt/mangapoisk-reborn",
    ) -> None:
        self.services = dict(services)
        self.deploy_root = (deploy_root or "/opt/mangapoisk-reborn").rstrip("/") or "/"
        self.ports = set(self.services.values())

    # -- public ---------------------------------------------------------
    def parse(self, payload: ConsoleRequest) -> ConsoleInvocation:
        has_command = payload.command is not None
        has_action = payload.action is not None
        if has_command and has_action:
            raise ConsoleRejected(
                "Укажите либо command, либо action — не оба одновременно.",
                code="console_ambiguous",
            )
        if has_command:
            return self.parse_command(payload.command or "")
        if has_action:
            return self.parse_action(payload.action or "", payload.params)
        raise ConsoleRejected(
            "Пустой запрос: нужна read-only команда или структурированное действие.",
            code="console_empty",
        )

    def parse_command(self, command: str) -> ConsoleInvocation:
        tokens = self._guard(command)
        head = tokens[0]
        if head == "systemctl":
            return self._systemctl(tokens)
        if head == "journalctl":
            return self._journalctl(tokens)
        if head == "docker":
            if tokens != ["docker", "ps"]:
                raise ConsoleRejected(
                    "Разрешена только команда `docker ps` (без prune/exec/system).",
                    code="console_command_denied",
                )
            return self._command(tokens, "docker")
        if head == "ss":
            if tokens != ["ss", "-ltnp"]:
                raise ConsoleRejected(
                    "Разрешена только команда `ss -ltnp`.", code="console_command_denied"
                )
            return self._command(tokens, "ss")
        if head == "df":
            if tokens != ["df", "-h"]:
                raise ConsoleRejected(
                    "Разрешена только команда `df -h`.", code="console_command_denied"
                )
            return self._command(tokens, "df")
        if head == "free":
            if tokens != ["free", "-h"]:
                raise ConsoleRejected(
                    "Разрешена только команда `free -h`.", code="console_command_denied"
                )
            return self._command(tokens, "free")
        if head == "uptime":
            if tokens != ["uptime"]:
                raise ConsoleRejected(
                    "Разрешена только команда `uptime`.", code="console_command_denied"
                )
            return self._command(tokens, "uptime")
        if head == "curl":
            return self._curl(tokens)
        if head == "ls":
            return self._ls(tokens)
        raise ConsoleRejected(
            "Команда не входит в allowlist серверной консоли.",
            code="console_command_denied",
        )

    def parse_action(self, action: str, params: dict[str, Any] | None) -> ConsoleInvocation:
        name = (action or "").strip()
        if name not in _ACTIONS:
            raise ConsoleRejected(
                "Неизвестное действие. Доступны: start/stop/restart, deploy, "
                "rollback, port_change, add_service.",
                code="console_action_denied",
            )
        values = params or {}
        if not isinstance(values, dict):
            raise ConsoleRejected("Параметры действия должны быть объектом.", code="console_params")
        if name in _SERVICE_ACTION_VERBS:
            self._reject_unknown_keys(values, {"service"})
            service = self._service(values.get("service"))
            unit = self._unit(service)
            return ConsoleInvocation(
                kind="action",
                action=name,
                argv=("systemctl", _SERVICE_ACTION_VERBS[name], unit),
                params={"service": service},
                label=f"systemctl {_SERVICE_ACTION_VERBS[name]} {unit}",
            )
        if name == "deploy":
            self._reject_unknown_keys(values, {"services", "update"})
            requested = values.get("services")
            if requested is None:
                services = sorted(self.services)
            else:
                if not isinstance(requested, list) or not requested:
                    raise ConsoleRejected(
                        "services должен быть непустым списком кодов сервисов.",
                        code="console_params",
                    )
                services = [self._service(item) for item in requested]
            update = values.get("update", True)
            if not isinstance(update, bool):
                raise ConsoleRejected("update должен быть true/false.", code="console_params")
            return ConsoleInvocation(
                kind="action",
                action=name,
                params={"services": services, "update": update},
                label="deploy " + ", ".join(services),
            )
        if name == "rollback":
            self._reject_unknown_keys(values, set())
            return ConsoleInvocation(kind="action", action=name, label="rollback")
        if name == "port_change":
            self._reject_unknown_keys(values, {"service", "port"})
            service = self._service(values.get("service"))
            port = self._port(values.get("port"))
            self._ensure_free_port(port, except_service=service)
            return ConsoleInvocation(
                kind="action",
                action=name,
                params={"service": service, "port": port},
                label=f"port_change {service}:{port}",
            )
        # add_service
        self._reject_unknown_keys(values, {"service", "port"})
        service = self._service_code(values.get("service"))
        if service in self.services:
            raise ConsoleRejected(
                f"Сервис {service} уже настроен на этом сервере.",
                code="console_service_exists",
            )
        port = self._port(values.get("port"))
        self._ensure_free_port(port)
        return ConsoleInvocation(
            kind="action",
            action=name,
            params={"service": service, "port": port},
            label=f"add_service {service}:{port}",
        )

    # -- guards ---------------------------------------------------------
    def _guard(self, text: str) -> list[str]:
        if not isinstance(text, str) or not text.strip():
            raise ConsoleRejected("Команда пустая.", code="console_empty")
        if len(text) > MAX_COMMAND_CHARS:
            raise ConsoleRejected(
                f"Команда длиннее {MAX_COMMAND_CHARS} символов.",
                code="console_too_long",
            )
        if any(ord(ch) < 32 for ch in text):
            raise ConsoleRejected(
                "Управляющие символы и переводы строк запрещены.",
                code="console_injection",
            )
        if any(ch in _SHELL_META for ch in text):
            raise ConsoleRejected(
                "Символы shell (; | & $ > < ` кавычки, скобки, подстановки) запрещены. "
                "Консоль принимает только готовые allowlist-команды.",
                code="console_injection",
            )
        lowered = text.casefold()
        for marker in _SENSITIVE_MARKERS:
            if marker in lowered:
                raise ConsoleRejected(
                    "Доступ к секретам, .env и ключам запрещён.",
                    code="console_secret_denied",
                )
        try:
            tokens = shlex.split(text, posix=True)
        except ValueError as exc:
            raise ConsoleRejected("Не удалось разобрать команду.", code="console_injection") from exc
        if not tokens:
            raise ConsoleRejected("Команда пустая.", code="console_empty")
        for token in tokens:
            folded = token.casefold()
            if folded in _BLOCKED_TOKENS or any(
                folded.startswith(f"{blocked}.") or folded.startswith(f"{blocked}-")
                for blocked in _BLOCKED_TOKENS
            ):
                raise ConsoleRejected(
                    f"Команда/утилита `{token}` запрещена.",
                    code="console_command_denied",
                )
            if len(token) > 512:
                raise ConsoleRejected("Слишком длинный аргумент команды.", code="console_too_long")
        return tokens

    def _systemctl(self, tokens: list[str]) -> ConsoleInvocation:
        if len(tokens) not in (3, 4):
            raise ConsoleRejected(
                "Формат: systemctl status|is-active|is-failed [--no-pager] mangapoisk-*.",
                code="console_command_denied",
            )
        verb = tokens[1]
        if verb not in {"status", "is-active", "is-failed"}:
            raise ConsoleRejected(
                "У systemctl разрешены только status, is-active и is-failed.",
                code="console_command_denied",
            )
        if len(tokens) == 4 and tokens[2] != "--no-pager":
            raise ConsoleRejected(
                "Дополнительный флаг systemctl не разрешён.",
                code="console_command_denied",
            )
        unit = tokens[-1]
        self._require_unit(unit)
        normalized = ("systemctl", verb, unit) if len(tokens) == 3 else (
            "systemctl",
            verb,
            "--no-pager",
            unit,
        )
        return self._command(normalized, verb)

    def _journalctl(self, tokens: list[str]) -> ConsoleInvocation:
        if len(tokens) < 4 or tokens[1] != "-u":
            raise ConsoleRejected(
                "Формат: journalctl -u mangapoisk-* -n N [--no-pager].",
                code="console_command_denied",
            )
        unit = tokens[2]
        self._require_unit(unit)
        lines: int | None = None
        index = 3
        while index < len(tokens):
            token = tokens[index]
            if token == "-n":
                if index + 1 >= len(tokens):
                    raise ConsoleRejected("После -n нужно число строк.", code="console_command_denied")
                try:
                    lines = int(tokens[index + 1])
                except ValueError as exc:
                    raise ConsoleRejected("N должно быть целым числом.", code="console_command_denied") from exc
                index += 2
                continue
            if token == "--no-pager":
                index += 1
                continue
            raise ConsoleRejected(
                "Разрешены только -u, -n N и --no-pager.", code="console_command_denied"
            )
        if lines is None or not 1 <= lines <= MAX_JOURNAL_LINES:
            raise ConsoleRejected(
                f"journalctl -n N: N от 1 до {MAX_JOURNAL_LINES}.",
                code="console_command_denied",
            )
        return self._command(
            ("journalctl", "-u", unit, "-n", str(lines), "--no-pager"),
            "journalctl",
        )

    def _curl(self, tokens: list[str]) -> ConsoleInvocation:
        if len(tokens) not in (3, 4):
            raise ConsoleRejected(
                "Формат: curl -s 127.0.0.1:<port>/health.",
                code="console_command_denied",
            )
        flag = tokens[1]
        if flag not in {"-s", "-fsS"}:
            raise ConsoleRejected(
                "У curl разрешены только флаги -s и -fsS.", code="console_command_denied"
            )
        match = _CURL_RE.fullmatch(tokens[-1])
        if match is None:
            raise ConsoleRejected(
                "curl разрешён только к 127.0.0.1/localhost:<port>/health.",
                code="console_command_denied",
            )
        port = int(match.group("port"))
        if not MIN_PORT <= port <= MAX_PORT:
            raise ConsoleRejected("Порт вне диапазона 1024–65535.", code="console_port")
        if port not in self.ports:
            raise ConsoleRejected(
                "Health-check разрешён только для портов из inventory этого сервера.",
                code="console_port_denied",
            )
        url = f"http://127.0.0.1:{port}/health"
        return self._command(("curl", flag, url), "curl")

    def _ls(self, tokens: list[str]) -> ConsoleInvocation:
        allowed = {
            ("ls", "-la", self.deploy_root),
            ("ls", "-la", f"{self.deploy_root}/"),
        }
        if tuple(tokens) not in allowed:
            raise ConsoleRejected(
                f"Разрешено только `ls -la {self.deploy_root}`.",
                code="console_path_denied",
            )
        return self._command(("ls", "-la", self.deploy_root), "ls")

    def _command(self, argv: tuple[str, ...], action: str) -> ConsoleInvocation:
        return ConsoleInvocation(
            kind="command",
            action=action,
            argv=tuple(argv),
            label=" ".join(argv),
        )

    def _require_unit(self, unit: str) -> None:
        if not _UNIT_RE.fullmatch(unit):
            raise ConsoleRejected(
                "Разрешены только unit-файлы mangapoisk-*; чужие сервисы запрещены.",
                code="console_unit_denied",
            )
        code = unit.removesuffix(".service").removeprefix("mangapoisk-")
        if code not in _ALLOWED_SERVICE_CODES:
            raise ConsoleRejected(
                f"Сервис `{unit}` не входит в список MangaPoisk.",
                code="console_unit_denied",
            )

    def _service(self, value: Any) -> str:
        service = self._service_code(value)
        if service not in self.services:
            raise ConsoleRejected(
                f"Сервис {service} не настроен на этом сервере.",
                code="console_service_denied",
            )
        return service

    def _service_code(self, value: Any) -> str:
        if not isinstance(value, str) or not _SERVICE_RE.fullmatch(value):
            raise ConsoleRejected("Некорректный код сервиса.", code="console_service_denied")
        if value not in _ALLOWED_SERVICE_CODES:
            raise ConsoleRejected(
                f"Неизвестный микросервис {value}.",
                code="console_service_denied",
            )
        return value

    def _unit(self, service: str) -> str:
        if service not in _ALLOWED_SERVICE_CODES:
            raise ConsoleRejected(
                f"Сервис {service} не входит в список MangaPoisk.",
                code="console_unit_denied",
            )
        return f"mangapoisk-{service}.service"

    def _port(self, value: Any) -> int:
        if isinstance(value, bool):
            raise ConsoleRejected("Порт должен быть числом.", code="console_port")
        if isinstance(value, float):
            if not value.is_integer():
                raise ConsoleRejected("Порт должен быть целым числом.", code="console_port")
            port = int(value)
        elif isinstance(value, str):
            if not value.isdigit():
                raise ConsoleRejected("Порт должен быть целым числом.", code="console_port")
            port = int(value)
        elif isinstance(value, int):
            port = value
        else:
            raise ConsoleRejected("Порт должен быть числом.", code="console_port")
        if not MIN_PORT <= port <= MAX_PORT:
            raise ConsoleRejected("Порт вне диапазона 1024–65535.", code="console_port")
        return port

    def _ensure_free_port(self, port: int, *, except_service: str | None = None) -> None:
        for code, current in self.services.items():
            if code != except_service and current == port:
                raise ConsoleRejected(
                    f"Порт {port} уже занят сервисом {code}.",
                    code="console_port_in_use",
                )

    @staticmethod
    def _reject_unknown_keys(values: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(values) - allowed
        if unknown:
            raise ConsoleRejected(
                "Неизвестные параметры действия: " + ", ".join(sorted(unknown)),
                code="console_params",
            )


class ConsoleExecutor:
    """Runs an already-validated invocation and writes an audit record."""

    def __init__(self, settings: ControlSettings, control: ControlService) -> None:
        self.settings = settings
        self.control = control

    async def execute(
        self,
        server_id,
        payload: ConsoleRequest,
        *,
        admin: str | None = None,
    ) -> ConsoleResultOut:
        server = await self.control._server_model(server_id)
        admin_name = _normalize_admin(admin)
        policy = ConsolePolicy(
            {service.code: service.port for service in server.services},
            self.settings.deploy_root,
        )
        started = time.monotonic()
        try:
            invocation = policy.parse(payload)
        except ConsoleRejected as exc:
            await self._audit(
                server.id,
                admin_name,
                payload,
                exit_code=None,
                output_hash=None,
                duration_ms=_elapsed_ms(started),
                rejected=exc.code,
            )
            raise
        if invocation.kind == "action":
            return await self._run_action(server, invocation, admin_name, started)
        return await self._run_command(server, invocation, admin_name, started)

    async def _run_command(
        self,
        server,
        invocation: ConsoleInvocation,
        admin: str,
        started: float,
    ) -> ConsoleResultOut:
        target, jump = await self.control.deployer._target(server)
        try:
            result = await asyncio.to_thread(
                self.control.ssh.run_command,
                target,
                invocation.argv,
                jump=jump,
                timeout=COMMAND_TIMEOUT_SECONDS,
                max_output_bytes=MAX_OUTPUT_BYTES,
            )
        except Exception as exc:
            await self._audit(
                server.id,
                admin,
                ConsoleRequest(command=invocation.label),
                exit_code=None,
                output_hash=None,
                duration_ms=_elapsed_ms(started),
                error=type(exc).__name__,
            )
            raise UpstreamError(
                "Не удалось выполнить команду на сервере. Проверьте SSH-доступ.",
                code="console_ssh_failed",
            ) from exc
        output_hash = hashlib.sha256(result.output.encode("utf-8", "replace")).hexdigest()
        await self._audit(
            server.id,
            admin,
            ConsoleRequest(command=invocation.label),
            exit_code=result.exit_code,
            output_hash=output_hash,
            duration_ms=_elapsed_ms(started),
            truncated=result.truncated,
            timed_out=result.timed_out,
        )
        return ConsoleResultOut(
            ok=result.exit_code == 0 and not result.timed_out,
            kind="command",
            action=invocation.action,
            command=invocation.label,
            output=result.output,
            exit_code=result.exit_code,
            duration_ms=_elapsed_ms(started),
            truncated=result.truncated,
            timed_out=result.timed_out,
            output_hash=output_hash,
        )

    async def _run_action(
        self,
        server,
        invocation: ConsoleInvocation,
        admin: str,
        started: float,
    ) -> ConsoleResultOut:
        try:
            if invocation.action in _SERVICE_ACTION_VERBS:
                return await self._run_service_action(server, invocation, admin, started)
            if invocation.action == "deploy":
                ports = {item.code: item.port for item in server.services}
                services = [
                    ServiceSpec(code=code, port=ports[code])
                    for code in invocation.params["services"]
                ]
                response: DeployResponse = await self.control.deploy(
                    server.id,
                    services,
                    update=bool(invocation.params.get("update", True)),
                )
                return await self._job_result(
                    server.id, admin, invocation, started, response, "Развёртывание запущено."
                )
            if invocation.action == "rollback":
                response = await self.control.rollback(server.id)
                return await self._job_result(
                    server.id,
                    admin,
                    invocation,
                    started,
                    response,
                    "Rollback запущен как control job.",
                )
            if invocation.action == "port_change":
                response = await self.control.change_port(
                    server.id,
                    str(invocation.params["service"]),
                    int(invocation.params["port"]),
                )
                return await self._job_result(
                    server.id,
                    admin,
                    invocation,
                    started,
                    response,
                    "Порт обновлён в inventory; развёртывание запущено.",
                )
            if invocation.action == "add_service":
                response = await self.control.add_service(
                    server.id,
                    str(invocation.params["service"]),
                    int(invocation.params["port"]),
                )
                return await self._job_result(
                    server.id,
                    admin,
                    invocation,
                    started,
                    response,
                    "Сервис добавлен в inventory; развёртывание запущено.",
                )
        except Exception as exc:
            await self._audit(
                server.id,
                admin,
                ConsoleRequest(action=invocation.action, params=invocation.params),
                exit_code=None,
                output_hash=None,
                duration_ms=_elapsed_ms(started),
                error=type(exc).__name__,
            )
            raise
        raise ConsoleRejected(
            "Действие не поддерживается.", code="console_action_denied"
        )

    async def _run_service_action(
        self,
        server,
        invocation: ConsoleInvocation,
        admin: str,
        started: float,
    ) -> ConsoleResultOut:
        target, jump = await self.control.deployer._target(server)
        result = await asyncio.to_thread(
            self.control.ssh.run_command,
            target,
            invocation.argv,
            jump=jump,
            timeout=COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=MAX_OUTPUT_BYTES,
        )
        output_hash = hashlib.sha256(result.output.encode("utf-8", "replace")).hexdigest()
        await self._audit(
            server.id,
            admin,
            ConsoleRequest(action=invocation.action, params=invocation.params),
            exit_code=result.exit_code,
            output_hash=output_hash,
            duration_ms=_elapsed_ms(started),
            truncated=result.truncated,
            timed_out=result.timed_out,
        )
        return ConsoleResultOut(
            ok=result.exit_code == 0 and not result.timed_out,
            kind="action",
            action=invocation.action,
            command=invocation.label,
            output=result.output,
            exit_code=result.exit_code,
            duration_ms=_elapsed_ms(started),
            truncated=result.truncated,
            timed_out=result.timed_out,
            output_hash=output_hash,
        )

    async def _job_result(
        self,
        server_id,
        admin: str,
        invocation: ConsoleInvocation,
        started: float,
        response: DeployResponse,
        message: str,
    ) -> ConsoleResultOut:
        await self._audit(
            server_id,
            admin,
            ConsoleRequest(action=invocation.action, params=invocation.params),
            exit_code=None,
            output_hash=None,
            duration_ms=_elapsed_ms(started),
            job_id=str(response.job_id),
        )
        return ConsoleResultOut(
            ok=True,
            kind="action",
            action=invocation.action,
            command=invocation.label,
            duration_ms=_elapsed_ms(started),
            job_id=response.job_id,
            message=message,
        )

    async def _audit(
        self,
        server_id,
        admin: str,
        payload: ConsoleRequest,
        *,
        exit_code: int | None,
        output_hash: str | None,
        duration_ms: int,
        rejected: str | None = None,
        error: str | None = None,
        truncated: bool = False,
        timed_out: bool = False,
        job_id: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "admin": admin,
            "duration_ms": duration_ms,
        }
        if payload.command is not None:
            # Accepted commands are already allowlisted.  Rejected commands are
            # stored as a hash so a pasted secret never reaches the audit log.
            if rejected is not None:
                details["command_hash"] = hashlib.sha256(
                    payload.command.encode("utf-8", "replace")
                ).hexdigest()
            else:
                details["command"] = payload.command
        if payload.action is not None:
            details["action"] = payload.action
            if rejected is not None:
                # Rejected params are untrusted: keep only safe key names so a
                # pasted secret can never be persisted.
                details["params_keys"] = sorted(
                    key
                    for key in payload.params
                    if isinstance(key, str)
                    and _PARAM_KEY_RE.fullmatch(key)
                    and not any(marker in key.casefold() for marker in _SENSITIVE_MARKERS)
                )
            else:
                details["params"] = payload.params
        if exit_code is not None:
            details["exit_code"] = exit_code
        if output_hash is not None:
            details["output_hash"] = output_hash
        if rejected is not None:
            details["rejected"] = rejected
        if error is not None:
            details["error"] = error
        if truncated:
            details["truncated"] = True
        if timed_out:
            details["timed_out"] = True
        if job_id is not None:
            details["job_id"] = job_id
        action = "console.action" if payload.action is not None else "console.command"
        async with self.control.session_factory() as session:
            await audit(session, action, server_id=server_id, details=details)
            await session.commit()


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


async def console_history(control: ControlService, server_id, limit: int = 50) -> list[AuditOut]:
    await control._server_model(server_id)
    async with control.session_factory() as session:
        rows = await list_console_audit(session, server_id, limit)
        return [audit_out(row) for row in rows]
