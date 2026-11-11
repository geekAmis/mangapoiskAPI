"""Small, source-agnostic parsing helpers used by adapters."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from manga_common.text import strip_html

_WHITESPACE_RE = re.compile(r"\s+")
_RU_DATE_RE = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[а-яё]+)\s+(?P<year>\d{4})", re.IGNORECASE)

_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def normalize_whitespace(value: str | None) -> str:
    """Collapse all whitespace and trim the result."""

    return _WHITESPACE_RE.sub(" ", value or "").strip()


def first_text(*values: Any) -> str:
    """Return the first non-empty value as tag-free, entity-decoded text.

    Upstream labels sometimes contain HTML entities (``&mdash;``, ``&amp;``) or
    stray tags.  ``strip_html`` decodes entities with ``html.unescape`` and
    collapses whitespace, so titles are safe to store and render as plain text.
    """

    for value in values:
        if value is None:
            continue
        text = strip_html(str(value))
        if text:
            return text
    return ""


def normalize_number(value: Any) -> str:
    """Normalise an upstream chapter/volume number to a short string."""

    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize_whitespace(str(value))


def number_from_path_segment(segment: str) -> tuple[str | None, str]:
    """Split a ``volume-number`` path segment as used by MangaPoisk.

    The upstream chapter link ends with e.g. ``1-312`` or ``0-12.5``.  A
    missing volume is represented as ``None``; the chapter number is always
    returned (possibly empty when the segment is malformed).
    """

    cleaned = segment.strip("/")
    if "-" not in cleaned:
        return None, cleaned
    volume, number = cleaned.split("-", 1)
    return volume or None, number


def chapter_numbers_from_text(value: str) -> tuple[str | None, str | None]:
    """Extract volume and chapter numbers from Russian/English labels."""

    text = normalize_whitespace(value)
    volume_match = re.search(r"(?:том|volume|vol\.?)\s*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
    chapter_match = re.search(
        r"(?:глава|chapter|ch\.?)\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    volume = volume_match.group(1) if volume_match else None
    number = chapter_match.group(1) if chapter_match else None
    return volume, number


def parse_ru_date(value: str | None) -> datetime | None:
    """Parse dates like ``25 сентября 2026`` into an aware UTC datetime."""

    text = normalize_whitespace(value)
    if not text:
        return None
    match = _RU_DATE_RE.search(text)
    if not match:
        return None
    month = _RU_MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    try:
        return datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, accepting a trailing ``Z``."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def path_segments(url: str) -> list[str]:
    """Return non-empty decoded-ish path segments from an absolute/relative URL."""

    return [segment for segment in urlparse(url).path.split("/") if segment]


def absolute_url(base: str, value: str | None) -> str | None:
    """Join ``value`` with ``base`` and reject non-HTTP results."""

    from manga_common.text import absolute_url as shared_absolute_url

    resolved = shared_absolute_url(base, value)
    if not resolved:
        return None
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return resolved


def cover_url(base: str, value: str | None) -> str | None:
    """Normalise covers that upstream returns as a path or protocol-relative URL."""

    return absolute_url(base, value)
