from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
        "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def normalize_whitespace(value: str | None) -> str:
    return _WS_RE.sub(" ", (value or "")).strip()


def absolute_url(base: str, value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("//"):
        return f"https:{value}"
    return urljoin(base, value)


def parse_year(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    digits = re.sub(r"[^\d-]", "", str(value))
    try:
        return int(digits)
    except ValueError:
        return None


def slugify(value: str) -> str:
    transliterated = value.lower().translate(_TRANSLIT)
    return _SAFE_SLUG_RE.sub("-", transliterated).strip("-") or "manga"


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_absolute_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
