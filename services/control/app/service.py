from __future__ import annotations

import asyncio
import json
import logging
import shlex
import socket
import uuid
from datetime import UTC, datetime
from typing import get_args
from urllib.parse import urlparse

import httpx
from manga_common.errors import ConflictError, NotFoundError, UpstreamError, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import ControlSettings
from .console import ConsoleExecutor, console_history
from .crypto import SecretBox
from .deployer import Deployer
from .models import Server
from .repository import (
    audit,
    create_server,
    delete_server,
    get_job,
    get_server,
    job_out,
    list_jobs,
    list_servers,
    server_out,
    update_server,
)
from .schemas import (
    HTTP_SERVICES,
    AuditOut,
    ConsoleRequest,
    ConsoleResultOut,
    DeployResponse,
    JobOut,
    RegistryEndpoint,
    RegistryOut,
    ReplicaActionOut,
    ServerCreate,
    ServerHealthOut,
    ServerOut,
    ServerUpdate,
    ServiceCode,
    ServiceOut,
    ServiceSpec,
)
from .ssh import SSHRunner, SSHTarget

logger = logging.getLogger(__name__)


class ControlService:
    def __init__(self, settings: ControlSettings, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.box = SecretBox(settings.control_secret_key)
        self.ssh = SSHRunner()
        self.deployer = Deployer(settings, session_factory, self.box, self.ssh, self)
        self.console_executor = ConsoleExecutor(settings, self)

    def _target(self, server: Server) -> SSHTarget:
        return SSHTarget(
            host=server.host,
            port=server.ssh_port,
            username=server.username,
            password=self.box.decrypt(server.password_encrypted),
            name=server.name,
        )

    async def _jump_target(self, session: AsyncSession, server: Server) -> SSHTarget | None:
        if server.jump_server_id is None:
            return None
        jump = await session.get(Server, server.jump_server_id)
        if jump is None:
            raise ValidationError("Jump-сервер не найден", code="jump_not_found")
        return self._target(jump)

    async def servers(self) -> list[ServerOut]:
        async with self.session_factory() as session:
            rows = await list_servers(session)
            names = {row.id: row.name for row in rows}
            return [server_out(row, names.get(row.jump_server_id)) for row in rows]

    async def _server_model(self, server_id: uuid.UUID) -> Server:
        async with self.session_factory() as session:
            row = await get_server(session, server_id)
            if row is None:
                raise NotFoundError("Сервер не найден")
            return row

    async def server(self, server_id: uuid.UUID) -> ServerOut:
        async with self.session_factory() as session:
            row = await get_server(session, server_id)
            if row is None:
                raise NotFoundError("Сервер не найден")
            jump = await session.get(Server, row.jump_server_id) if row.jump_server_id else None
            return server_out(row, jump.name if jump else None)

    async def _validate_services(
        self, session: AsyncSession, services: list[ServiceSpec]
    ) -> list[tuple[str, int]]:
        codes = [item.code for item in services]
        if len(codes) != len(set(codes)):
            raise ValidationError("Микросервис указан дважды", code="duplicate_service")
        ports = [item.port for item in services]
        if len(ports) != len(set(ports)):
            raise ValidationError("Порт указан дважды", code="duplicate_port")
        return [(item.code, item.port) for item in services]

    async def create(self, payload: ServerCreate) -> ServerOut:
        async with self.session_factory() as session:
            jump = None
            if payload.jump_server_id:
                jump = await session.get(Server, payload.jump_server_id)
                if jump is None:
                    raise ValidationError("Jump-сервер не найден", code="jump_not_found")
            services = await self._validate_services(session, payload.services)
            try:
                row = await create_server(
                    session,
                    name=payload.name.strip(),
                    host=payload.host.strip(),
                    public_host=(payload.public_host or "").strip() or None,
                    ssh_port=payload.ssh_port,
                    username=payload.username.strip(),
                    password_encrypted=self.box.encrypt(payload.password),
                    jump_server_id=payload.jump_server_id,
                    bind_host=payload.bind_host.strip(),
                    priority=payload.priority,
                    is_fallback=payload.is_fallback,
                    is_jump=payload.is_jump,
                    notes=payload.notes,
                    services=services,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise ConflictError(
                    "Сервер с таким хостом и SSH-портом уже есть. "
                    "Закройте форму и нажмите «Изменить» у существующего сервера.",
                    code="server_exists",
                ) from exc
            except Exception as exc:
                await session.rollback()
                logger.exception("failed to create server %s", payload.host)
                raise UpstreamError(
                    "Не удалось сохранить сервер. Попробуйте ещё раз.",
                    code="server_save_failed",
                ) from exc
            await audit(
                session,
                "server.created",
                server_id=row.id,
                details={"host": row.host, "services": services},
            )
            await session.commit()
            return server_out(row, jump.name if jump else None)

    async def update(self, server_id: uuid.UUID, payload: ServerUpdate) -> ServerOut:
        async with self.session_factory() as session:
            row = await get_server(session, server_id)
            if row is None:
                raise NotFoundError("Сервер не найден")
            values = payload.model_dump(exclude_unset=True)
            password = values.pop("password", None)
            if password:
                values["password_encrypted"] = self.box.encrypt(password)
            services = values.pop("services", None)
            if services is not None:
                parsed = [
                    ServiceSpec.model_validate(item) if isinstance(item, dict) else item
                    for item in services
                ]
                validated = await self._validate_services(session, parsed)
                values["services"] = validated
            if values.get("jump_server_id") == server_id:
                raise ValidationError("Сервер не может быть jump-сервером для себя")
            if values.get("jump_server_id"):
                jump = await session.get(Server, values["jump_server_id"])
                if jump is None:
                    raise ValidationError("Jump-сервер не найден", code="jump_not_found")
            try:
                row = await update_server(session, row, values)
            except IntegrityError as exc:
                await session.rollback()
                raise ConflictError(
                    "Сервер с таким хостом и SSH-портом уже существует",
                    code="server_exists",
                ) from exc
            except Exception as exc:
                await session.rollback()
                logger.exception("failed to update server %s", server_id)
                raise UpstreamError(
                    "Не удалось обновить сервер. Попробуйте ещё раз.",
                    code="server_save_failed",
                ) from exc
            audit_details = {
                key: value for key, value in values.items() if "password" not in key.lower()
            }
            await audit(session, "server.updated", server_id=row.id, details=audit_details)
            await session.commit()
            jump = await session.get(Server, row.jump_server_id) if row.jump_server_id else None
            return server_out(row, jump.name if jump else None)

    async def delete(self, server_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            row = await get_server(session, server_id)
            if row is None:
                raise NotFoundError("Сервер не найден")
            await delete_server(session, row)
            await audit(session, "server.deleted", server_id=server_id)
            await session.commit()

    async def deploy(
        self,
        server_id: uuid.UUID,
        services: list[ServiceSpec] | None,
        *,
        update: bool = True,
    ) -> DeployResponse:
        async with self.session_factory() as session:
            row = await get_server(session, server_id)
            if row is None:
                raise NotFoundError("Сервер не найден")
            if not row.enabled:
                raise ValidationError("Сервер отключён", code="server_disabled")
            specs = services or [
                ServiceSpec(code=item.code, port=item.port)  # type: ignore[arg-type]
                for item in row.services
            ]
            if not specs:
                raise ValidationError(
                    "Выберите хотя бы один микросервис для развёртывания",
                    code="no_services",
                )
            validated = await self._validate_services(session, specs)
            job = await self.deployer.start(row, validated, update=update)
            await audit(
                session,
                "deployment.started",
                server_id=row.id,
                details={"job_id": str(job.id), "services": validated},
            )
            await session.commit()
            return DeployResponse(job_id=job.id, status=job.status)

    async def console(
        self,
        server_id: uuid.UUID,
        payload: ConsoleRequest,
        *,
        admin: str | None = None,
    ) -> ConsoleResultOut:
        return await self.console_executor.execute(server_id, payload, admin=admin)

    async def console_history(
        self, server_id: uuid.UUID, limit: int = 50
    ) -> list[AuditOut]:
        return await console_history(self, server_id, limit)

    async def rollback(self, server_id: uuid.UUID) -> DeployResponse:
        server = await self._server_model(server_id)
        if not server.services:
            raise ValidationError(
                "На сервере нет настроенных сервисов для rollback.",
                code="no_services",
            )
        job = await self.deployer.start_rollback(server)
        async with self.session_factory() as session:
            await audit(
                session,
                "deployment.rollback_started",
                server_id=server.id,
                details={"job_id": str(job.id)},
            )
            await session.commit()
        return DeployResponse(job_id=job.id, status=job.status)

    async def change_port(
        self, server_id: uuid.UUID, code: str, port: int
    ) -> DeployResponse:
        server = await self._server_model(server_id)
        services = {item.code: item.port for item in server.services}
        if code not in services:
            raise ValidationError(
                f"Сервис {code} не настроен на этом сервере.",
                code="service_not_configured",
            )
        if any(other != code and value == port for other, value in services.items()):
            raise ValidationError(
                f"Порт {port} уже занят другим сервисом.", code="port_in_use"
            )
        updated = [
            ServiceSpec(code=item, port=(port if item == code else value))
            for item, value in services.items()
        ]
        await self.update(server_id, ServerUpdate(services=updated))
        return await self.deploy(
            server_id, [ServiceSpec(code=code, port=port)], update=True
        )

    async def add_service(
        self, server_id: uuid.UUID, code: str, port: int
    ) -> DeployResponse:
        server = await self._server_model(server_id)
        services = {item.code: item.port for item in server.services}
        if code in services:
            raise ValidationError(
                f"Сервис {code} уже настроен на этом сервере.",
                code="service_exists",
            )
        if code not in get_args(ServiceCode):
            raise ValidationError(
                f"Неизвестный микросервис {code}.", code="service_unknown"
            )
        if any(value == port for value in services.values()):
            raise ValidationError(
                f"Порт {port} уже занят другим сервисом.", code="port_in_use"
            )
        updated = [
            ServiceSpec(code=item, port=value) for item, value in services.items()
        ]
        updated.append(ServiceSpec(code=code, port=port))
        await self.update(server_id, ServerUpdate(services=updated))
        return await self.deploy(
            server_id, [ServiceSpec(code=code, port=port)], update=True
        )

    async def jobs(self, limit: int = 30) -> list[JobOut]:
        await self.deployer.reap_stale_jobs()
        async with self.session_factory() as session:
            rows = await list_jobs(session, limit)
            return [job_out(row) for row in rows]

    async def job(self, job_id: uuid.UUID) -> JobOut:
        await self.deployer.reap_stale_jobs()
        async with self.session_factory() as session:
            row = await get_job(session, job_id)
            if row is None:
                raise NotFoundError("Задача деплоя не найдена")
            return job_out(row)

    async def cancel_job(self, job_id: uuid.UUID) -> JobOut:
        await self.deployer.cancel_job(job_id, "Deployment cancelled by administrator")
        async with self.session_factory() as session:
            row = await get_job(session, job_id)
            if row is None:
                raise NotFoundError("Задача деплоя не найдена")
            return job_out(row)

    async def reap_stale_jobs(self) -> int:
        return await self.deployer.reap_stale_jobs()

    async def _check_service(self, endpoint: RegistryEndpoint) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{endpoint.url}/health")
            if response.status_code == 200:
                return True, None
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)[:512]

    async def health_check_all(self) -> list[ServerHealthOut]:
        async with self.session_factory() as session:
            rows = await list_servers(session)
            results: list[ServerHealthOut] = []
            for row in rows:
                service_results: list[ServiceOut] = []
                for service in row.services:
                    if service.code not in HTTP_SERVICES:
                        service.healthy = True
                        service.checked_at = datetime.now(UTC)
                        service_results.append(
                            ServiceOut(code=service.code, port=service.port, healthy=True)
                        )
                        continue
                    endpoint = self._endpoint(row, service)
                    healthy, error = await self._check_service(endpoint)
                    service.healthy = healthy
                    service.checked_at = datetime.now(UTC)
                    service.last_error = error
                    service_results.append(
                        ServiceOut(
                            code=service.code,
                            port=service.port,
                            healthy=healthy,
                            checked_at=service.checked_at,
                            last_error=error,
                        )
                    )
                await session.flush()
                results.append(
                    ServerHealthOut(
                        server_id=row.id,
                        name=row.name,
                        host=row.host,
                        healthy=all(item.healthy for item in service_results) if service_results else False,
                        services=service_results,
                    )
                )
            await session.commit()
            return results

    def _local_hosts(self) -> set[str]:
        hosts = {"127.0.0.1", "localhost", "::1"}
        for url in (
            self.settings.control_public_url,
            self.settings.public_api_url,
            self.settings.public_web_url,
        ):
            parsed = urlparse(url)
            if parsed.hostname:
                hosts.add(parsed.hostname)
                try:
                    for info in socket.getaddrinfo(parsed.hostname, None):
                        hosts.add(str(info[4][0]).split("%", 1)[0])
                except OSError:
                    pass
        return hosts

    def _endpoint(self, server: Server, service) -> RegistryEndpoint:  # type: ignore[no-untyped-def]
        public_host = (server.public_host or server.host or "").strip()
        if service.code == "replica":
            # Replicas are pulled by peers, so the registry must advertise an
            # address that is reachable from other nodes even when the primary
            # app services themselves bind to loopback.
            host = public_host or server.host
        elif server.host in self._local_hosts():
            # The control plane runs on this machine; loopback is the shortest path.
            host = "127.0.0.1" if server.bind_host in {"127.0.0.1", "localhost"} else public_host
        else:
            # Remote nodes are reached by their public address.  A loopback bind
            # on a remote node is expected to fail the check until the operator
            # switches it to 0.0.0.0 (or puts a reverse proxy on that node).
            host = public_host or server.host
        return RegistryEndpoint(
            server_id=server.id,
            server_name=server.name,
            host=host,
            port=service.port,
            url=f"http://{host}:{service.port}",
            healthy=service.healthy,
            is_fallback=server.is_fallback,
            priority=server.priority,
            is_jump=server.is_jump,
            checked_at=service.checked_at,
            last_error=service.last_error,
        )

    async def registry(self) -> RegistryOut:
        async with self.session_factory() as session:
            rows = await list_servers(session)
            server_meta = {
                row.id: (
                    row.is_jump,
                    row.created_at or datetime.min.replace(tzinfo=UTC),
                )
                for row in rows
            }
            services: dict[str, list[RegistryEndpoint]] = {}
            for row in rows:
                if not row.enabled:
                    continue
                for service in row.services:
                    endpoint = self._endpoint(row, service)
                    services.setdefault(service.code, []).append(endpoint)
            for items in services.values():
                items.sort(
                    key=lambda item: (
                        item.is_fallback,
                        not item.healthy,
                        item.priority,
                        server_meta[item.server_id][0],
                        server_meta[item.server_id][1],
                    )
                )
            return RegistryOut(services=services)

    async def select(self, service: str) -> RegistryEndpoint | None:
        registry = await self.registry()
        items = registry.services.get(service, [])
        for item in items:
            if item.healthy and not item.is_fallback:
                return item
        for item in items:
            if item.healthy:
                return item
        return items[0] if items else None

    async def server_health(self, server_id: uuid.UUID) -> ServerHealthOut:
        all_health = await self.health_check_all()
        for item in all_health:
            if item.server_id == server_id:
                return item
        raise NotFoundError("Сервер не найден")

    async def _run_on_server(self, server: Server, script: str, timeout: float = 300.0) -> tuple[int, str]:
        target, jump = await self.deployer._target(server)
        return await asyncio.to_thread(
            self.ssh.run_script, target, script, jump=jump, timeout=timeout
        )

    async def _replica_script(self, server: Server, body: str, stores: str) -> tuple[int, str]:
        root = shlex.quote(self.settings.deploy_root.rstrip("/"))
        payload = shlex.quote(body)
        script = f"""set -u
ROOT={root}
TOKEN=$(grep '^INTERNAL_TOKEN=' "$ROOT/.env" | cut -d= -f2-)
systemctl start mangapoisk-replica.service 2>/dev/null || true
for svc in catalog library media; do systemctl stop "mangapoisk-$svc.service" 2>/dev/null || true; done
curl -fsS --max-time 240 -X POST "http://127.0.0.1:8108/internal/replica/{stores}" \\
  -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' -d {payload}
CODE=$?
for svc in catalog library media; do systemctl start "mangapoisk-$svc.service" 2>/dev/null || true; done
exit $CODE
"""
        return await self._run_on_server(server, script)

    async def promote_replica(self, server_id: uuid.UUID) -> ReplicaActionOut:
        server = await self._server_model(server_id)
        body = json.dumps({"stores": ["catalog", "library", "media"]})
        code, output = await self._replica_script(server, body, "promote")
        if code != 0:
            raise UpstreamError(
                "Не удалось восстановить данные из реплики",
                code="replica_promote_failed",
                details=output[-2000:],
            )
        await self.health_check_all()
        return ReplicaActionOut(ok=True, log=output[-4000:])

    async def bootstrap_replica(self, server_id: uuid.UUID, source_id: uuid.UUID) -> ReplicaActionOut:
        server = await self._server_model(server_id)
        if server_id == source_id:
            raise ValidationError("Нельзя восстановить сервер из самого себя")
        source = await self._server_model(source_id)
        source_host = (source.public_host or source.host).strip()
        if not source_host:
            raise ValidationError("У исходного сервера не указан адрес")
        body = json.dumps(
            {"source": f"http://{source_host}:8108", "promote": True, "stores": ["catalog", "library", "media"]}
        )
        code, output = await self._replica_script(server, body, "bootstrap")
        if code != 0:
            raise UpstreamError(
                "Не удалось скопировать данные с исходного сервера",
                code="replica_bootstrap_failed",
                details=output[-2000:],
            )
        await self.health_check_all()
        return ReplicaActionOut(ok=True, log=output[-4000:])

    async def service_urls(self) -> dict[str, str]:
        registry = await self.registry()
        urls: dict[str, str] = {}
        for code, items in registry.services.items():
            for item in items:
                if item.healthy:
                    urls[code] = item.url
                    break
            else:
                if items:
                    urls[code] = items[0].url
        return urls
