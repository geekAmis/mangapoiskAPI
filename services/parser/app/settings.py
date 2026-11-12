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
    # HentaiLib is reachable through several domains.  The first working host is
    # remembered for the process; the list is also a fallback order.
    hentailib_base_urls: str = "https://hentailib.me"
    hentailib_api_base_urls: str = "https://hapi.hentaicdn.org/api"

    @field_validator("parser_enabled_sources")
    @classmethod
    def _normalise_sources(cls, value: str) -> str:
        return ",".join(part.strip().lower() for part in (value or "").split(",") if part.strip())

    @field_validator("hentailib_base_urls", "hentailib_api_base_urls")
    @classmethod
    def _normalise_urls(cls, value: str) -> str:
        return ",".join(
            part.strip().rstrip("/") for part in (value or "").split(",") if part.strip()
        )

    @property
    def enabled_source_codes(self) -> set[str]:
        return {code for code in self.parser_enabled_sources.split(",") if code}

    @property
    def hentailib_base_url_list(self) -> list[str]:
        return [url for url in self.hentailib_base_urls.split(",") if url]

    @property
    def hentailib_api_base_url_list(self) -> list[str]:
        return [url for url in self.hentailib_api_base_urls.split(",") if url]
