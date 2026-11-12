"""Persistent, per-source session credential store.

The parser only needs a small amount of operator-provided state: an optional
cookie/authorization header for sources that show more content to signed-in
users.  This module keeps that state in a JSON file so it survives restarts and
can be managed by the internal admin API.

Security notes:

* the file is written atomically with mode ``0600``;
* values are never logged and the status helper only exposes a boolean;
* an empty store is valid and means "use anonymous access".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("parser.cookie_store")

DEFAULT_COOKIE_STORE_PATH = "data/source-cookies.json"
MAX_COOKIE_LENGTH = 20_000
_STORE_VERSION = 1
_FILE_MODE = 0o600


@dataclass(frozen=True, slots=True, repr=False)
class CookieRecord:
    """One source credential plus its last update time (never logged)."""

    value: str
    updated_at: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SourceCookieStore:
    """A tiny JSON-backed credential store keyed by source code."""

    def __init__(self, path: str | Path = DEFAULT_COOKIE_STORE_PATH) -> None:
        self.path = Path(path)
        self._records: dict[str, CookieRecord] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    # ------------------------------------------------------------------
    # Reading and writing
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read the store from disk, tolerating a missing/corrupt file."""

        self._loaded = True
        if not self.path.exists():
            return
        # Repair permissions on an existing file created by an older version.
        self._chmod(self.path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("cookie_store_unreadable: %s", type(exc).__name__)
            return

        records: dict[str, CookieRecord] = {}
        raw_sources: Any = payload
        if isinstance(payload, dict):
            raw_sources = payload.get("sources", payload)
        if not isinstance(raw_sources, Mapping):
            logger.warning("cookie_store_invalid_shape")
            return

        for raw_code, raw_value in raw_sources.items():
            code = str(raw_code).strip().lower()
            if not code:
                continue
            value: str | None = None
            updated_at: datetime | None = None
            if isinstance(raw_value, str):
                value = raw_value
            elif isinstance(raw_value, Mapping):
                raw_cookie = raw_value.get("cookie")
                if isinstance(raw_cookie, str):
                    value = raw_cookie
                raw_updated = raw_value.get("updated_at")
                if isinstance(raw_updated, str):
                    try:
                        updated_at = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                    except ValueError:
                        updated_at = None
            if value is not None and value.strip():
                records[code] = CookieRecord(value=value.strip(), updated_at=updated_at)
        self._records = records

    def get(self, code: str) -> CookieRecord | None:
        self._ensure_loaded()
        return self._records.get((code or "").strip().lower())

    def is_configured(self, code: str) -> bool:
        return self.get(code) is not None

    def codes(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._records)

    def status(self, code: str) -> dict[str, Any]:
        record = self.get(code)
        return {
            "configured": record is not None,
            "updated_at": record.updated_at if record is not None else None,
        }

    async def set(self, code: str, value: str) -> CookieRecord | None:
        """Store a credential atomically, or clear it when it is empty."""

        normalised = (code or "").strip().lower()
        if not normalised:
            raise ValueError("source code must not be empty")
        clean_value = (value or "").strip()
        if len(clean_value) > MAX_COOKIE_LENGTH:
            raise ValueError("cookie value is too long")

        async with self._lock:
            self._ensure_loaded()
            if not clean_value:
                removed = self._records.pop(normalised, None)
                if removed is not None:
                    self._write_locked()
                return None
            record = CookieRecord(value=clean_value, updated_at=_utc_now())
            self._records[normalised] = record
            self._write_locked()
            return record

    async def clear(self, code: str) -> bool:
        normalised = (code or "").strip().lower()
        async with self._lock:
            self._ensure_loaded()
            if normalised not in self._records:
                return False
            del self._records[normalised]
            self._write_locked()
            return True

    def set_sync(self, code: str, value: str) -> CookieRecord | None:
        """Synchronous variant used only during application startup."""

        self._ensure_loaded()
        normalised = (code or "").strip().lower()
        if not normalised:
            raise ValueError("source code must not be empty")
        clean_value = (value or "").strip()
        if not clean_value:
            self._records.pop(normalised, None)
            return None
        record = CookieRecord(value=clean_value, updated_at=_utc_now())
        self._records[normalised] = record
        self._write_locked()
        return record

    def seed_from_environment(
        self,
        settings: object,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> list[str]:
        """Seed initial cookies from the environment when the store is empty.

        Only the Remanga credential has a documented env fallback.  The value is
        accepted from the typed setting (``REMANGA_COOKIE``) and from the
        historical spellings ``REMANGACOOKIE`` / ``REMAGA_COOKIE``.  Environment
        values never override an existing store entry.
        """

        self._ensure_loaded()
        if self.is_configured("remanga"):
            return []

        env = environ if environ is not None else os.environ
        candidates = [
            getattr(settings, "remanga_cookie", None),
            env.get("REMANGACOOKIE"),
            env.get("REMAGA_COOKIE"),
            env.get("REManga_COOKIE"),
            env.get("REMANGA_COOKIE"),
        ]
        value = next(
            (str(item).strip() for item in candidates if item and str(item).strip()),
            None,
        )
        if not value:
            return []
        try:
            self.set_sync("remanga", value)
        except OSError as exc:
            logger.warning("cookie_store_seed_unwritable: %s", type(exc).__name__)
            # Keep the credential available for this process even when the
            # configured path is read-only (for example a missing volume).
            self._records["remanga"] = CookieRecord(value=value, updated_at=_utc_now())
        logger.info("cookie_store_seeded: source=remanga origin=environment")
        return ["remanga"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _write_locked(self) -> None:
        payload = {
            "version": _STORE_VERSION,
            "sources": {
                code: {
                    "cookie": record.value,
                    "updated_at": (
                        record.updated_at.isoformat() if record.updated_at is not None else None
                    ),
                }
                for code, record in sorted(self._records.items())
            },
        }
        serialised = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialised)
                handle.flush()
                os.fsync(handle.fileno())
            self._chmod(temporary)
            os.replace(temporary, self.path)
            self._chmod(self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _chmod(path: Path) -> None:
        # Windows and some network filesystems do not support POSIX mode bits;
        # the atomic replace still protects the file contents.
        with contextlib.suppress(OSError):
            path.chmod(_FILE_MODE)


def apply_cookie(adapter: object, value: str | None) -> bool:
    """Apply a credential to a live adapter without recreating it.

    Adapters that understand their upstream authentication implement
    ``set_cookie``.  Other adapters still use the shared ``BaseAdapter``
    ``_cookie`` header, so all known sources can be managed by the same store.
    """

    setter = getattr(adapter, "set_cookie", None)
    if callable(setter):
        setter(value)
        return True
    if hasattr(adapter, "_cookie"):
        adapter._cookie = (value or "").strip() or None  # type: ignore[attr-defined]
        return True
    return False


def cookie_supported(adapter: object) -> bool:
    return callable(getattr(adapter, "set_cookie", None)) or hasattr(adapter, "_cookie")
