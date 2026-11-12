"""Parser-specific settings layered on the shared service settings."""

from __future__ import annotations

from manga_common.config import Settings
from pydantic import field_validator


class ParserSettings(Settings):
    """Shared settings plus parser-specific operator switches.

    Sources that are disabled for legal/robots reasons can only be enabled
    explicitly with ``PARSER_ENABLED_SOURCES`` (comma-separated codes).  This is
    intentionally awkward: no default deployment silently scrapes a site whose
    robots policy disallows it.
    """

    service_name: str = "parser"
    port: int = 8001
    parser_enabled_sources: str = ""
    # Admin-managed credentials live outside the repository; mount a writable
    # volume here in production.  The file is created lazily on first write.
    parser_cookie_store_path: str = "data/source-cookies.json"

    @field_validator("parser_enabled_sources")
    @classmethod
    def _normalise_sources(cls, value: str) -> str:
        return ",".join(part.strip().lower() for part in (value or "").split(",") if part.strip())

    @property
    def enabled_source_codes(self) -> set[str]:
        return {code for code in self.parser_enabled_sources.split(",") if code}
