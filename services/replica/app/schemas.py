from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

StoreName = Literal["catalog", "library", "control", "media"]
SyncStatus = Literal["pulled", "unchanged", "skipped", "failed"]


class SnapshotMeta(BaseModel):
    store: StoreName
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    updated_at: datetime
    source: str | None = None


class ArchiveEntry(BaseModel):
    name: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    updated_at: datetime


class ArchiveManifest(BaseModel):
    archives: list[ArchiveEntry] = Field(default_factory=list)
    count: int = 0
    bytes: int = 0


class ArchiveCopySummary(BaseModel):
    copied: int = 0
    skipped: int = 0
    bytes: int = 0


class ArchiveSyncSummary(BaseModel):
    source: str | None = None
    pulled: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    errors: list[str] = Field(default_factory=list)


class StoreSyncResult(BaseModel):
    store: StoreName
    status: SyncStatus
    source: str | None = None
    size: int | None = None
    sha256: str | None = None
    error: str | None = None


class SyncReport(BaseModel):
    mode: Literal["registry", "peers"]
    peers: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    stores: dict[str, StoreSyncResult] = Field(default_factory=dict)
    archives: ArchiveSyncSummary | None = None
    errors: dict[str, str] = Field(default_factory=dict)


class PromoteResult(BaseModel):
    store: StoreName
    promoted: bool
    live_path: str
    snapshot_path: str | None = None
    backup_path: str | None = None
    size: int | None = None
    sha256: str | None = None
    updated_at: datetime | None = None
    error: str | None = None


class PromoteResponse(BaseModel):
    results: list[PromoteResult] = Field(default_factory=list)


class SyncRequest(BaseModel):
    peers: list[str] | None = None
    stores: list[StoreName] | None = None


class BootstrapRequest(BaseModel):
    source: str = Field(min_length=1, max_length=2048)
    stores: list[StoreName] | None = None
    promote: bool = False


class PromoteRequest(BaseModel):
    stores: list[StoreName] | None = None


class BootstrapResponse(SyncReport):
    source: str
    promoted: list[PromoteResult] = Field(default_factory=list)
    archives_copied: int = 0
    archives_skipped: int = 0


class SyncStateOut(BaseModel):
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_source: str | None = None
    last_error: str | None = None
    store_errors: dict[str, str] = Field(default_factory=dict)
    report: SyncReport | None = None


class StoreStatus(BaseModel):
    store: StoreName
    available: bool
    size: int | None = None
    sha256: str | None = None
    updated_at: datetime | None = None
    source: str | None = None
    error: str | None = None


class ArchiveStatus(BaseModel):
    count: int = 0
    bytes: int = 0


class ReplicaStatus(BaseModel):
    service: str = "replica"
    self_url: str
    sync_disabled: bool
    stores: dict[str, StoreStatus] = Field(default_factory=dict)
    archives: ArchiveStatus = Field(default_factory=ArchiveStatus)
    last_sync: SyncStateOut = Field(default_factory=SyncStateOut)
    last_error: str | None = None
    store_errors: dict[str, str] = Field(default_factory=dict)
