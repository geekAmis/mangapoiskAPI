"""Shared adapter infrastructure.

Every adapter gets:

* one shared ``httpx.AsyncClient`` (connection pooling),
* one token bucket so a single upstream never receives a burst,
* a small concurrency ceiling for hosts behind anti-bot protection,
* typed cache helpers that include the source and normalised parameters,
* robots.txt policy handling that fails open *only* for network errors.

No adapter is allowed to bypass logins, paywalls, CAPTCHA or DRM.  The helpers
in this module deliberately provide no such capability.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, FeatureNotFound
from manga_common.cache import Cache, cache_key
from manga_common.config import Settings
from manga_common.errors import (
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
)
from manga_common.errors import (
    TimeoutError as UpstreamTimeoutError,
)
from manga_common.errors import (
    ValidationError as InputValidationError,
)
from manga_common.http import AsyncRateLimiter, request_with_retry
from manga_common.logging import log_event
from manga_common.source_models import SourceInfo
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_OUR_AGENT_TOKEN = "mangapoiskreborn"


class RobotsRule:
    """A single ``Allow``/``Disallow`` rule with a compiled matcher."""

    __slots__ = ("allow", "pattern", "regex")

    def __init__(self, pattern: str, allow: bool) -> None:
        self.pattern = pattern
        self.allow = allow
        self.regex = self._compile(pattern)

    @staticmethod
    def _compile(pattern: str) -> re.Pattern[str]:
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        expression = re.escape(body).replace(r"\*", ".*")
        return re.compile("^" + expression + ("$" if anchored else ""))

    def matches(self, path: str) -> bool:
        return bool(self.regex.match(path))

    def to_dict(self) -> dict[str, Any]:
        return {"pattern": self.pattern, "allow": self.allow}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RobotsRule:
        return cls(pattern=str(value.get("pattern", "")), allow=bool(value.get("allow")))


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    """Parsed robots.txt policy for one host."""

    rules: tuple[RobotsRule, ...] = ()
    allow_all: bool = False
    disallow_all: bool = False
    crawl_delay: float | None = None

    def allows(self, path: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        matches = [rule for rule in self.rules if rule.matches(path)]
        if not matches:
            return True
        # The most specific rule wins; Allow wins an equal-length tie.
        winner = max(matches, key=lambda rule: (len(rule.pattern), rule.allow))
        return winner.allow

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "allow_all": self.allow_all,
            "disallow_all": self.disallow_all,
            "crawl_delay": self.crawl_delay,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RobotsPolicy:
        raw_rules = value.get("rules")
        rules = tuple(
            RobotsRule.from_dict(item)
            for item in (raw_rules if isinstance(raw_rules, list) else [])
            if isinstance(item, dict)
        )
        return cls(
            rules=rules,
            allow_all=bool(value.get("allow_all")),
            disallow_all=bool(value.get("disallow_all")),
            crawl_delay=value.get("crawl_delay"),
        )

    @classmethod
    def allow_everything(cls) -> RobotsPolicy:
        return cls(allow_all=True)

    @classmethod
    def deny_everything(cls) -> RobotsPolicy:
        return cls(disallow_all=True)

    @classmethod
    def parse(cls, text: str) -> RobotsPolicy:
        """Parse the subset of robots.txt that matters for politeness.

        Groups are selected by a user-agent token contained in our product
        name, falling back to ``*``.  ``Crawl-delay`` is preserved for
        diagnostics but the token bucket remains the effective limiter.
        """

        groups: list[tuple[set[str], list[tuple[bool, str]], float | None]] = []
        agents: set[str] = set()
        rules: list[tuple[bool, str]] = []
        crawl_delay: float | None = None
        last_line_was_agent = False

        def finish_group() -> None:
            nonlocal agents, rules, crawl_delay
            if agents:
                groups.append((set(agents), list(rules), crawl_delay))
            agents = set()
            rules = []
            crawl_delay = None

        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if not last_line_was_agent and agents:
                    finish_group()
                if value:
                    agents.add(value.lower())
                last_line_was_agent = True
            elif key in {"allow", "disallow"}:
                if agents and value:
                    rules.append((key == "allow", value))
                last_line_was_agent = False
            elif key == "crawl-delay":
                if agents and value:
                    try:
                        crawl_delay = max(crawl_delay or 0.0, float(value))
                    except ValueError:
                        crawl_delay = crawl_delay
                last_line_was_agent = False
        finish_group()

        selected: tuple[set[str], list[tuple[bool, str]], float | None] | None = None
        best_agent_length = -1
        wildcard: tuple[set[str], list[tuple[bool, str]], float | None] | None = None
        for group in groups:
            agent_names, _, _ = group
            if "*" in agent_names:
                wildcard = group
            for agent in agent_names:
                if agent != "*" and agent in _OUR_AGENT_TOKEN and len(agent) > best_agent_length:
                    selected = group
                    best_agent_length = len(agent)
        chosen = selected or wildcard
        if chosen is None:
            return cls.allow_everything()
        _, chosen_rules, chosen_delay = chosen
        parsed_rules = tuple(RobotsRule(pattern, allow) for allow, pattern in chosen_rules)
        if not parsed_rules:
            return cls(crawl_delay=chosen_delay)
        return cls(rules=parsed_rules, crawl_delay=chosen_delay)


class BaseAdapter:
    """Common plumbing for all source adapters."""

    info: SourceInfo
    allowed_hosts: frozenset[str] = frozenset()
    max_concurrency: int = 2
    # Last page accepted by the upstream catalogue, when the source publishes a
    # hard cap.  ``None`` means the adapter follows ``has_next`` unmodified.
    max_catalogue_pages: int | None = None
    default_headers: ClassVar[dict[str, str]] = {}

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        cache: Cache,
    ) -> None:
        self.client = client
        self.settings = settings
        self.cache = cache
        self.info = self.info.model_copy(deep=True)  # type: ignore[has-type]
        if not self.allowed_hosts:
            self.allowed_hosts = frozenset({urlparse(self.info.base_url).netloc.lower()})
        else:
            hosts = {host.lower() for host in self.allowed_hosts}
            hosts.add(urlparse(self.info.base_url).netloc.lower())
            self.allowed_hosts = frozenset(hosts)
        self.limiter = AsyncRateLimiter(settings.scraper_requests_per_minute)
        self._semaphore = asyncio.Semaphore(max(1, self.max_concurrency))
        self._cache_ttl = max(1, int(settings.scraper_cache_ttl_seconds or settings.cache_ttl_seconds))
        self._logger = logging.getLogger(f"parser.adapters.{self.info.code}")
        self._cookie = self._configured_cookie(settings)

    # ------------------------------------------------------------------
    # Configuration hooks
    # ------------------------------------------------------------------

    def _configured_cookie(self, settings: Settings) -> str | None:
        """Return an optional operator-provided cookie header, if allowed."""

        return None

    @property
    def cache_ttl(self) -> int:
        return self._cache_ttl

    # ------------------------------------------------------------------
    # URL and request helpers
    # ------------------------------------------------------------------

    def absolute(self, path: str) -> str:
        """Resolve a path against the adapter's base URL."""

        if path.startswith(("http://", "https://")):
            return path
        return urljoin(self.info.base_url.rstrip("/") + "/", path.lstrip("/"))

    def assert_allowed_url(self, url: str) -> None:
        """Reject URLs outside the adapter's upstream host allow-list.

        This protects internal endpoints that accept a user-supplied ``url``
        from being turned into an SSRF primitive.
        """

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InputValidationError(
                "URL must be an absolute HTTP(S) URL",
                code="invalid_url",
            )
        if parsed.netloc.lower() not in self.allowed_hosts:
            raise InputValidationError(
                f"URL host is not allowed for source '{self.info.code}'",
                code="url_host_not_allowed",
                details={"allowed_hosts": sorted(self.allowed_hosts)},
            )

    def _request_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            **self.default_headers,
            **(extra or {}),
        }
        if self._cookie:
            # Never log this header; it is an optional operator session.
            headers["Cookie"] = self._cookie
        return headers

    @staticmethod
    def _redact_url(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(query="", fragment="").geturl()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
        follow_redirects: bool = True,
    ) -> httpx.Response:
        """Perform a rate-limited request with shared retry/backoff logic."""

        resolved = self.absolute(url) if url.startswith("/") else url
        self.assert_allowed_url(resolved)
        async with self._semaphore:
            try:
                return await request_with_retry(
                    self.client,
                    method,
                    resolved,
                    settings=self.settings,
                    limiter=self.limiter,
                    retries=retries,
                    headers=self._request_headers(headers),
                    params=params,
                    follow_redirects=follow_redirects,
                )
            except UpstreamError as exc:
                status_code = None
                if isinstance(exc.details, dict):
                    status_code = exc.details.get("status_code")
                if status_code == 404:
                    raise NotFoundError(
                        f"{self.info.name}: resource not found",
                        code="not_found",
                        details={
                            "source": self.info.code,
                            "url": self._redact_url(resolved),
                        },
                    ) from exc
                raise

    async def request_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        response = await self.request("GET", url, params=params, headers=headers)
        return response.text

    async def request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.request("GET", url, params=params, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(
                f"{self.info.name}: upstream returned invalid JSON",
                code="invalid_upstream_json",
                details={"source": self.info.code, "url": self._redact_url(url)},
            ) from exc

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def cache_id(self, namespace: str, *parts: object) -> str:
        """Build a deterministic key with source + normalised parameters."""

        normalised = "|".join(
            re.sub(r"\s+", " ", str(part)).strip().casefold() for part in parts if part is not None
        )
        digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:20]
        readable = re.sub(r"[^a-z0-9_.-]+", "_", normalised).strip("_")[:60] or "all"
        return cache_key("parser", self.info.code, namespace, readable, digest)

    async def cache_read_model(
        self,
        namespace: str,
        parts: tuple[object, ...],
        model_type: type[ModelT],
    ) -> ModelT | None:
        raw = await self._cache_get(self.cache_id(namespace, *parts))
        if raw is None:
            return None
        try:
            return model_type.model_validate(raw)
        except PydanticValidationError:
            await self._cache_delete(self.cache_id(namespace, *parts))
            return None

    async def cache_write_model(
        self,
        namespace: str,
        parts: tuple[object, ...],
        value: BaseModel,
        *,
        ttl: int | None = None,
    ) -> None:
        await self._cache_set(
            self.cache_id(namespace, *parts),
            value.model_dump(mode="json"),
            ttl=ttl or self.cache_ttl,
        )

    async def cache_read_json(self, namespace: str, *parts: object) -> Any | None:
        return await self._cache_get(self.cache_id(namespace, *parts))

    async def cache_write_json(
        self,
        namespace: str,
        value: Any,
        *parts: object,
        ttl: int | None = None,
    ) -> None:
        await self._cache_set(
            self.cache_id(namespace, *parts),
            value,
            ttl=ttl or self.cache_ttl,
        )

    async def _cache_get(self, key: str) -> Any | None:
        try:
            return await self.cache.get_json(key)
        except Exception as exc:
            log_event(
                self._logger,
                "cache_read_failed",
                source=self.info.code,
                error=type(exc).__name__,
            )
            return None

    async def _cache_set(self, key: str, value: Any, *, ttl: int) -> None:
        try:
            await self.cache.set_json(key, value, ttl=ttl)
        except Exception as exc:
            log_event(
                self._logger,
                "cache_write_failed",
                source=self.info.code,
                error=type(exc).__name__,
            )

    async def _cache_delete(self, key: str) -> None:
        try:
            await self.cache.delete(key)
        except Exception as exc:
            log_event(
                self._logger,
                "cache_delete_failed",
                source=self.info.code,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------

    async def robots_policy(self, host: str) -> RobotsPolicy:
        """Return a cached robots.txt policy for ``host``."""

        key = self.cache_id("robots", host)
        raw = await self._cache_get(key)
        if isinstance(raw, dict):
            try:
                return RobotsPolicy.from_dict(raw)
            except (TypeError, ValueError):
                await self._cache_delete(key)

        robots_url = f"https://{host}/robots.txt"
        try:
            response = await self.request("GET", robots_url, retries=0)
        except NotFoundError:
            policy = RobotsPolicy.allow_everything()
        except UpstreamTimeoutError as exc:
            log_event(
                self._logger,
                "robots_fail_open",
                source=self.info.code,
                host=host,
                error=str(exc),
            )
            return RobotsPolicy.allow_everything()
        except RateLimitError as exc:
            log_event(
                self._logger,
                "robots_rate_limited",
                source=self.info.code,
                host=host,
                error=str(exc),
            )
            return RobotsPolicy.deny_everything()
        except UpstreamError as exc:
            status_code = exc.details.get("status_code") if isinstance(exc.details, dict) else None
            if status_code is None:
                # Network/DNS/TLS failure: fail open, but log loudly.
                log_event(
                    self._logger,
                    "robots_fail_open",
                    source=self.info.code,
                    host=host,
                    error=str(exc),
                )
                return RobotsPolicy.allow_everything()
            log_event(
                self._logger,
                "robots_fail_closed",
                source=self.info.code,
                host=host,
                status_code=status_code,
            )
            policy = RobotsPolicy.deny_everything()
        else:
            policy = RobotsPolicy.parse(response.text)

        await self._cache_set(key, policy.to_dict(), ttl=3600)
        return policy

    async def ensure_robots_allowed(self, url: str) -> None:
        """Raise a typed 403 when robots.txt disallows ``url``."""

        resolved = self.absolute(url) if url.startswith("/") else url
        parsed = urlparse(resolved)
        policy = await self.robots_policy(parsed.netloc.lower())
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        if not policy.allows(path):
            raise ForbiddenError(
                f"{self.info.name}: path is disallowed by robots.txt",
                code="robots_disallowed",
                details={"source": self.info.code, "path": path},
            )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_html(text: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(text, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(text, "html.parser")

    @staticmethod
    def clamp_chapters_limit(value: int, *, maximum: int = 1000) -> int:
        return max(0, min(int(value), maximum))

    @staticmethod
    def normalise_query(query: str) -> str:
        value = re.sub(r"\s+", " ", (query or "")).strip()
        if not value:
            raise InputValidationError("Search query must not be empty", code="empty_query")
        return value

    def log_debug(self, event: str, **fields: Any) -> None:
        self._logger.debug(event, extra={"event": event, **fields})
