from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ServiceCode = Literal[
    "parser", "catalog", "library", "media", "control", "gateway", "notifier", "replica", "comments", "scheduler"
]
HTTP_SERVICES = {"parser", "catalog", "library", "media", "control", "gateway", "notifier", "replica", "comments"}

_HOST_RE = r"^[A-Za-z0-9._:\-\[\]]+$"


class _ServerFields(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if any(ch in cleaned for ch in "\r\n\t"):
            raise ValueError("Имя не должно содержать переводы строк")
        return cleaned

    @field_validator("host", "public_host", "bind_host", check_fields=False)
    @classmethod
    def _clean_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if any(ch in cleaned for ch in "\r\n\t \"'`;$|&"):
            raise ValueError("Некорректный адрес сервера")
        return cleaned

    @field_validator("username", check_fields=False)
    @classmethod
    def _clean_username(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned or any(ch in cleaned for ch in "\r\n\t \"'`;$|&/"):
            raise ValueError("Некорректное имя SSH-пользователя")
        return cleaned


class ServiceSpec(BaseModel):
    code: ServiceCode
    port: int = Field(ge=1024, le=65535)


class ServerCreate(_ServerFields):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    public_host: str | None = Field(default=None, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="root", min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)
    jump_server_id: UUID | None = None
    bind_host: str = Field(default="0.0.0.0", max_length=64)
    priority: int = Field(default=100, ge=0, le=10000)
    is_fallback: bool = False
    is_jump: bool = False
    notes: str | None = Field(default=None, max_length=2000)
    services: list[ServiceSpec] = Field(default_factory=list)


class ServerUpdate(_ServerFields):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    public_host: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    jump_server_id: UUID | None = None
    bind_host: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=0, le=10000)
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
    priority: int = 100
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
    last_output_at: datetime | None = None


class RegistryEndpoint(BaseModel):
    server_id: UUID
    server_name: str
    host: str
    port: int
    url: str
    healthy: bool
    is_fallback: bool
    priority: int = 100
    is_jump: bool = False
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


class ReplicaActionOut(BaseModel):
    ok: bool
    log: str = ""


class ReplicaBootstrapRequest(BaseModel):
    source_server_id: UUID


class AuditOut(BaseModel):
    id: UUID
    action: str
    server_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ConsoleRequest(BaseModel):
    """Either a read-only allowlisted ``command`` or a structured ``action``."""

    command: str | None = Field(default=None, max_length=1000)
    action: str | None = Field(default=None, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class ConsoleResultOut(BaseModel):
    ok: bool
    kind: Literal["command", "action"]
    action: str
    command: str | None = None
    output: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    truncated: bool = False
    timed_out: bool = False
    output_hash: str | None = None
    job_id: UUID | None = None
    message: str | None = None
