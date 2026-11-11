from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from .config import STORE_NAMES, ReplicaSettings
from .registry import (
    normalize_url,
    select_replica_target,
    urls_match,
)
from .schemas import (
    ArchiveEntry,
    ArchiveStatus,
    ArchiveSyncSummary,
    BootstrapResponse,
    PromoteResponse,
    PromoteResult,
    ReplicaStatus,
    SnapshotMeta,
    StoreStatus,
    StoreSyncResult,
    SyncReport,
    SyncStateOut,
)
from .store import SnapshotStore, ensure_store, safe_archive_name

logger = logging.getLogger(__name__)

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_DEFAULT_ATTEMPTS = 3
_DEFAULT_BACKOFF_SECONDS = 0.5
_MAX_ARCHIVE_ERRORS = 10


class _RetryableStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Retryable upstream status {status_code}")
        self.status_code = status_code


def resolve_stores(stores: Sequence[str] | None) -> list[str]:
    if not stores:
        return list(STORE_NAMES)
    resolved: list[str] = []
    for store in stores:
        ensure_store(store)
        if store not in resolved:
            resolved.append(store)
    return resolved


def _short_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]


class ReplicaSync:
    """Pulls snapshots and archives from registry-selected peers."""

    def __init__(
        self,
        settings: ReplicaSettings,
        store: SnapshotStore,
        *,
        client: httpx.AsyncClient | None = None,
        attempts: int = _DEFAULT_ATTEMPTS,
        backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.settings = settings
        self.store = store
        self._client = client
        self._owns_client = client is None
        self._attempts = max(1, attempts)
        self._backoff_seconds = max(0.0, backoff_seconds)
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_source: str | None = None
        self._last_error: str | None = None
        self._store_errors: dict[str, str] = {}
        self._last_report: SyncReport | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def startup(self) -> None:
        if self.settings.sync_disabled:
            logger.info("replica background sync disabled")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="replica-sync")

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _loop(self) -> None:
        logger.info(
            "replica sync loop started interval=%ss registry=%s",
            self.settings.sync_seconds,
            self.settings.registry_url,
        )
        while not self._stop.is_set():
            started = asyncio.get_running_loop().time()
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("replica sync loop iteration failed")
            elapsed = asyncio.get_running_loop().time() - started
            delay = max(0.0, float(self.settings.sync_seconds) - elapsed)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
        logger.info("replica sync loop stopped")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or (self._owns_client and self._client.is_closed):
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                follow_redirects=True,
            )
        return self._client

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Internal-Token": self.settings.internal_token,
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    async def sync(
        self,
        *,
        peers: Sequence[str] | None = None,
        stores: Sequence[str] | None = None,
    ) -> SyncReport:
        selected = resolve_stores(stores)
        started = datetime.now(UTC)
        async with self._lock:
            if peers:
                report = await self._sync_peers(selected, list(peers))
            else:
                report = await self._sync_registry(selected)
            report.started_at = started
            report.finished_at = datetime.now(UTC)
            self._record(report)
            return report

    async def sync_once(self) -> SyncReport:
        """Run one registry-driven cycle (used by the background task)."""

        return await self.sync()

    async def bootstrap(
        self,
        source: str,
        *,
        stores: Sequence[str] | None = None,
        promote: bool = False,
    ) -> BootstrapResponse:
        selected = resolve_stores(stores)
        peer = normalize_url(source)
        started = datetime.now(UTC)
        async with self._lock:
            report = self._report("peers", [peer] if peer else [])
            report = BootstrapResponse(
                **report.model_dump(),
                source=peer,
            )
            if not peer or self._is_self(peer):
                message = "bootstrap source is empty or points at this node"
                self._fail_all(report, selected, message)
            else:
                for store in selected:
                    result = await self._pull_store(store, peer)
                    report.stores[store] = result
                    if result.status == "failed":
                        report.errors[store] = result.error or "snapshot pull failed"
                if "media" in selected:
                    archives = await self._pull_archives(peer)
                    report.archives = archives
                    self._merge_archive_error(report, archives)
                if promote:
                    for store in selected:
                        try:
                            report.promoted.append(await self.store.promote(store))
                        except Exception as exc:
                            logger.warning("promote failed store=%s error=%s", store, exc)
                            report.promoted.append(
                                PromoteResult(
                                    store=store,
                                    promoted=False,
                                    live_path=str(self.store.live_db_path(store)),
                                    error=_short_error(exc),
                                )
                            )
                    copied = await self.store.promote_archives()
                    report.archives_copied = copied.copied
                    report.archives_skipped = copied.skipped
            report.started_at = started
            report.finished_at = datetime.now(UTC)
            self._record(report)
            return report

    async def promote(self, *, stores: Sequence[str] | None = None) -> PromoteResponse:
        selected = resolve_stores(stores)
        results: list[PromoteResult] = []
        for store in selected:
            try:
                results.append(await self.store.promote(store))
            except Exception as exc:
                logger.warning("promote failed store=%s error=%s", store, exc)
                results.append(
                    PromoteResult(
                        store=store,
                        promoted=False,
                        live_path=str(self.store.live_db_path(store)),
                        error=_short_error(exc),
                    )
                )
        return PromoteResponse(results=results)

    async def status(self) -> ReplicaStatus:
        stores: dict[str, StoreStatus] = {}
        for store in STORE_NAMES:
            meta = await self.store.meta(store)
            stores[store] = StoreStatus(
                store=store,
                available=meta is not None,
                size=meta.size if meta else None,
                sha256=meta.sha256 if meta else None,
                updated_at=meta.updated_at if meta else None,
                source=meta.source if meta else None,
                error=self._store_errors.get(store),
            )
        manifest = await self.store.archive_manifest()
        return ReplicaStatus(
            service=self.settings.service_name,
            self_url=self.settings.self_replica_url,
            sync_disabled=self.settings.sync_disabled,
            stores=stores,
            archives=ArchiveStatus(
                count=len(manifest),
                bytes=sum(item.size for item in manifest),
            ),
            last_sync=self._state(),
            last_error=self._last_error,
            store_errors=dict(self._store_errors),
        )

    # ------------------------------------------------------------------
    # Registry-driven sync
    # ------------------------------------------------------------------
    async def _sync_registry(self, selected: Sequence[str]) -> SyncReport:
        report = self._report("registry", [])
        try:
            registry = await self._fetch_registry()
        except Exception as exc:
            message = f"registry unavailable: {_short_error(exc)}"
            logger.warning("replica registry unavailable: %s", message)
            self._fail_all(report, selected, message)
            report.errors["registry"] = message
            return report

        media_peer: str | None = None
        for store in selected:
            target = select_replica_target(registry, store)
            if target is None:
                message = "no healthy leader with a replica endpoint in registry"
                result = StoreSyncResult(store=store, status="failed", error=message)
                report.stores[store] = result
                report.errors[store] = message
                continue
            if self._is_self(target.replica_url):
                # This node is the writer: refresh the local snapshot so peers
                # can pull it on their next cycle, and do not fetch from self.
                result = await self._snapshot_local(store)
                report.stores[store] = result
                if result.status == "failed":
                    report.errors[store] = result.error or "local snapshot failed"
                continue
            result = await self._pull_store(store, target.replica_url)
            report.stores[store] = result
            if result.status == "failed":
                report.errors[store] = result.error or "snapshot pull failed"
            if store == "media":
                media_peer = target.replica_url

        if "media" in selected and media_peer is not None:
            archives = await self._pull_archives(media_peer)
            report.archives = archives
            self._merge_archive_error(report, archives)
        return report

    # ------------------------------------------------------------------
    # Explicit-peer sync
    # ------------------------------------------------------------------
    async def _sync_peers(self, selected: Sequence[str], peers: Sequence[str]) -> SyncReport:
        clean: list[str] = []
        for peer in peers:
            normalized = normalize_url(peer)
            if normalized and normalized not in clean:
                clean.append(normalized)
        report = self._report("peers", clean)
        if not clean:
            self._fail_all(report, selected, "no peers supplied")
            return report

        for store in selected:
            result = await self._pull_store_from_peers(store, clean)
            report.stores[store] = result
            if result.status == "failed":
                report.errors[store] = result.error or "snapshot pull failed"

        if "media" in selected:
            media_result = report.stores.get("media")
            candidates = [media_result.source] if media_result and media_result.source else []
            candidates.extend(peer for peer in clean if peer not in candidates)
            archives = await self._pull_archives_from_peers(candidates)
            report.archives = archives
            self._merge_archive_error(report, archives)
        return report

    async def _snapshot_local(self, store: str) -> StoreSyncResult:
        live = self.store.live_db_path(store)
        if not live.is_file():
            return StoreSyncResult(
                store=store,
                status="failed",
                source=self.settings.self_replica_url,
                error=f"live database not found: {live}",
            )
        try:
            meta = await self.store.snapshot(store)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("local snapshot failed store=%s error=%s", store, exc)
            return StoreSyncResult(
                store=store,
                status="failed",
                source=self.settings.self_replica_url,
                error=_short_error(exc),
            )
        return StoreSyncResult(
            store=store,
            status="skipped",
            source=self.settings.self_replica_url,
            size=meta.size,
            sha256=meta.sha256,
        )

    async def _pull_store_from_peers(
        self, store: str, peers: Sequence[str]
    ) -> StoreSyncResult:
        errors: list[str] = []
        attempted = 0
        for peer in peers:
            if self._is_self(peer):
                continue
            attempted += 1
            result = await self._pull_store(store, peer)
            if result.status in {"pulled", "unchanged"}:
                return result
            if result.error:
                errors.append(f"{peer}: {result.error}")
        if attempted == 0:
            return StoreSyncResult(
                store=store,
                status="skipped",
                error="all supplied peers point at this node",
            )
        return StoreSyncResult(
            store=store,
            status="failed",
            error="; ".join(errors)[:1000] or "all peers failed",
        )

    async def _pull_store(self, store: str, peer: str) -> StoreSyncResult:
        base = normalize_url(peer)
        try:
            remote = await self._fetch_remote_meta(base, store)
            local = await self.store.meta(store)
            if (
                remote is not None
                and local is not None
                and remote.size == local.size
                and remote.sha256.lower() == local.sha256.lower()
            ):
                return StoreSyncResult(
                    store=store,
                    status="unchanged",
                    source=base,
                    size=local.size,
                    sha256=local.sha256,
                )

            temp = self.store.new_snapshot_temp(store)
            try:
                await self._download(
                    f"{base}/internal/replica/db/{store}",
                    temp,
                )
                meta = await self.store.install_snapshot(
                    store,
                    temp,
                    expected_sha256=remote.sha256 if remote else None,
                    expected_size=remote.size if remote else None,
                    updated_at=remote.updated_at if remote else None,
                    source=base,
                )
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
            return StoreSyncResult(
                store=store,
                status="pulled",
                source=base,
                size=meta.size,
                sha256=meta.sha256,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("snapshot pull failed store=%s peer=%s error=%s", store, base, exc)
            return StoreSyncResult(
                store=store,
                status="failed",
                source=base,
                error=_short_error(exc),
            )

    # ------------------------------------------------------------------
    # Archives
    # ------------------------------------------------------------------
    async def _pull_archives_from_peers(self, peers: Sequence[str]) -> ArchiveSyncSummary:
        aggregate = ArchiveSyncSummary()
        attempted = 0
        for peer in peers:
            if self._is_self(peer):
                continue
            attempted += 1
            summary = await self._pull_archives(peer)
            if aggregate.source is None:
                aggregate.source = peer
            aggregate.pulled += summary.pulled
            aggregate.skipped += summary.skipped
            aggregate.failed += summary.failed
            aggregate.bytes += summary.bytes
            for item in summary.errors:
                if len(aggregate.errors) < _MAX_ARCHIVE_ERRORS:
                    aggregate.errors.append(item)
            if summary.failed == 0:
                break
        if attempted == 0:
            aggregate.failed = 1
            aggregate.errors.append("all supplied peers point at this node")
        return aggregate

    async def _pull_archives(self, peer: str) -> ArchiveSyncSummary:
        base = normalize_url(peer)
        summary = ArchiveSyncSummary(source=base)
        try:
            manifest = await self._fetch_archive_manifest(base)
            local = {item.name: item for item in await self.store.archive_manifest()}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("archive manifest pull failed peer=%s error=%s", base, exc)
            summary.failed = 1
            summary.errors.append(_short_error(exc))
            return summary

        seen: set[str] = set()
        for entry in manifest:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            try:
                safe_archive_name(entry.name)
            except ValueError as exc:
                summary.failed += 1
                if len(summary.errors) < _MAX_ARCHIVE_ERRORS:
                    summary.errors.append(f"{entry.name}: {_short_error(exc)}")
                continue
            existing = local.get(entry.name)
            if (
                existing is not None
                and existing.size == entry.size
                and existing.sha256.lower() == entry.sha256.lower()
            ):
                summary.skipped += 1
                continue

            temp = self.store.new_archive_temp(entry.name)
            try:
                await self._download(
                    f"{base}/internal/replica/archives/{entry.name}",
                    temp,
                )
                installed = await self.store.install_archive(
                    entry.name,
                    temp,
                    expected_sha256=entry.sha256,
                    expected_size=entry.size,
                    updated_at=entry.updated_at,
                )
            except asyncio.CancelledError:
                temp.unlink(missing_ok=True)
                raise
            except Exception as exc:
                temp.unlink(missing_ok=True)
                summary.failed += 1
                if len(summary.errors) < _MAX_ARCHIVE_ERRORS:
                    summary.errors.append(f"{entry.name}: {_short_error(exc)}")
                continue
            local[entry.name] = installed
            summary.pulled += 1
            summary.bytes += installed.size
        return summary

    async def _fetch_archive_manifest(self, base: str) -> list[ArchiveEntry]:
        response = await self._get(f"{base}/internal/replica/archives")
        payload = response.json()
        if isinstance(payload, dict):
            raw = payload.get("archives", [])
        elif isinstance(payload, list):
            raw = payload
        else:
            raise ValueError("unexpected archive manifest payload")
        if not isinstance(raw, list):
            raise ValueError("unexpected archive manifest payload")
        entries: list[ArchiveEntry] = []
        for item in raw:
            try:
                entries.append(ArchiveEntry.model_validate(item))
            except ValidationError:
                logger.warning("ignoring malformed archive manifest entry peer=%s", base)
        return entries

    # ------------------------------------------------------------------
    # Registry and HTTP helpers
    # ------------------------------------------------------------------
    async def _fetch_registry(self) -> dict[str, Any]:
        response = await self._get(self.settings.registry_url)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
            raise ValueError("registry payload is missing the services mapping")
        return payload

    async def _fetch_remote_meta(self, base: str, store: str) -> SnapshotMeta | None:
        response = await self._get(
            f"{base}/internal/replica/db/{store}/meta",
            allow_status=frozenset({404}),
        )
        if response.status_code == 404:
            return None
        try:
            payload = response.json()
            return SnapshotMeta.model_validate({**payload, "store": store})
        except (TypeError, ValueError) as exc:
            logger.warning("invalid remote snapshot metadata peer=%s store=%s: %s", base, store, exc)
            return None

    async def _get(
        self,
        url: str,
        *,
        allow_status: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        last_error: BaseException | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                response = await self._get_client().get(url, headers=self._headers)
                if response.status_code in allow_status:
                    return response
                if response.status_code in _RETRY_STATUSES:
                    raise _RetryableStatusError(response.status_code)
                response.raise_for_status()
                return response
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= self._attempts or not self._retryable(exc):
                    raise
                await self._sleep(attempt)
        raise RuntimeError("HTTP request failed") from last_error

    async def _download(self, url: str, destination: Path) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, self._attempts + 1):
            destination.unlink(missing_ok=True)
            try:
                async with self._get_client().stream(
                    "GET", url, headers=self._headers
                ) as response:
                    if response.status_code in _RETRY_STATUSES:
                        raise _RetryableStatusError(response.status_code)
                    response.raise_for_status()
                    handle = await asyncio.to_thread(destination.open, "wb")
                    try:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            await asyncio.to_thread(handle.write, chunk)
                    finally:
                        await asyncio.to_thread(handle.close)
                return
            except asyncio.CancelledError:
                destination.unlink(missing_ok=True)
                raise
            except Exception as exc:
                last_error = exc
                destination.unlink(missing_ok=True)
                if attempt >= self._attempts or not self._retryable(exc):
                    raise
                await self._sleep(attempt)
        raise RuntimeError("download failed") from last_error

    async def _sleep(self, attempt: int) -> None:
        delay = self._backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _retryable(exc: BaseException) -> bool:
        if isinstance(exc, _RetryableStatusError):
            return True
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in _RETRY_STATUSES
        return isinstance(exc, OSError)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _is_self(self, url: str) -> bool:
        return urls_match(url, self.settings.self_replica_url)

    def _report(self, mode: Literal["registry", "peers"], peers: list[str]) -> SyncReport:
        now = datetime.now(UTC)
        return SyncReport(
            mode=mode,
            peers=peers,
            started_at=now,
            finished_at=now,
        )

    def _fail_all(
        self, report: SyncReport, selected: Sequence[str], message: str
    ) -> None:
        for store in selected:
            report.stores[store] = StoreSyncResult(
                store=store,
                status="failed",
                error=message,
            )
            report.errors[store] = message

    def _merge_archive_error(self, report: SyncReport, summary: ArchiveSyncSummary) -> None:
        if summary.failed <= 0:
            return
        detail = "; ".join(summary.errors) or f"{summary.failed} archive(s) failed"
        existing = report.errors.get("media")
        report.errors["media"] = f"{existing}; archives: {detail}" if existing else detail

    def _record(self, report: SyncReport) -> None:
        self._last_run_at = report.finished_at
        self._last_report = report
        if report.peers:
            self._last_source = ", ".join(report.peers)
        elif report.mode == "registry":
            self._last_source = "registry"
        else:
            self._last_source = None
        self._store_errors = {
            key: value for key, value in report.errors.items() if key in STORE_NAMES and value
        }
        all_errors = [f"{key}: {value}" for key, value in report.errors.items() if value]
        self._last_error = "; ".join(all_errors)[:2000] or None
        if self._last_error is None:
            self._last_success_at = report.finished_at
            logger.info(
                "replica sync ok source=%s stores=%s archives=%s",
                self._last_source,
                {name: item.status for name, item in report.stores.items()},
                report.archives.pulled if report.archives else 0,
            )
        else:
            logger.warning("replica sync had errors: %s", self._last_error)

    def _state(self) -> SyncStateOut:
        return SyncStateOut(
            last_run_at=self._last_run_at,
            last_success_at=self._last_success_at,
            last_source=self._last_source,
            last_error=self._last_error,
            store_errors=dict(self._store_errors),
            report=self._last_report,
        )


# Descriptive alias used by the API layer.
SyncManager = ReplicaSync


__all__ = [
    "ReplicaSync",
    "SyncManager",
    "resolve_stores",
]
