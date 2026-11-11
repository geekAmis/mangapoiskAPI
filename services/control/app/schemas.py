from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ServiceCode = Literal[
    "parser", "catalog", "library", "media", "control", "gateway", "notifier", "scheduler"
]
HTTP_SERVICES = {"parser", "catalog", "library", "media", "control", "gateway", "notifier"}


class ServiceSpec(BaseModel):
    code: ServiceCode
    port: int = Field(ge=1024, le=65535)


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    public_host: str | None = Field(default=None, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="root", min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)
    jump_server_id: UUID | None = None
    bind_host: str = Field(default="0.0.0.0", max_length=64)
    is_fallback: bool = False
    is_jump: bool = False
    notes: str | None = Field(default=None, max_length=2000)
    services: list[ServiceSpec] = Field(default_factory=list)


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    public_host: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    jump_server_id: UUID | None = None
    bind_host: str | None = Field(default=None, max_length=64)
    is_fallback: bool | None = None
    is_jump: bool | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    services: list[ServiceSpec] | None = None


class ServiceOut(BaseModel):
    code: str
    port: int
    healthy: bool = False
    checked_at: datetime | None = None
    last_error: str | None = None


class ServerOut(BaseModel):
    id: UUID
    name: str
    host: str
    public_host: str | None = None
    ssh_port: int
    username: str
    jump_server_id: UUID | None = None
    jump_server_name: str | None = None
    bind_host: str
    is_fallback: bool
    is_jump: bool
    enabled: bool
    notes: str | None = None
    services: list[ServiceOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeployRequest(BaseModel):
    services: list[ServiceSpec] | None = None
    update: bool = True


class DeployResponse(BaseModel):
    job_id: UUID
    status: str


class JobOut(BaseModel):
    id: UUID
    server_id: UUID
    status: str
    requested: dict[str, Any] = Field(default_factory=dict)
    log: str = ""
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RegistryEndpoint(BaseModel):
    server_id: UUID
    server_name: str
    host: str
    port: int
    url: str
    healthy: bool
    is_fallback: bool
    checked_at: datetime | None = None
    last_error: str | None = None


class RegistryOut(BaseModel):
    services: dict[str, list[RegistryEndpoint]]


class SelectRequest(BaseModel):
    service: str = Field(min_length=1, max_length=32)


class SelectResponse(BaseModel):
    service: str
    url: str | None
    endpoint: RegistryEndpoint | None = None


class ServerHealthOut(BaseModel):
    server_id: UUID
    name: str
    host: str
    healthy: bool
    services: list[ServiceOut]


class AuditOut(BaseModel):
    id: UUID
    action: str
    server_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
