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
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
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
    last_output_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    server: Mapped[Server] = relationship(back_populates="jobs")


class AuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "audit_log"

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)


class IntegrationSecret(Base, UUIDPrimaryKey, TimestampMixin):
    """Encrypted credential value for an external integration.

    Values are encrypted with the same Fernet key as SSH/ad secrets.  Only the
    masked hint is returned to the admin UI; the plaintext is available solely
    through the internal credentials endpoint used by the gateway.
    """

    __tablename__ = "integration_secrets"
    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_integration_secrets_provider_name"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str] = mapped_column(String(32), nullable=False, default="")


class IntegrationSetting(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "integration_settings"

    provider: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AdProvider(Base, UUIDPrimaryKey, TimestampMixin):
    """A configured advertising integration and its slot placement.

    Secret values live in :class:`AdSecret`; this row only keeps non-secret
    presentation and scheduling data so it can be returned to the admin UI.
    """

    __tablename__ = "ad_providers"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    placement: Mapped[str] = mapped_column(String(32), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False, default="both")
    frequency_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_days: Mapped[list[int]] = mapped_column(JSONType, nullable=False, default=list)
    schedule_start: Mapped[str] = mapped_column(String(5), nullable=False, default="00:00")
    schedule_end: Mapped[str] = mapped_column(String(5), nullable=False, default="23:59")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    custom_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    custom_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exclude_adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hide_for_donors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    secrets: Mapped[list[AdSecret]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", passive_deletes=True
    )


class AdSecret(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ad_secrets"
    __table_args__ = (
        UniqueConstraint("provider_id", "name", name="uq_ad_secrets_provider_name"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ad_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    provider: Mapped[AdProvider] = relationship(back_populates="secrets")
