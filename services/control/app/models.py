from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")


class Server(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "servers"
    __table_args__ = (UniqueConstraint("host", "ssh_port", name="uq_servers_host_port"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    public_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="root")
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    jump_server_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("servers.id", ondelete="SET NULL"), nullable=True
    )
    bind_host: Mapped[str] = mapped_column(String(64), nullable=False, default="0.0.0.0")
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_jump: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    services: Mapped[list[ServerService]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list[DeploymentJob]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )


class ServerService(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "server_services"
    __table_args__ = (
        UniqueConstraint("server_id", "code", name="uq_server_services_server_code"),
        UniqueConstraint("server_id", "port", name="uq_server_services_server_port"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    server: Mapped[Server] = relationship(back_populates="services")


class DeploymentJob(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "deployment_jobs"

    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    requested: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    server: Mapped[Server] = relationship(back_populates="jobs")


class AuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "audit_log"

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
