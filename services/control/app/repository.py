from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import AuditLog, DeploymentJob, Server, ServerService
from .schemas import AuditOut, JobOut, ServerOut, ServiceOut


def _services(server: Server) -> list[ServiceOut]:
    return [
        ServiceOut(
            code=item.code,
            port=item.port,
            healthy=item.healthy,
            checked_at=item.checked_at,
            last_error=item.last_error,
        )
        for item in sorted(server.services, key=lambda row: row.code)
    ]


def server_out(server: Server, jump_name: str | None = None) -> ServerOut:
    return ServerOut(
        id=server.id,
        name=server.name,
        host=server.host,
        public_host=server.public_host,
        ssh_port=server.ssh_port,
        username=server.username,
        jump_server_id=server.jump_server_id,
        jump_server_name=jump_name,
        bind_host=server.bind_host,
        priority=server.priority,
        is_fallback=server.is_fallback,
        is_jump=server.is_jump,
        enabled=server.enabled,
        notes=server.notes,
        services=_services(server),
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def job_out(job: DeploymentJob) -> JobOut:
    return JobOut(
        id=job.id,
        server_id=job.server_id,
        status=job.status,
        requested=job.requested or {},
        log=job.log or "",
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def audit_out(row: AuditLog) -> AuditOut:
    return AuditOut(
        id=row.id,
        action=row.action,
        server_id=row.server_id,
        details=row.details or {},
        created_at=row.created_at,
    )


async def list_servers(session: AsyncSession) -> list[Server]:
    result = await session.scalars(
        select(Server).options(selectinload(Server.services)).order_by(Server.created_at.asc())
    )
    return list(result.unique().all())


async def get_server(session: AsyncSession, server_id: uuid.UUID) -> Server | None:
    return await session.scalar(
        select(Server).options(selectinload(Server.services)).where(Server.id == server_id)
    )


async def find_server_by_host(
    session: AsyncSession, host: str, port: int
) -> Server | None:
    return await session.scalar(
        select(Server).where(Server.host == host, Server.ssh_port == port)
    )


async def create_server(
    session: AsyncSession,
    *,
    name: str,
    host: str,
    public_host: str | None,
    ssh_port: int,
    username: str,
    password_encrypted: str,
    jump_server_id: uuid.UUID | None,
    bind_host: str,
    priority: int,
    is_fallback: bool,
    is_jump: bool,
    notes: str | None,
    services: list[tuple[str, int]],
) -> Server:
    server = Server(
        name=name,
        host=host,
        public_host=public_host,
        ssh_port=ssh_port,
        username=username,
        password_encrypted=password_encrypted,
        jump_server_id=jump_server_id,
        bind_host=bind_host,
        priority=priority,
        is_fallback=is_fallback,
        is_jump=is_jump,
        notes=notes,
    )
    session.add(server)
    await session.flush()
    for code, port in services:
        session.add(ServerService(server_id=server.id, code=code, port=port))
    await session.flush()
    await session.refresh(server, attribute_names=["services"])
    return server


async def update_server(session: AsyncSession, server: Server, values: dict) -> Server:
    services = values.pop("services", None)
    for key, value in values.items():
        setattr(server, key, value)
    if services is not None:
        await session.execute(delete(ServerService).where(ServerService.server_id == server.id))
        for code, port in services:
            session.add(ServerService(server_id=server.id, code=code, port=port))
    await session.flush()
    await session.refresh(server, attribute_names=["services"])
    return server


async def delete_server(session: AsyncSession, server: Server) -> None:
    await session.delete(server)
    await session.flush()


async def create_job(
    session: AsyncSession, server_id: uuid.UUID, requested: dict
) -> DeploymentJob:
    job = DeploymentJob(server_id=server_id, requested=requested, status="queued", log="")
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> DeploymentJob | None:
    return await session.get(DeploymentJob, job_id)


async def update_job(
    session: AsyncSession,
    job: DeploymentJob,
    *,
    status: str | None = None,
    log: str | None = None,
    error: str | None = None,
) -> DeploymentJob:
    if status is not None:
        job.status = status
    if log is not None:
        job.log = log
    if error is not None:
        job.error = error
    await session.flush()
    return job


async def append_job_log(session: AsyncSession, job_id: uuid.UUID, text: str) -> None:
    job = await session.get(DeploymentJob, job_id)
    if job is not None:
        job.log = ((job.log or "") + text)[-200_000:]
        await session.flush()


async def audit(
    session: AsyncSession,
    action: str,
    *,
    server_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    session.add(AuditLog(action=action, server_id=server_id, details=details or {}))
    await session.flush()


async def list_audit(session: AsyncSession, limit: int = 100) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return list(result.all())
