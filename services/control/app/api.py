from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request

from manga_common.errors import NotFoundError
from manga_common.security import require_internal_token

from .repository import audit_out, get_job, job_out, list_audit
from .schemas import (
    AuditOut,
    DeployRequest,
    DeployResponse,
    JobOut,
    RegistryOut,
    SelectRequest,
    SelectResponse,
    ServerCreate,
    ServerHealthOut,
    ServerOut,
    ServerUpdate,
)
from .service import ControlService

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_service(request: Request) -> ControlService:
    return request.app.state.service


@router.get("/servers", response_model=list[ServerOut])
async def servers(service: ControlService = Depends(get_service)) -> list[ServerOut]:
    return await service.servers()


@router.post("/servers", response_model=ServerOut)
async def create_server(
    payload: ServerCreate, service: ControlService = Depends(get_service)
) -> ServerOut:
    return await service.create(payload)


@router.patch("/servers/{server_id}", response_model=ServerOut)
async def update_server(
    server_id: uuid.UUID,
    payload: ServerUpdate,
    service: ControlService = Depends(get_service),
) -> ServerOut:
    return await service.update(server_id, payload)


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: uuid.UUID, service: ControlService = Depends(get_service)
) -> dict[str, bool]:
    await service.delete(server_id)
    return {"ok": True}


@router.post("/servers/{server_id}/deploy", response_model=DeployResponse)
async def deploy_server(
    server_id: uuid.UUID,
    payload: DeployRequest,
    service: ControlService = Depends(get_service),
) -> DeployResponse:
    return await service.deploy(server_id, payload.services, update=payload.update)


@router.get("/servers/{server_id}/health", response_model=ServerHealthOut)
async def server_health(
    server_id: uuid.UUID, service: ControlService = Depends(get_service)
) -> ServerHealthOut:
    return await service.server_health(server_id)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job(
    job_id: uuid.UUID, service: ControlService = Depends(get_service)
) -> JobOut:
    async with service.session_factory() as session:
        row = await get_job(session, job_id)
        if row is None:
            raise NotFoundError("Задача деплоя не найдена")
        return job_out(row)


@router.get("/registry", response_model=RegistryOut)
async def registry(service: ControlService = Depends(get_service)) -> RegistryOut:
    return await service.registry()


@router.post("/registry/refresh", response_model=RegistryOut)
async def refresh_registry(service: ControlService = Depends(get_service)) -> RegistryOut:
    await service.health_check_all()
    return await service.registry()


@router.post("/registry/select", response_model=SelectResponse)
async def select_endpoint(
    payload: SelectRequest, service: ControlService = Depends(get_service)
) -> SelectResponse:
    endpoint = await service.select(payload.service)
    return SelectResponse(
        service=payload.service,
        url=endpoint.url if endpoint else None,
        endpoint=endpoint,
    )


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    service: ControlService = Depends(get_service),
) -> list[AuditOut]:
    async with service.session_factory() as session:
        rows = await list_audit(session, limit)
        return [audit_out(row) for row in rows]
