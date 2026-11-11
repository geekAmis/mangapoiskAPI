from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from manga_common.errors import ConflictError, NotFoundError, UpstreamError, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import ControlSettings
from .crypto import SecretBox
from .deployer import Deployer
from .models import Server
from .repository import (
    audit,
    create_server,
    delete_server,
    get_server,
    list_servers,
    server_out,
    update_server,
)
from .schemas import (
    HTTP_SERVICES,
    DeployResponse,
    RegistryEndpoint,
    RegistryOut,
    ServerCreate,
    ServerHealthOut,
    ServerOut,
    ServerUpdate,
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
            except Exception as exc:
                await session.rollback()
                raise ConflictError("Не удалось обновить сервер", details=str(exc)) from exc
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
            if row.is_jump:
                raise ValidationError(
                    "Jump-сервер используется только для SSH-доступа и не запускает микросервисы.",
                    code="jump_server_deploy_forbidden",
                )
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
        return hosts

    def _endpoint(self, server: Server, service) -> RegistryEndpoint:  # type: ignore[no-untyped-def]
        public_host = (server.public_host or server.host or "").strip()
        if server.host in self._local_hosts():
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
            checked_at=service.checked_at,
            last_error=service.last_error,
        )

    async def registry(self) -> RegistryOut:
        async with self.session_factory() as session:
            rows = await list_servers(session)
            services: dict[str, list[RegistryEndpoint]] = {}
            for row in rows:
                if not row.enabled:
                    continue
                for service in row.services:
                    endpoint = self._endpoint(row, service)
                    services.setdefault(service.code, []).append(endpoint)
            for items in services.values():
                items.sort(key=lambda item: (item.is_fallback, not item.healthy, item.server_name))
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
