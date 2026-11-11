from __future__ import annotations

import asyncio
import logging
import shlex
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import ControlSettings
from .crypto import SecretBox
from .models import DeploymentJob
from .repository import audit, create_job, get_job, get_server, update_server
from .ssh import SSHRunner, SSHTarget

logger = logging.getLogger(__name__)

HTTP_SERVICE_CODES = {"parser", "catalog", "library", "media", "control", "gateway", "notifier"}
ALL_SERVICE_CODES = HTTP_SERVICE_CODES | {"scheduler"}
DEFAULT_PORTS = {
    "parser": 8101,
    "catalog": 8102,
    "library": 8103,
    "media": 8104,
    "control": 8005,
    "gateway": 8100,
    "notifier": 8106,
}


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
        self._tasks: set[asyncio.Task] = set()

    async def start(self, server, services: list[tuple[str, int]], *, update: bool) -> DeploymentJob:
        async with self.session_factory() as session:
            job = await create_job(
                session,
                server.id,
                {
                    "services": [{"code": code, "port": port} for code, port in services],
                    "update": update,
                    "host": server.host,
                },
            )
            await session.commit()
            job_id = job.id
        task = asyncio.create_task(self._run(job_id, server.id, services, update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

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
            job.status = "running"
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
                    now = loop.time()
                    if now - last_commit >= 1.5:
                        job.log = log_buffer
                        await session.commit()
                        last_commit = now
                job.log = log_buffer

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
                    )
                finally:
                    loop.call_soon_threadsafe(line_queue.put_nowait, None)
                    await pump_task
                job = await get_job(session, job_id)
                if job is None:
                    return
                job.log = output[-200_000:]
                if code != 0:
                    job.status = "failed"
                    job.error = f"Скрипт завершился с кодом {code}"
                else:
                    job.status = "done"
                    await update_server(
                        session,
                        server,
                        {"services": services},
                    )
                    await audit(
                        session,
                        "deployment.finished",
                        server_id=server.id,
                        details={"job_id": str(job_id), "services": services},
                    )
                await session.commit()
            except Exception as exc:
                logger.exception("deployment failed")
                job = await get_job(session, job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = str(exc)[:2000]
                    job.log = ((job.log or "") + f"\nERROR: {exc}")[-200_000:]
                    await session.commit()
            finally:
                try:
                    await self.control.health_check_all()
                except Exception:
                    logger.warning("post-deploy health check failed", exc_info=True)

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
            deferred = """
echo "== control restart =="
if command -v systemd-run >/dev/null 2>&1; then
  systemd-run --quiet --on-active=5 --unit="mangapoisk-control-restart-$RANDOM" \
    systemctl restart mangapoisk-control.service
else
  (sleep 5; systemctl restart mangapoisk-control.service) >/dev/null 2>&1 &
fi
"""
        health_checks = "\n".join(
            self._health_block(code, port) for code, port in services if code in HTTP_SERVICE_CODES
        )
        script = _SCRIPT_TEMPLATE
        replacements = {
            "@@ROOT@@": shlex.quote(root),
            "@@USER@@": shlex.quote(deploy_user),
            "@@BIND_HOST@@": bind_host,
            "@@SOURCE_URL@@": shlex.quote(self.settings.deploy_source_url),
            "@@ENV_FILE@@": env,
            "@@UNITS@@": units,
            "@@INSTALLS@@": installs,
            "@@ENABLE@@": enable,
            "@@HEALTH@@": health_checks,
            "@@AFTER@@": deferred,
        }
        for key, value in replacements.items():
            script = script.replace(key, value)
        return script

    def _env_file(self, server, public_host: str, urls: dict[str, str]) -> str:
        root = self.settings.deploy_root.rstrip("/")
        lines = [
            "ENVIRONMENT=production",
            "LOG_LEVEL=INFO",
            "LOG_JSON=true",
            "DEBUG=false",
            f"JWT_SECRET={self.settings.jwt_secret}",
            f"INTERNAL_TOKEN={self.settings.internal_token}",
            f"CONTROL_SECRET_KEY={self.settings.control_secret_key}",
            f"ADMIN_USERNAME={self.settings.admin_username}",
            f"ADMIN_PASSWORD={self.settings.admin_password}",
            f"ADMIN_TOKEN_MINUTES={self.settings.admin_token_minutes}",
            f"DEPLOY_SOURCE_URL={self.settings.deploy_source_url}",
            f"CATALOG_DATABASE_URL=sqlite+aiosqlite:///{root}/data/catalog.db",
            f"LIBRARY_DATABASE_URL=sqlite+aiosqlite:///{root}/data/library.db",
            f"CONTROL_DATABASE_URL=sqlite+aiosqlite:///{root}/data/control.db",
            f"MEDIA_CACHE_DIR={root}/data/media-cache",
            f"EXPORT_DIR={root}/data/exports",
            "EXPORT_TTL_HOURS=48",
            "REDIS_URL=",
            f"PUBLIC_WEB_URL=http://{public_host}:8088",
            f"PUBLIC_API_URL=http://{public_host}:8088",
            f"CORS_ORIGINS=http://{public_host}:8088,http://localhost:5173,http://localhost:8080,capacitor://localhost,https://localhost",
            "SCRAPER_REQUESTS_PER_MINUTE=20",
            "SCRAPER_CACHE_TTL_SECONDS=600",
            "MEDIA_ALLOWED_HOSTS=static2.mangapoisk.me,img2.imglib.info,img3.cdnlibs.org",
            "PARSER_ENABLED_SOURCES=",
            f"CONTROL_URL={self.settings.control_public_url}",
            f"TELEGRAM_BOT_TOKEN={self.settings.telegram_bot_token or ''}",
            f"TELEGRAM_CHAT_ID={self.settings.telegram_chat_id or ''}",
        ]
        for code in ("parser", "catalog", "library", "media", "gateway", "notifier", "control"):
            if code in urls:
                lines.append(f"{code.upper()}_URL={urls[code]}")
        return "\n".join(lines) + "\n"

    def _unit_file(self, root: str, user: str, bind_host: str, code: str, port: int) -> str:
        paths = f"{root}/src/services/{code}"
        python = f"{root}/venv/bin/python"
        if code == "scheduler":
            command = f"{python} -m app.main"
        else:
            command = f"{root}/venv/bin/uvicorn app.main:app --host {bind_host} --port {port} --proxy-headers"
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
Environment=PYTHONPATH={root}/src/packages
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
        return f"""
ok=0
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:{port}/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "HEALTH_FAIL {code}:{port}"
  journalctl -u "mangapoisk-{code}.service" -n 50 --no-pager || true
  exit 1
fi
echo "HEALTH_OK {code}:{port}"
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
chown -R "$USER_NAME:$USER_NAME" "$ROOT/data"
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

echo "== venv =="
if [ ! -x "$ROOT/venv/bin/python" ]; then
  python3 -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install --upgrade pip >/dev/null
"$ROOT/venv/bin/pip" install -e "$ROOT/src/packages/manga_common"
@@INSTALLS@@

echo "== units =="
@@UNITS@@
systemctl daemon-reload
@@ENABLE@@

echo "== health =="
@@HEALTH@@

@@AFTER@@
echo "DEPLOY_OK"
"""
