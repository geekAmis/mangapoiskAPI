from __future__ import annotations

import asyncio
import logging
import shlex
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .ai_supervisor import (
    AISupervisor,
    SupervisorPolicy,
    is_full_deploy,
)
from .config import ControlSettings
from .crypto import SecretBox
from .models import DeploymentJob
from .repository import (
    audit,
    create_job,
    get_job,
    get_server,
    list_running_jobs,
    update_server,
)
from .ssh import SSHRunHandle, SSHRunner, SSHTarget

logger = logging.getLogger(__name__)

HTTP_SERVICE_CODES = {"parser", "catalog", "library", "media", "control", "gateway", "notifier", "replica", "comments"}
ALL_SERVICE_CODES = HTTP_SERVICE_CODES | {"scheduler"}
DEFAULT_PORTS = {
    "parser": 8101,
    "catalog": 8102,
    "library": 8103,
    "media": 8104,
    "control": 8005,
    "gateway": 8100,
    "notifier": 8106,
    "replica": 8108,
    "comments": 8109,
}


def merge_deployed_services(
    existing: list[tuple[str, int]], deployed: list[tuple[str, int]]
) -> list[tuple[str, int]]:
    """Keep the inventory of services that were not part of this deploy.

    A partial deploy (e.g. only gateway) must not erase parser/catalog/library
    from the server card or from the gateway registry.
    """

    merged = dict(existing)
    merged.update(dict(deployed))
    return list(merged.items())


class Deployer:
    def __init__(
        self,
        settings: ControlSettings,
        session_factory: async_sessionmaker[AsyncSession],
        box: SecretBox,
        ssh: SSHRunner,
        control,  # ControlService; typed loosely to avoid a circular import
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.box = box
        self.ssh = ssh
        self.control = control
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._handles: dict[uuid.UUID, SSHRunHandle] = {}
        self.ai_supervisor = (
            AISupervisor(
                policy=SupervisorPolicy(
                    settings.deploy_root, settings.ai_supervisor_max_steps
                ),
                model=settings.ai_supervisor_model,
                timeout_seconds=settings.ai_supervisor_timeout_seconds,
                round_timeout_seconds=settings.ai_supervisor_round_timeout_seconds,
                max_iterations=settings.ai_supervisor_max_iterations,
                opencode_bin=settings.ai_supervisor_opencode_bin,
                dry_run=settings.ai_supervisor_dry_run,
                skip_when_healthy=settings.ai_supervisor_skip_when_healthy,
                rollback_enabled=settings.ai_supervisor_rollback,
            )
            if settings.ai_supervisor_enabled
            else None
        )

    async def start(self, server, services: list[tuple[str, int]], *, update: bool) -> DeploymentJob:
        async with self.session_factory() as session:
            job = await create_job(
                session,
                server.id,
                {
                    "services": [{"code": code, "port": port} for code, port in services],
                    "update": update,
                    "host": server.host,
                    "health_timeout_seconds": self.settings.deploy_health_timeout_seconds,
                    "read_timeout_seconds": self.settings.deploy_read_timeout_seconds,
                    "stale_after_seconds": self.settings.deploy_stale_job_seconds,
                },
            )
            await session.commit()
            job_id = job.id
        task = asyncio.create_task(self._run(job_id, server.id, services, update))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task, key=job_id: self._tasks.pop(key, None))
        return job

    async def close(self) -> None:
        for handle in list(self._handles.values()):
            handle.cancel()
        self._handles.clear()
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_job(self, job_id: uuid.UUID, reason: str) -> bool:
        """Cancel a running job and make its failure observable immediately."""

        task = self._tasks.pop(job_id, None)
        handle = self._handles.pop(job_id, None)
        if handle is not None:
            handle.cancel()
        if task is not None and not task.done():
            task.cancel()
        async with self.session_factory() as session:
            job = await get_job(session, job_id)
            if job is None or job.status not in {"queued", "running"}:
                return False
            now = datetime.now(UTC)
            job.status = "failed"
            job.error = reason[:2000]
            job.last_output_at = now
            job.log = ((job.log or "") + f"\nCANCELLED: {reason}\n")[-200_000:]
            await session.commit()
        return True

    async def reap_stale_jobs(self) -> int:
        """Fail/cancel running jobs whose heartbeat is older than the limit."""

        async with self.session_factory() as session:
            jobs = await list_running_jobs(session)
            now = datetime.now(UTC)
            stale: list[uuid.UUID] = []
            for job in jobs:
                last = job.last_output_at or job.updated_at or job.created_at
                if last is None:
                    continue
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if (now - last).total_seconds() >= self.settings.deploy_stale_job_seconds:
                    stale.append(job.id)
        for job_id in stale:
            await self.cancel_job(
                job_id,
                "Deploy job stalled: no output for "
                f"{self.settings.deploy_stale_job_seconds}s; cancelled by control",
            )
        return len(stale)

    async def _target(self, server) -> tuple[SSHTarget, SSHTarget | None]:
        target = SSHTarget(
            host=server.host,
            port=server.ssh_port,
            username=server.username,
            password=self.box.decrypt(server.password_encrypted),
            name=server.name,
        )
        jump = None
        if server.jump_server_id:
            async with self.session_factory() as session:
                from .models import Server

                jump_server = await session.get(Server, server.jump_server_id)
                if jump_server is not None:
                    jump = SSHTarget(
                        host=jump_server.host,
                        port=jump_server.ssh_port,
                        username=jump_server.username,
                        password=self.box.decrypt(jump_server.password_encrypted),
                        name=jump_server.name,
                    )
        return target, jump

    async def _run(
        self,
        job_id: uuid.UUID,
        server_id: uuid.UUID,
        services: list[tuple[str, int]],
        update: bool,
    ) -> None:
        async with self.session_factory() as session:
            job = await get_job(session, job_id)
            server = await get_server(session, server_id)
            if job is None or server is None:
                return
            if job.status not in {"queued", "running"}:
                return
            job.status = "running"
            job.last_output_at = datetime.now(UTC)
            job.log = "Подключение к серверу…\n"
            await session.commit()
            target, jump = await self._target(server)
            if jump is not None:
                job.log = (
                    f"Подключаемся к {server.host}:{server.ssh_port} "
                    f"через jump-сервер {jump.name or jump.host}…\n"
                )
                await session.commit()
            loop = asyncio.get_running_loop()
            line_queue: asyncio.Queue[str | None] = asyncio.Queue()
            log_buffer = job.log
            handle = SSHRunHandle()
            self._handles[job_id] = handle

            def on_line(line: str) -> None:
                loop.call_soon_threadsafe(line_queue.put_nowait, line)

            async def pump() -> None:
                nonlocal log_buffer
                last_commit = loop.time()
                while True:
                    line = await line_queue.get()
                    if line is None:
                        break
                    log_buffer = (log_buffer + line + "\n")[-200_000:]
                    job.last_output_at = datetime.now(UTC)
                    now = loop.time()
                    if now - last_commit >= 1.5:
                        job.log = log_buffer
                        await session.commit()
                        last_commit = now
                job.log = log_buffer
                job.last_output_at = datetime.now(UTC)

            pump_task = asyncio.create_task(pump())
            try:
                try:
                    script = await self._build_script(server, services)
                    code, output = await asyncio.to_thread(
                        self.ssh.run_script,
                        target,
                        script,
                        jump=jump,
                        on_line=on_line,
                        timeout=self.settings.deploy_timeout_seconds,
                        read_timeout=self.settings.deploy_read_timeout_seconds,
                        handle=handle,
                    )
                finally:
                    loop.call_soon_threadsafe(line_queue.put_nowait, None)
                    try:
                        await pump_task
                    except asyncio.CancelledError:
                        pump_task.cancel()
                        raise
                job = await get_job(session, job_id)
                if job is None:
                    return
                job.log = output[-200_000:]
                job.last_output_at = datetime.now(UTC)
                deploy_ok = code == 0
                supervisor_report = None
                supervisor_run = self._supervisor_runner(job_id, target, jump)
                supervisor_active = self._should_run_supervisor(server, services)
                if supervisor_active:
                    supervisor_report = await self._run_supervisor(
                        session=session,
                        job=job,
                        server=server,
                        services=services,
                        deploy_ok=deploy_ok,
                        deploy_log=output,
                        run_script=supervisor_run,
                    )
                post_health = None
                if (
                    self.ai_supervisor is not None
                    and supervisor_report is not None
                    and supervisor_report.get("status") not in {"skipped", "dry_run"}
                ):
                    post_health = await self.ai_supervisor.check_health(
                        supervisor_run, services
                    )
                rollback_ok = bool(
                    ((supervisor_report or {}).get("rollback") or {}).get("ok")
                )
                rollback_attempted = bool(
                    ((supervisor_report or {}).get("rollback") or {}).get("attempted")
                ) and not bool(
                    ((supervisor_report or {}).get("rollback") or {}).get("skipped")
                )
                recovered = (
                    not deploy_ok
                    and supervisor_report is not None
                    and supervisor_report.get("status") == "recovered"
                    and post_health is not None
                    and post_health.ok
                    and not rollback_attempted
                )
                if (
                    deploy_ok
                    and not rollback_attempted
                    and (post_health is None or post_health.ok)
                ) or recovered:
                    job.status = "done"
                    job.error = None
                else:
                    job.status = "failed"
                    if "HEALTH_FAIL" in output:
                        job.error = (
                            "Health check failed after "
                            f"{self.settings.deploy_health_timeout_seconds}s"
                        )
                    elif rollback_attempted and not rollback_ok:
                        job.error = "AI supervisor failed; source rollback is incomplete"
                    elif rollback_ok:
                        job.error = "AI supervisor failed; source was rolled back"
                    elif (
                        supervisor_report is not None
                        and supervisor_report.get("status") == "skipped"
                    ):
                        job.error = (
                            "AI supervisor skipped: "
                            f"{supervisor_report.get('skipped_reason') or 'unavailable'}"
                        )
                    elif supervisor_report is not None and supervisor_report.get(
                        "error"
                    ):
                        job.error = f"AI supervisor: {supervisor_report['error']}"
                    else:
                        job.error = f"Скрипт завершился с кодом {code}"
                if (
                    job.status == "done"
                    and self.settings.ai_supervisor_required
                    and supervisor_report is not None
                    and supervisor_report.get("status") == "skipped"
                ):
                    job.status = "failed"
                    job.error = (
                        "AI supervisor is required but was skipped: "
                        f"{supervisor_report.get('skipped_reason') or 'unavailable'}"
                    )
                if job.status == "done":
                    inventory = merge_deployed_services(
                        [(item.code, item.port) for item in server.services], services
                    )
                    await update_server(
                        session,
                        server,
                        {"services": inventory},
                    )
                    await audit(
                        session,
                        "deployment.finished",
                        server_id=server.id,
                        details={"job_id": str(job_id), "services": services},
                    )
                await session.commit()
                if (
                    job.status == "done"
                    and supervisor_active
                    and not rollback_attempted
                    and any(code == "control" for code, _ in services)
                ):
                    await self._schedule_control_restart(target, jump)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("deployment failed")
                job = await get_job(session, job_id)
                if job is not None:
                    job.last_output_at = datetime.now(UTC)
                    if job.status != "failed":
                        job.status = "failed"
                        job.error = str(exc)[:2000]
                    job.log = ((job.log or "") + f"\nERROR: {exc}")[-200_000:]
                    await session.commit()
            finally:
                self._handles.pop(job_id, None)
                try:
                    await self.control.health_check_all()
                except Exception:
                    logger.warning("post-deploy health check failed", exc_info=True)

    def _should_run_supervisor(self, server, services: list[tuple[str, int]]) -> bool:
        if not self.settings.ai_supervisor_enabled:
            return False
        if not self.settings.ai_supervisor_full_deploy_only:
            return True
        return is_full_deploy(
            services, [item.code for item in getattr(server, "services", [])]
        )

    def _supervisor_runner(self, job_id: uuid.UUID, target, jump):
        async def run(script: str, timeout: float, read_timeout: float) -> tuple[int, str]:
            handle = SSHRunHandle()
            self._handles[job_id] = handle
            try:
                return await asyncio.to_thread(
                    self.ssh.run_script,
                    target,
                    script,
                    jump=jump,
                    timeout=timeout,
                    read_timeout=read_timeout,
                    handle=handle,
                )
            finally:
                if self._handles.get(job_id) is handle:
                    self._handles.pop(job_id, None)

        return run

    def _append_job_log(self, job: DeploymentJob, text: str) -> None:
        job.log = ((job.log or "") + text)[-200_000:]
        job.last_output_at = datetime.now(UTC)

    async def _run_supervisor(
        self,
        *,
        session: AsyncSession,
        job: DeploymentJob,
        server,
        services: list[tuple[str, int]],
        deploy_ok: bool,
        deploy_log: str,
        run_script,
    ) -> dict:
        if self.ai_supervisor is None:
            return {
                "status": "skipped",
                "summary": "AI supervisor is disabled",
                "skipped_reason": "disabled",
            }
        self._append_job_log(job, "\n== AI supervisor ==\n")
        await session.commit()

        async def on_event(line: str) -> None:
            self._append_job_log(job, line + "\n")
            await session.commit()

        try:
            report = await self.ai_supervisor.run(
                job_id=str(job.id),
                server_name=server.name,
                server_host=server.host,
                services=services,
                deploy_ok=deploy_ok,
                deploy_log=deploy_log,
                run_script=run_script,
                on_event=on_event,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("AI supervisor failed")
            report = {
                "status": "error",
                "summary": f"AI supervisor crashed: {exc}"[:500],
                "error": str(exc)[:500],
                "rounds": 0,
                "actions": [],
                "guard_violations": [],
                "changed_files": [],
                "shell_commands": [],
                "rollback": None,
            }
        self._append_job_log(
            job,
            f"AI supervisor result: {report.get('status')} — "
            f"{report.get('summary') or 'no summary'}\n",
        )
        requested = dict(job.requested or {})
        requested["supervisor"] = report
        job.requested = requested
        await audit(
            session,
            "ai_supervisor.finished",
            server_id=server.id,
            details={
                "job_id": str(job.id),
                "status": report.get("status"),
                "rounds": report.get("rounds"),
                "rollback": bool((report.get("rollback") or {}).get("attempted")),
                "guard_violations": len(report.get("guard_violations") or []),
                "changed_files": len(report.get("changed_files") or []),
                "shell_commands": len(report.get("shell_commands") or []),
            },
        )
        await session.commit()
        return report

    async def _schedule_control_restart(self, target, jump) -> None:
        """Restart control only after the job result has been persisted.

        A control self-deploy cannot restart control from inside the deploy
        script while the AI supervisor is still running in this process.  The
        deploy script therefore leaves a long fallback timer; here we schedule
        the real restart and cancel the fallback once it is armed.
        """

        script = """set -u
if command -v systemd-run >/dev/null 2>&1; then
  if systemd-run --quiet --on-active=5 --unit="mangapoisk-control-restart-now" \\
    systemctl restart mangapoisk-control.service; then
    systemctl stop "mangapoisk-control-restart-fallback.timer" 2>/dev/null || true
    systemctl reset-failed "mangapoisk-control-restart-fallback.service" 2>/dev/null || true
    echo "AI_CONTROL_RESTART_SCHEDULED"
    exit 0
  fi
fi
echo "AI_CONTROL_RESTART_DEFERRED"
exit 0
"""
        try:
            _code, output = await asyncio.to_thread(
                self.ssh.run_script,
                target,
                script,
                jump=jump,
                timeout=60.0,
                read_timeout=30.0,
            )
        except Exception:
            logger.warning("failed to schedule control restart", exc_info=True)
            return
        if "AI_CONTROL_RESTART_SCHEDULED" not in output:
            logger.warning("control restart was not scheduled: %s", output[-500:])

    async def _build_script(self, server, services: list[tuple[str, int]]) -> str:
        root = self.settings.deploy_root.rstrip("/")
        deploy_user = self.settings.deploy_user
        bind_host = server.bind_host or "0.0.0.0"
        public_host = server.public_host or server.host
        urls = await self.control.service_urls()
        for code, port in services:
            urls[code] = f"http://{public_host}:{port}" if bind_host not in {"127.0.0.1", "localhost"} else f"http://127.0.0.1:{port}"
        env = self._env_file(server, public_host, urls)
        units = "\n".join(
            self._unit_file(root, deploy_user, bind_host, code, port) for code, port in services
        )
        installs = "\n".join(
            f'"$ROOT/venv/bin/pip" install -r "$ROOT/src/services/{code}/requirements.txt"'
            for code, _ in services
        )
        opencode_install = ""
        if self.settings.ai_supervisor_install_opencode:
            opencode_install = f"""
echo "== opencode =="
if [ "$(id -u)" -eq 0 ] && [ -f "$ROOT/src/scripts/ops/install_opencode.sh" ]; then
  if OPENCODE_SUPERVISOR_MAX_STEPS={self.settings.ai_supervisor_max_steps} \\
    bash "$ROOT/src/scripts/ops/install_opencode.sh" --skip-auth-check; then
    echo "OPENCODE_INSTALL_OK"
  else
    echo "OPENCODE_INSTALL_WARNING installer failed; supervisor will skip"
  fi
else
  echo "OPENCODE_INSTALL_SKIPPED not-root-or-installer-missing"
fi
"""
        enable_lines: list[str] = []
        for code, _ in services:
            if code == "control":
                # Restarting control from inside its own deploy job kills the job
                # runner before it can persist the result.  Enable it now and
                # schedule the restart after the job has been recorded.
                enable_lines.append('systemctl enable "mangapoisk-control.service"')
            else:
                enable_lines.append(
                    f'systemctl enable --now "mangapoisk-{code}.service"; '
                    f'systemctl restart "mangapoisk-{code}.service"'
                )
        enable = "\n".join(enable_lines)
        deferred = ""
        if any(code == "control" for code, _ in services):
            delay = 5
            if self._should_run_supervisor(server, services):
                # The supervisor runs in this control process.  Give it the
                # full budget before the fallback timer restarts control; the
                # job runner schedules an earlier restart after it persists
                # the result.
                delay = self.settings.ai_supervisor_timeout_seconds + 600
            deferred = f"""
echo "== control restart =="
systemctl stop "mangapoisk-control-restart-fallback.timer" 2>/dev/null || true
systemctl reset-failed "mangapoisk-control-restart-fallback.service" 2>/dev/null || true
if command -v systemd-run >/dev/null 2>&1; then
  systemd-run --quiet --on-active={delay} --unit="mangapoisk-control-restart-fallback" \\
    systemctl restart mangapoisk-control.service || true
else
  (sleep {delay}; systemctl restart mangapoisk-control.service) >/dev/null 2>&1 &
fi
"""
        env_extras = self._service_env_files(services)
        health_checks = "\n".join(
            self._health_block(code, port) for code, port in services if code in HTTP_SERVICE_CODES
        )
        pre_start = self.settings.deploy_pre_start_command.strip()
        pre_start_arg = shlex.quote(pre_start) if pre_start else "''"
        script = _SCRIPT_TEMPLATE
        replacements = {
            "@@ROOT@@": shlex.quote(root),
            "@@USER@@": shlex.quote(deploy_user),
            "@@BIND_HOST@@": bind_host,
            "@@SOURCE_URL@@": shlex.quote(self.settings.deploy_source_url),
            "@@ENV_FILE@@": env,
            "@@ENV_EXTRAS@@": env_extras,
            "@@UNITS@@": units,
            "@@INSTALLS@@": installs,
            "@@OPENCODE@@": opencode_install,
            "@@PRE_START@@": pre_start_arg,
            "@@PRE_START_TIMEOUT@@": str(self.settings.deploy_pre_start_timeout_seconds),
            "@@ENABLE@@": enable,
            "@@HEALTH@@": health_checks,
            "@@AFTER@@": deferred,
        }
        for key, value in replacements.items():
            script = script.replace(key, value)
        return script

    def _public_url(self, value: str, field: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if not parsed.netloc:
            raise RuntimeError(f"{field} must be an absolute URL")
        if self.settings.is_production and parsed.scheme != "https":
            raise RuntimeError(f"{field} must use https in production")
        return value

    def _public_api_base(self) -> str:
        base = self._public_url(self.settings.public_api_url, "PUBLIC_API_URL")
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base

    def _env_file(self, server, public_host: str, urls: dict[str, str]) -> str:
        root = self.settings.deploy_root.rstrip("/")
        public_web_url = self._public_url(self.settings.public_web_url, "PUBLIC_WEB_URL")
        public_api_base = self._public_api_base()
        lines = [
            "ENVIRONMENT=production",
            "LOG_LEVEL=INFO",
            "LOG_JSON=true",
            "DEBUG=false",
            f"JWT_SECRET={self.settings.jwt_secret}",
            f"INTERNAL_TOKEN={self.settings.internal_token}",
            f"CATALOG_DATABASE_URL=sqlite+aiosqlite:///{root}/data/catalog.db",
            f"LIBRARY_DATABASE_URL=sqlite+aiosqlite:///{root}/data/library.db",
            f"CONTROL_DATABASE_URL=sqlite+aiosqlite:///{root}/data/control.db",
            f"COMMENTS_DATABASE_URL=sqlite+aiosqlite:///{root}/data/comments.db",
            f"NOTIFIER_DATABASE_URL=sqlite+aiosqlite:///{root}/data/notifier.db",
            f"COMMENTS_URL={urls.get('comments', 'http://127.0.0.1:8109')}",
            f"VAPID_PUBLIC_KEY={self.settings.vapid_public_key}",
            f"VAPID_PRIVATE_KEY={self.settings.vapid_private_key}",
            f"VAPID_SUBJECT={self.settings.vapid_subject}",
            f"WEB_PUSH_ENABLED={'true' if self.settings.web_push_enabled else 'false'}",
            f"MEDIA_CACHE_DIR={root}/data/media-cache",
            f"REPLICA_DIR={root}/data/replica",
            f"REPLICA_DATA_ROOT={root}/data",
            f"REGISTRY_URL={public_api_base}/registry",
            f"REPLICA_SELF_URL=http://{public_host}:8108",
            "REPLICA_SYNC_SECONDS=10",
            f"EXPORT_DIR={root}/data/exports",
            f"PARSER_COOKIE_STORE_PATH={root}/data/source-cookies.json",
            "EXPORT_TTL_HOURS=48",
            "REDIS_URL=",
            f"PUBLIC_WEB_URL={public_web_url}",
            f"PUBLIC_API_URL={public_api_base}",
            f"CORS_ORIGINS={public_web_url},http://{public_host}:8088,http://localhost:5173,http://localhost:8080,capacitor://localhost,https://localhost",
            "SCRAPER_REQUESTS_PER_MINUTE=36",
            "SCRAPER_CACHE_TTL_SECONDS=600",
            "MEDIA_ALLOWED_HOSTS=static2.mangapoisk.me,img2.imglib.info,img3.cdnlibs.org,remanga.org,img3.reimg2.org,img-reserve.reimg2.org",
            "PARSER_ENABLED_SOURCES=",
            "CATALOGUE_IMPORT_ENABLED=true",
            "CATALOGUE_IMPORT_INTERVAL_SECONDS=21600",
            "CATALOGUE_SOURCES=mangapoisk,mangalib,remanga",
            "CATALOGUE_CRAWL_DELAY_SECONDS=1.75",
            "CATALOGUE_ENRICHMENT_LIMIT=60",
            f"CONTROL_URL={self.settings.control_public_url}",
        ]
        for code in ("parser", "catalog", "library", "media", "gateway", "notifier", "control", "replica"):
            if code in urls:
                lines.append(f"{code.upper()}_URL={urls[code]}")
        return "\n".join(lines) + "\n"

    def _service_env_files(self, services: list[tuple[str, int]]) -> str:
        """Write service-scoped secrets next to the shared read-only env.

        Parser/media/catalog must not receive ADMIN_PASSWORD or
        CONTROL_SECRET_KEY; only gateway/control get admin credentials, and
        only control gets the Fernet key and deploy source.
        """

        blocks: list[str] = []
        for code in ("gateway", "control", "notifier"):
            lines: list[str] = []
            if code in {"gateway", "control"}:
                lines.extend(
                    [
                        f"ADMIN_USERNAME={self.settings.admin_username}",
                        f"ADMIN_PASSWORD={self.settings.admin_password}",
                        f"ADMIN_TOKEN_MINUTES={self.settings.admin_token_minutes}",
                    ]
                )
            if code == "control":
                lines.extend(
                    [
                        f"CONTROL_SECRET_KEY={self.settings.control_secret_key}",
                        f"DEPLOY_SOURCE_URL={self.settings.deploy_source_url}",
                        f"AI_SUPERVISOR_ENABLED={'true' if self.settings.ai_supervisor_enabled else 'false'}",
                        f"AI_SUPERVISOR_MODEL={self.settings.ai_supervisor_model}",
                        f"AI_SUPERVISOR_TIMEOUT_SECONDS={self.settings.ai_supervisor_timeout_seconds}",
                        "AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS="
                        f"{self.settings.ai_supervisor_round_timeout_seconds}",
                        f"AI_SUPERVISOR_MAX_ITERATIONS={self.settings.ai_supervisor_max_iterations}",
                        f"AI_SUPERVISOR_MAX_STEPS={self.settings.ai_supervisor_max_steps}",
                        f"AI_SUPERVISOR_OPENCODE_BIN={self.settings.ai_supervisor_opencode_bin}",
                        "AI_SUPERVISOR_INSTALL_OPENCODE="
                        f"{'true' if self.settings.ai_supervisor_install_opencode else 'false'}",
                        "AI_SUPERVISOR_FULL_DEPLOY_ONLY="
                        f"{'true' if self.settings.ai_supervisor_full_deploy_only else 'false'}",
                        "AI_SUPERVISOR_SKIP_WHEN_HEALTHY="
                        f"{'true' if self.settings.ai_supervisor_skip_when_healthy else 'false'}",
                        f"AI_SUPERVISOR_REQUIRED={'true' if self.settings.ai_supervisor_required else 'false'}",
                        f"AI_SUPERVISOR_ROLLBACK={'true' if self.settings.ai_supervisor_rollback else 'false'}",
                        f"AI_SUPERVISOR_DRY_RUN={'true' if self.settings.ai_supervisor_dry_run else 'false'}",
                    ]
                )
            if code == "notifier":
                lines.extend(
                    [
                        f"TELEGRAM_BOT_TOKEN={self.settings.telegram_bot_token or ''}",
                        f"TELEGRAM_CHAT_ID={self.settings.telegram_chat_id or ''}",
                    ]
                )
            if not lines:
                continue
            content = "\n".join(lines) + "\n"
            blocks.append(
                f"""mkdir -p "$ROOT/env"
cat > "$ROOT/env/{code}.env" <<'SERVICEENV'
{content}SERVICEENV
chmod 640 "$ROOT/env/{code}.env"
chown root:"$USER_NAME" "$ROOT/env/{code}.env" || true
"""
            )
        return "\n".join(blocks)

    def _unit_file(self, root: str, user: str, bind_host: str, code: str, port: int) -> str:
        paths = f"{root}/src/services/{code}"
        python = f"{root}/venv/bin/python"
        if code == "scheduler":
            command = f"{python} -m app.main"
        else:
            listen_host = "0.0.0.0" if code == "replica" else bind_host
            command = f"{root}/venv/bin/uvicorn app.main:app --host {listen_host} --port {port} --proxy-headers"
        supervisor_env = (
            f"EnvironmentFile=-{root}/env/ai-supervisor.env\n" if code == "control" else ""
        )
        return f"""
cat > /etc/systemd/system/mangapoisk-{code}.service <<'UNITEOF'
[Unit]
Description=MangaPoisk Reborn {code}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory={paths}
EnvironmentFile=-{root}/.env
EnvironmentFile=-{root}/env/{code}.env
{supervisor_env}Environment=PYTHONPATH={root}/src/packages:{root}/src
ExecStart={command}
Restart=always
RestartSec=3
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths={root}/data

[Install]
WantedBy=multi-user.target
UNITEOF
"""

    def _health_block(self, code: str, port: int) -> str:
        timeout = self.settings.deploy_health_timeout_seconds
        poll = self.settings.deploy_health_poll_seconds
        attempts = max(1, (timeout + poll - 1) // poll)
        progress_every = max(1, min(attempts, 10))
        return f"""
ok=0
echo "HEALTH_WAIT {code}:{port} timeout={timeout}s attempts={attempts}"
for i in $(seq 1 {attempts}); do
  if curl -fsS "http://127.0.0.1:{port}/health" >/dev/null 2>&1; then
    ok=1
    echo "HEALTH_OK {code}:{port} attempt=$i"
    break
  fi
  if [ $((i % {progress_every})) -eq 0 ]; then
    echo "HEALTH_WAIT {code}:{port} attempt=$i/{attempts}"
  fi
  sleep {poll}
done
if [ "$ok" != "1" ]; then
  echo "HEALTH_FAIL {code}:{port} timeout={timeout}s attempts={attempts}"
  journalctl -u "mangapoisk-{code}.service" -n 50 --no-pager || true
  exit 1
fi
"""


_SCRIPT_TEMPLATE = r"""set -euo pipefail
ROOT=@@ROOT@@
USER_NAME=@@USER@@
export DEBIAN_FRONTEND=noninteractive

echo "== MangaPoisk deploy =="
echo "root: $ROOT"

if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home "$ROOT" --shell /usr/sbin/nologin "$USER_NAME"
fi
mkdir -p "$ROOT" "$ROOT/data" "$ROOT/data/media-cache" "$ROOT/data/exports" "$ROOT/logs" "$ROOT/run"
chown -R "$USER_NAME:$USER_NAME" "$ROOT/data" 2>/dev/null || true
chmod 750 "$ROOT/data"

echo "== source =="
if ! command -v curl >/dev/null 2>&1; then echo "curl is required"; exit 1; fi
if ! command -v tar >/dev/null 2>&1; then echo "tar is required"; exit 1; fi
curl -fsSL @@SOURCE_URL@@ -o /tmp/mangapoisk-reborn.tar.gz
rm -rf "$ROOT/src.new"
mkdir -p "$ROOT/src.new"
tar -xzf /tmp/mangapoisk-reborn.tar.gz --strip-components=1 -C "$ROOT/src.new"
if [ -d "$ROOT/src" ]; then rm -rf "$ROOT/src.old"; mv "$ROOT/src" "$ROOT/src.old"; fi
mv "$ROOT/src.new" "$ROOT/src"
chmod -R a+rX "$ROOT/src"

echo "== env =="
cat > "$ROOT/.env" <<'ENVEOF'
@@ENV_FILE@@ENVEOF
chmod 640 "$ROOT/.env"
chown root:"$USER_NAME" "$ROOT/.env" || true
@@ENV_EXTRAS@@

echo "== venv =="
if [ ! -x "$ROOT/venv/bin/python" ]; then
  if ! python3 -m venv "$ROOT/venv" 2>/tmp/mangapoisk-venv.err; then
    cat /tmp/mangapoisk-venv.err
    if command -v apt-get >/dev/null 2>&1; then
      echo "Installing python3-venv…"
      apt-get update -qq && apt-get install -y -qq python3-venv python3-pip
      python3 -m venv "$ROOT/venv"
    else
      echo "python3 -m venv failed and apt-get is unavailable"
      exit 1
    fi
  fi
fi
if [ ! -x "$ROOT/venv/bin/pip" ]; then
  "$ROOT/venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if [ ! -x "$ROOT/venv/bin/pip" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq python3-venv python3-pip
    python3 -m venv --upgrade "$ROOT/venv" 2>/dev/null || python3 -m venv "$ROOT/venv"
    "$ROOT/venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi
fi
if [ ! -x "$ROOT/venv/bin/pip" ]; then
  echo "Python venv without pip. Install python3-venv (or python3-pip) and retry."
  exit 1
fi
"$ROOT/venv/bin/pip" install --upgrade pip >/dev/null
"$ROOT/venv/bin/pip" install -e "$ROOT/src/packages/manga_common"
@@INSTALLS@@

@@OPENCODE@@

echo "== pre-start =="
if [ -n @@PRE_START@@ ]; then
  echo "Running pre-start command (timeout @@PRE_START_TIMEOUT@@s)…"
  timeout @@PRE_START_TIMEOUT@@ bash -lc @@PRE_START@@
fi

echo "== units =="
@@UNITS@@
systemctl daemon-reload
@@ENABLE@@

echo "== health =="
@@HEALTH@@

@@AFTER@@
echo "DEPLOY_OK"
"""
