"""Server-side prerender for crawlers and social link previews.

The site is a React SPA.  Humans must keep receiving the real ``index.html``
so hydration is unchanged; crawlers, messengers and search bots receive a
complete, JS-free HTML card with canonical/OG/Twitter metadata and JSON-LD.

This module is deliberately small and lives inside the gateway (no extra
service).  It never turns a catalogue outage into a 5xx: a bot gets a generic
200 shell with ``noindex`` and a link to the SPA, while humans always get the
SPA shell (proxied from nginx, or a minimal fallback).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
import uuid
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from manga_common.errors import NotFoundError
from manga_common.text import build_url_slug, strip_html

logger = logging.getLogger(__name__)

router = APIRouter()

# A UUID is the routing key; the slug after it is cosmetic.  The path
# converter is used instead of two routes because ``{manga_id}-{slug}`` would
# split the UUID at its first hyphen.
_MANGA_ROUTE_RE = re.compile(
    r"^(?P<manga_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:-(?P<slug>[^/]{0,255}))?/?$"
)

# Keep this list explicit: a generic ``bot`` substring would also match
# legitimate user agents and make debugging/preview behaviour unpredictable.
_BOT_RE = re.compile(
    r"("
    r"googlebot|google-inspectiontool|adsbot-google|mediapartners-google|"
    r"yandexbot|yandex\.com/bots|yandeximages|"
    r"bingbot|msnbot|slurp|duckduckbot|baiduspider|applebot|petalbot|"
    r"twitterbot|telegrambot|facebookexternalhit|facebot|linkedinbot|"
    r"discordbot|slackbot|whatsapp|vkbot|vkshare|okbot|pinterestbot|"
    r"embedly|quora link preview|outbrain|rogerbot|semrushbot|ahrefsbot|"
    r"mj12bot|seznambot|ia_archiver|archive\.org_bot"
    r")",
    re.IGNORECASE,
)

DEFAULT_CACHE_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_CACHE_ITEMS = 512
_CACHE: dict[str, tuple[float, str]] = {}
_SPA_CACHE: tuple[float, str] | None = None

_BOT_HTML_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"
_SPA_CACHE_CONTROL = "no-cache"
_FALLBACK_CACHE_CONTROL = "no-store"


def reset_prerender_cache() -> None:
    """Clear all in-process caches (tests and explicit operations)."""

    global _SPA_CACHE
    _CACHE.clear()
    _SPA_CACHE = None


def is_bot(user_agent: str | None) -> bool:
    return bool(user_agent and _BOT_RE.search(user_agent))


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _base(request: Request) -> str:
    return str(getattr(_settings(request), "public_web_url", "")).rstrip("/")


def _cache_seconds(request: Request) -> float:
    return float(getattr(_settings(request), "seo_prerender_cache_seconds", DEFAULT_CACHE_SECONDS))


def _timeout_seconds(request: Request) -> float:
    return float(getattr(_settings(request), "seo_prerender_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))


def _cache_items(request: Request) -> int:
    return int(getattr(_settings(request), "seo_prerender_cache_max_items", DEFAULT_CACHE_ITEMS))


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _truncate(value: Any, max_length: int = 160) -> str:
    text = strip_html("" if value is None else str(value))
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1]
    last_space = cut.rfind(" ")
    if last_space > max_length * 0.6:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def _absolute(value: Any, base: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("/"):
        return f"{base}{text}"
    return f"{base}/{text}"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None
    return None


def _json_ld(data: dict[str, Any]) -> str:
    # Escaping ``<`` prevents a title such as ``</script><script>...`` from
    # breaking out of the JSON-LD element.  ``&`` is escaped for HTML parsers
    # that treat the script body as raw text; JSON parsers see the original
    # characters after unescaping.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json" data-seo="json-ld">{payload}</script>'


def _verification_tags(settings: Any) -> str:
    tags: list[str] = []
    google = (getattr(settings, "google_site_verification", None) or "").strip()
    yandex = (getattr(settings, "yandex_verification", None) or "").strip()
    if google:
        tags.append(f'<meta name="google-site-verification" content="{_esc(google)}" />')
    if yandex:
        tags.append(f'<meta name="yandex-verification" content="{_esc(yandex)}" />')
    return "\n    ".join(tags)


def _head(
    *,
    title: str,
    description: str,
    canonical: str,
    robots: str,
    image: str | None,
    image_alt: str,
    og_type: str,
    json_ld: str | None,
    verification: str,
) -> str:
    image_tags = ""
    if image:
        image_tags = (
            f'\n    <meta property="og:image" content="{_esc(image)}" />'
            f'\n    <meta property="og:image:alt" content="{_esc(image_alt)}" />'
            f'\n    <meta name="twitter:image" content="{_esc(image)}" />'
            f'\n    <meta name="twitter:image:alt" content="{_esc(image_alt)}" />'
        )
    json_ld_tag = f"\n    {json_ld}" if json_ld else ""
    verification_tag = f"\n    {verification}" if verification else ""
    return (
        "<!doctype html>\n"
        '<html lang="ru">\n'
        "<head>\n"
        '    <meta charset="utf-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"    <title>{_esc(title)}</title>\n"
        f'    <meta name="description" content="{_esc(description)}" />\n'
        f'    <meta name="robots" content="{_esc(robots)}" />\n'
        f'    <link rel="canonical" href="{_esc(canonical)}" />\n'
        f'    <meta property="og:type" content="{_esc(og_type)}" />\n'
        '    <meta property="og:locale" content="ru_RU" />\n'
        '    <meta property="og:site_name" content="MangaPoisk Reborn" />\n'
        f'    <meta property="og:title" content="{_esc(title)}" />\n'
        f'    <meta property="og:description" content="{_esc(description)}" />\n'
        f'    <meta property="og:url" content="{_esc(canonical)}" />'
        f"{image_tags}\n"
        '    <meta name="twitter:card" content="summary_large_image" />\n'
        f'    <meta name="twitter:title" content="{_esc(title)}" />\n'
        f'    <meta name="twitter:description" content="{_esc(description)}" />'
        f"{verification_tag}"
        f"{json_ld_tag}\n"
        '    <meta name="theme-color" content="#060b12" />\n'
        "</head>\n"
    )


def _site_header() -> str:
    return (
        '<header style="padding:16px 20px;border-bottom:1px solid #24303d">'
        '<a href="/" style="color:#5ec8ff;text-decoration:none;font-weight:700">'
        "MangaPoisk Reborn</a></header>"
    )


def _chapter_label(chapter: Any) -> str:
    volume = getattr(chapter, "volume", None)
    number = getattr(chapter, "number", "") or ""
    title = (getattr(chapter, "title", "") or "").strip()
    parts: list[str] = []
    if volume:
        parts.append(f"Том {volume}")
    if number:
        parts.append(f"Глава {number}")
    label = " ".join(parts) or "Глава"
    if title and title.casefold() not in label.casefold():
        label = f"{label} — {title}"
    return label


def _chapter_list(chapters: list[Any], base: str) -> str:
    if not chapters:
        return '<p style="color:#9aa7b4">Главы ещё не импортированы.</p>'
    items: list[str] = []
    for chapter in chapters[:20]:
        chapter_id = getattr(chapter, "id", None)
        if not chapter_id:
            continue
        label = _chapter_label(chapter)
        published = _iso(getattr(chapter, "published_at", None))
        time_tag = (
            f' <time datetime="{_esc(published)}" style="color:#7f8c99">'
            f"{_esc(published[:10])}</time>"
            if published
            else ""
        )
        items.append(
            f'<li style="margin:6px 0"><a href="{_esc(base)}/reader/{_esc(chapter_id)}">'
            f"{_esc(label)}</a>{time_tag}</li>"
        )
    return '<ol style="padding-left:22px">' + "".join(items) + "</ol>"


def _cover_of(manga: Any) -> str | None:
    covers = getattr(manga, "covers", None) or []
    for cover in covers:
        if getattr(cover, "is_primary", False) and getattr(cover, "url", None):
            return str(cover.url)
    for cover in covers:
        if getattr(cover, "url", None):
            return str(cover.url)
    poster = getattr(manga, "poster_url", None)
    return str(poster) if poster else None


def _genres_of(manga: Any) -> list[str]:
    return [str(item) for item in (getattr(manga, "genres", None) or []) if str(item).strip()]


def _alternate_names(manga: Any) -> list[str]:
    primary = (getattr(manga, "title", None) or "").strip()
    seen: set[str] = {primary.casefold()} if primary else set()
    result: list[str] = []
    for value in (getattr(manga, "title_en", None), getattr(manga, "title_alt", None)):
        text = (value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def build_manga_json_ld(
    manga: Any,
    *,
    canonical: str,
    base: str,
    image: str | None,
    description: str,
) -> dict[str, Any]:
    title = (getattr(manga, "title", None) or "Тайтл").strip()
    genres = _genres_of(manga)
    adult = bool(getattr(manga, "adult", False))
    updated = _iso(getattr(manga, "updated_at", None)) or _iso(
        getattr(manga, "last_chapter_at", None)
    )
    story: dict[str, Any] = {
        "@type": ["ComicStory", "Book"],
        "@id": f"{canonical}#comic",
        "name": title,
        "url": canonical,
        "inLanguage": "ru",
        "isFamilyFriendly": not adult,
    }
    if description:
        story["description"] = description
    if image:
        story["image"] = image
    alternate = _alternate_names(manga)
    if alternate:
        story["alternateName"] = alternate
    if genres:
        story["genre"] = genres
    year = getattr(manga, "year", None)
    if isinstance(year, int) and year > 0:
        story["copyrightYear"] = year
    if updated:
        story["dateModified"] = updated
    same_as = _absolute(getattr(manga, "url", None), base)
    if same_as and same_as.startswith(("http://", "https://")):
        story["sameAs"] = same_as
    rating = getattr(manga, "rating", None)
    rating_count = getattr(manga, "rating_count", None)
    if isinstance(rating, (int, float)) and rating > 0 and isinstance(rating_count, int) and rating_count > 0:
        story["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": rating,
            "ratingCount": rating_count,
            "bestRating": 10,
            "worstRating": 1,
        }

    breadcrumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Главная", "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "Каталог", "item": f"{base}/catalogue"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }
    return {"@context": "https://schema.org", "@graph": [story, breadcrumbs]}


def render_manga_html(
    manga: Any,
    *,
    base: str,
    settings: Any,
) -> str:
    title = (getattr(manga, "title", None) or "Тайтл").strip()
    slug = getattr(manga, "url_slug", None) or build_url_slug(title)
    canonical = f"{base}/manga/{manga.id}-{slug}"
    raw_description = getattr(manga, "description", None) or getattr(
        manga, "description_fallback", None
    )
    description = _truncate(raw_description, 160) or _truncate(
        f"{title} — читать онлайн на русском. Описание, список глав и читалка MangaPoisk Reborn.",
        160,
    )
    cover = _absolute(_cover_of(manga), base) or f"{base}/icons/icon-512.png"
    genres = _genres_of(manga)
    chapters = list(getattr(manga, "chapters", None) or [])
    chapter_count = len(chapters) or int(getattr(manga, "chapters_count", 0) or 0)
    alt_titles = _alternate_names(manga)
    adult = bool(getattr(manga, "adult", False))
    year = getattr(manga, "year", None)
    json_ld = _json_ld(
        build_manga_json_ld(
            manga,
            canonical=canonical,
            base=base,
            image=cover,
            description=description,
        )
    )
    head = _head(
        title=f"{title} — читать онлайн на русском | MangaPoisk Reborn",
        description=description,
        canonical=canonical,
        robots="index,follow,max-image-preview:large",
        image=cover,
        image_alt=f"Обложка «{title}»",
        og_type="book",
        json_ld=json_ld,
        verification=_verification_tags(settings),
    )
    facts: list[str] = []
    if year:
        facts.append(str(year))
    if genres:
        facts.append(", ".join(genres[:4]))
    if chapter_count:
        facts.append(f"Глав: {chapter_count}")
    facts_html = (
        '<p style="color:#9aa7b4">' + _esc(" · ".join(facts)) + "</p>" if facts else ""
    )
    alt_html = (
        '<p style="color:#7f8c99">' + _esc(" · ".join(alt_titles)) + "</p>"
        if alt_titles
        else ""
    )
    adult_html = '<p><span style="background:#7f1d1d;color:#fff;padding:2px 8px;border-radius:4px">18+</span></p>' if adult else ""
    body = (
        _site_header()
        + '<main style="max-width:900px;margin:0 auto;padding:24px 20px;font-family:system-ui,sans-serif;line-height:1.6">'
        + '<nav aria-label="Хлебные крошки" style="color:#9aa7b4;margin-bottom:18px">'
        + '<a href="/" style="color:#5ec8ff">Главная</a> / '
        + '<a href="/catalogue" style="color:#5ec8ff">Каталог</a> / '
        + f"<span>{_esc(title)}</span></nav>"
        + '<article style="display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start">'
        + f'<img src="{_esc(cover)}" alt="{_esc(f"Обложка «{title}»")}" width="220" style="width:100%;border-radius:12px" />'
        + "<div>"
        + f"<h1 style=\"margin:0 0 8px\">{_esc(title)}</h1>"
        + alt_html
        + facts_html
        + adult_html
        + f'<p>{_esc(description)}</p>'
        + (f'<p><strong>Жанры:</strong> {_esc(", ".join(genres))}</p>' if genres else "")
        + f'<p><a href="{_esc(canonical)}" style="color:#5ec8ff">Открыть тайтл в читалке MangaPoisk</a></p>'
        + "</div></article>"
        + '<section style="margin-top:28px"><h2>Последние главы</h2>'
        + _chapter_list(chapters, base)
        + "</section>"
        + '<p style="margin-top:28px;color:#7f8c99">'
        + f'<a href="{_esc(canonical)}" style="color:#5ec8ff">MangaPoisk Reborn</a> — '
        + "каталог манги и манхвы на русском.</p>"
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def render_reader_html(chapter: Any, manga: Any, *, base: str, settings: Any) -> str:
    manga_title = (getattr(manga, "title", None) or "Тайтл").strip()
    slug = getattr(manga, "url_slug", None) or build_url_slug(manga_title)
    manga_id = getattr(manga, "id", None) or getattr(chapter, "manga_id", None)
    canonical = f"{base}/manga/{manga_id}-{slug}"
    label = _chapter_label(chapter)
    description = _truncate(
        f"{manga_title}: {label} — читать онлайн на русском в MangaPoisk Reborn. "
        "Страница чтения закрыта от индексации, каноническая страница — тайтл.",
        160,
    )
    cover = _absolute(_cover_of(manga), base) or f"{base}/icons/icon-512.png"
    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Главная", "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "Каталог", "item": f"{base}/catalogue"},
            {"@type": "ListItem", "position": 3, "name": manga_title, "item": canonical},
        ],
    }
    head = _head(
        title=f"{label} — {manga_title} | MangaPoisk",
        description=description,
        canonical=canonical,
        robots="noindex,follow",
        image=cover,
        image_alt=f"Обложка «{manga_title}»",
        og_type="article",
        json_ld=_json_ld(breadcrumbs),
        verification=_verification_tags(settings),
    )
    body = (
        _site_header()
        + '<main style="max-width:760px;margin:0 auto;padding:24px 20px;font-family:system-ui,sans-serif;line-height:1.6">'
        + '<p style="color:#9aa7b4">Страница чтения не индексируется. '
        + f'<a href="{_esc(canonical)}" style="color:#5ec8ff">Открыть страницу тайтла</a>.</p>'
        + f"<h1>{_esc(label)}</h1>"
        + f"<p>{_esc(manga_title)}</p>"
        + f'<p><a href="{_esc(canonical)}" style="color:#5ec8ff">Все главы и описание тайтла</a></p>'
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def _catalogue_canonical(request: Request, base: str) -> str:
    allowed = ("q", "source", "genre", "genres", "year", "status", "page")
    pairs: list[tuple[str, str]] = []
    for key in allowed:
        for value in request.query_params.getlist(key):
            value = value.strip()
            if not value:
                continue
            if key == "page" and value == "1":
                continue
            pairs.append((key, value))
    query = urlencode(pairs, doseq=True)
    return f"{base}/catalogue" + (f"?{query}" if query else "")


def render_catalogue_html(
    *,
    request: Request,
    items: list[Any],
    total: int,
    robots: str,
    base: str,
    settings: Any,
    query: str,
) -> str:
    canonical = _catalogue_canonical(request, base)
    title = (
        f"«{query}» — поиск манги | MangaPoisk Reborn"
        if query
        else "Каталог манги и манхвы на русском | MangaPoisk Reborn"
    )
    description = (
        f"Поиск манги и манхвы по запросу «{query}» в каталоге MangaPoisk Reborn."
        if query
        else "Каталог манги и манхвы на русском: поиск, жанры, свежие главы и читалка с офлайн-режимом."
    )
    head = _head(
        title=title,
        description=_truncate(description, 160),
        canonical=canonical,
        robots=robots,
        image=f"{base}/icons/icon-512.png",
        image_alt="MangaPoisk Reborn",
        og_type="website",
        json_ld=None,
        verification=_verification_tags(settings),
    )
    cards: list[str] = []
    for item in items[:24]:
        item_title = (getattr(item, "title", None) or "Тайтл").strip()
        slug = getattr(item, "url_slug", None) or build_url_slug(item_title)
        item_url = f"{base}/manga/{item.id}-{slug}"
        cover = _absolute(getattr(item, "poster_url", None), base) or f"{base}/icons/icon-512.png"
        cards.append(
            '<li style="display:flex;gap:12px;margin:12px 0">'
            f'<img src="{_esc(cover)}" alt="" width="64" height="90" style="object-fit:cover;border-radius:6px" />'
            f'<div><a href="{_esc(item_url)}" style="color:#5ec8ff;font-weight:650">{_esc(item_title)}</a>'
            f'<div style="color:#9aa7b4;font-size:14px">{_esc(getattr(item, "year", None) or "")}'
            f' {_esc(", ".join(_genres_of(item)[:3]))}</div></div></li>'
        )
    if not cards:
        cards.append('<li style="color:#9aa7b4">Ничего не найдено. Попробуйте изменить запрос.</li>')
    body = (
        _site_header()
        + '<main style="max-width:900px;margin:0 auto;padding:24px 20px;font-family:system-ui,sans-serif;line-height:1.6">'
        + f"<h1>{_esc(title)}</h1>"
        + f'<p style="color:#9aa7b4">Найдено: {int(total)}</p>'
        + '<ul style="list-style:none;padding:0">' + "".join(cards) + "</ul>"
        + f'<p><a href="{_esc(base)}/catalogue" style="color:#5ec8ff">Открыть каталог в читалке</a></p>'
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def render_private_html(*, route: str, base: str, settings: Any) -> str:
    labels = {
        "/library": "Библиотека",
        "/profile": "Профиль",
        "/admin": "Админ-панель",
        "/login": "Вход",
        "/register": "Регистрация",
    }
    title = labels.get(route, "MangaPoisk Reborn")
    head = _head(
        title=f"{title} — MangaPoisk Reborn",
        description="Приватный раздел MangaPoisk Reborn закрыт от индексации.",
        canonical=f"{base}/",
        robots="noindex,nofollow",
        image=None,
        image_alt="",
        og_type="website",
        json_ld=None,
        verification=_verification_tags(settings),
    )
    body = (
        _site_header()
        + '<main style="max-width:640px;margin:60px auto;padding:0 20px;font-family:system-ui,sans-serif">'
        + f"<h1>{_esc(title)}</h1>"
        + '<p style="color:#9aa7b4">Этот раздел доступен после входа и не предназначен для поисковых систем.</p>'
        + f'<p><a href="{_esc(base)}/" style="color:#5ec8ff">На главную</a></p>'
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def render_fallback_html(*, canonical: str, base: str, settings: Any) -> str:
    head = _head(
        title="MangaPoisk Reborn — читалка манги и манхвы онлайн",
        description="Каталог манги и манхвы, удобная читалка и офлайн-экспорт глав.",
        canonical=canonical,
        robots="noindex,follow",
        image=f"{base}/icons/icon-512.png",
        image_alt="MangaPoisk Reborn",
        og_type="website",
        json_ld=None,
        verification=_verification_tags(settings),
    )
    body = (
        _site_header()
        + '<main style="max-width:640px;margin:60px auto;padding:0 20px;font-family:system-ui,sans-serif">'
        + "<h1>MangaPoisk Reborn</h1>"
        + '<p style="color:#9aa7b4">Каталог временно недоступен. Откройте страницу в браузере — '
        + "читалка загрузится автоматически.</p>"
        + f'<p><a href="{_esc(canonical)}" style="color:#5ec8ff">Открыть страницу</a></p>'
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def render_not_found_html(*, base: str, settings: Any) -> str:
    head = _head(
        title="Страница не найдена — MangaPoisk Reborn",
        description="Запрошенная страница не найдена.",
        canonical=f"{base}/404",
        robots="noindex,follow",
        image=None,
        image_alt="",
        og_type="website",
        json_ld=None,
        verification=_verification_tags(settings),
    )
    body = (
        _site_header()
        + '<main style="max-width:640px;margin:60px auto;padding:0 20px;font-family:system-ui,sans-serif">'
        + "<h1>404 — страница не найдена</h1>"
        + f'<p><a href="{_esc(base)}/catalogue" style="color:#5ec8ff">Перейти в каталог</a></p>'
        + "</main>"
    )
    return head + "<body>" + body + "</body></html>"


def _headers(kind: str, cache: str) -> dict[str, str]:
    return {
        "Cache-Control": cache,
        "Vary": "User-Agent",
        "X-Prerender": kind,
    }


async def _call(request: Request, method: str, *args: Any, **kwargs: Any) -> Any:
    catalog = request.app.state.catalog
    call = getattr(catalog, method)
    return await asyncio.wait_for(call(*args, **kwargs), timeout=_timeout_seconds(request))


async def _cached_html(request: Request, key: str, builder: Any) -> tuple[str, str]:
    """Return ``(html, cache_status)``; stale HTML is better than a 5xx."""

    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] < _cache_seconds(request):
        return cached[1], "hit"
    try:
        html_text = await builder()
    except Exception:
        if cached is not None:
            logger.warning("prerender refresh failed; serving stale HTML for %s", key, exc_info=True)
            return cached[1], "stale"
        raise
    _CACHE[key] = (time.monotonic(), html_text)
    limit = max(16, _cache_items(request))
    if len(_CACHE) > limit:
        oldest = min(_CACHE.items(), key=lambda item: item[1][0])[0]
        _CACHE.pop(oldest, None)
    return html_text, "miss"


async def _fetch_spa_html(request: Request) -> str | None:
    global _SPA_CACHE

    now = time.monotonic()
    if _SPA_CACHE is not None and now - _SPA_CACHE[0] < _cache_seconds(request):
        return _SPA_CACHE[1]

    settings = _settings(request)
    candidates: list[str] = []
    internal = (getattr(settings, "web_internal_url", None) or "").strip().rstrip("/")
    if internal:
        candidates.append(f"{internal}/index.html")
    public = (getattr(settings, "public_web_url", None) or "").strip().rstrip("/")
    if public:
        candidates.append(f"{public}/index.html")

    for url in candidates:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                response = await client.get(url)
            if response.status_code == 200 and "text/html" in response.headers.get(
                "content-type", ""
            ):
                _SPA_CACHE = (time.monotonic(), response.text)
                return response.text
            logger.warning("SPA index fetch returned %s for %s", response.status_code, url)
        except Exception as exc:
            logger.warning("SPA index fetch failed for %s: %s", url, exc)
    return None


def _minimal_spa_html(canonical: str) -> str:
    return (
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\" />"
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        '<meta name="robots" content="noindex,follow" />'
        f'<link rel="canonical" href="{_esc(canonical)}" />'
        "<title>MangaPoisk Reborn</title></head><body>"
        '<div id="root"></div>'
        f'<p style="font-family:sans-serif;padding:24px">Откройте <a href="{_esc(canonical)}">'
        "страницу тайтла</a> в браузере.</p></body></html>"
    )


async def _spa_response(request: Request, canonical: str) -> Response:
    html_text = await _fetch_spa_html(request)
    if html_text is None:
        html_text = _minimal_spa_html(canonical)
    return HTMLResponse(
        content=html_text,
        headers=_headers("spa", _SPA_CACHE_CONTROL),
    )


async def _manga_route(route: str, request: Request) -> Response:
    base = _base(request)
    match = _MANGA_ROUTE_RE.match(route)
    if not match:
        if is_bot(request.headers.get("user-agent")):
            return HTMLResponse(
                content=render_not_found_html(base=base, settings=_settings(request)),
                status_code=404,
                headers=_headers("not-found", _FALLBACK_CACHE_CONTROL),
            )
        return await _spa_response(request, f"{base}/manga/{route}")

    manga_id = match.group("manga_id")
    requested_slug = match.group("slug")
    try:
        uuid.UUID(manga_id)
        manga = await _call(request, "manga", manga_id)
    except NotFoundError:
        if is_bot(request.headers.get("user-agent")):
            return HTMLResponse(
                content=render_not_found_html(base=base, settings=_settings(request)),
                status_code=404,
                headers=_headers("not-found", _FALLBACK_CACHE_CONTROL),
            )
        return await _spa_response(request, f"{base}/manga/{route}")
    except Exception:
        logger.warning("catalog lookup failed for manga %s", manga_id, exc_info=True)
        if not is_bot(request.headers.get("user-agent")):
            return await _spa_response(request, f"{base}/manga/{route}")
        canonical = f"{base}/manga/{manga_id}" + (f"-{requested_slug}" if requested_slug else "")
        return HTMLResponse(
            content=render_fallback_html(
                canonical=canonical, base=base, settings=_settings(request)
            ),
            headers=_headers("fallback", _FALLBACK_CACHE_CONTROL),
        )

    canonical_slug = getattr(manga, "url_slug", None) or build_url_slug(
        getattr(manga, "title", None)
    )
    canonical = f"{base}/manga/{manga_id}-{canonical_slug}"
    if requested_slug != canonical_slug:
        target = canonical
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(target, status_code=301, headers={"Cache-Control": "public, max-age=3600"})

    if not is_bot(request.headers.get("user-agent")):
        return await _spa_response(request, canonical)

    async def build() -> str:
        return render_manga_html(manga, base=base, settings=_settings(request))

    html_text, cache_status = await _cached_html(
        request, f"manga:{manga_id}:{canonical_slug}", build
    )
    return HTMLResponse(
        content=html_text,
        headers=_headers(cache_status, _BOT_HTML_CACHE_CONTROL),
    )


@router.get("/manga/{route:path}", include_in_schema=False)
async def manga_route(route: str, request: Request) -> Response:
    return await _manga_route(route, request)


@router.get("/reader/{chapter_id}", include_in_schema=False)
@router.get("/read/{chapter_id}", include_in_schema=False)
async def reader_route(chapter_id: str, request: Request) -> Response:
    base = _base(request)
    try:
        uuid.UUID(chapter_id)
        chapter = await _call(request, "chapter_meta", chapter_id)
    except NotFoundError:
        if is_bot(request.headers.get("user-agent")):
            return HTMLResponse(
                content=render_not_found_html(base=base, settings=_settings(request)),
                status_code=404,
                headers=_headers("not-found", _FALLBACK_CACHE_CONTROL),
            )
        return await _spa_response(request, f"{base}/reader/{chapter_id}")
    except Exception:
        logger.warning("catalog lookup failed for chapter %s", chapter_id, exc_info=True)
        if not is_bot(request.headers.get("user-agent")):
            return await _spa_response(request, f"{base}/reader/{chapter_id}")
        return HTMLResponse(
            content=render_fallback_html(
                canonical=f"{base}/reader/{chapter_id}",
                base=base,
                settings=_settings(request),
            ),
            headers=_headers("fallback", _FALLBACK_CACHE_CONTROL),
        )

    manga = None
    try:
        manga = await _call(request, "manga", str(chapter.manga_id))
    except Exception:
        logger.warning("manga lookup failed for reader %s", chapter_id, exc_info=True)

    if not is_bot(request.headers.get("user-agent")):
        return await _spa_response(request, f"{base}/reader/{chapter_id}")

    if manga is None:
        # The chapter exists but its title could not be loaded.  Keep the
        # reader noindex and point at the API-independent title URL.
        return HTMLResponse(
            content=render_fallback_html(
                canonical=f"{base}/manga/{chapter.manga_id}",
                base=base,
                settings=_settings(request),
            ),
            headers=_headers("fallback", _FALLBACK_CACHE_CONTROL),
        )

    async def build() -> str:
        return render_reader_html(chapter, manga, base=base, settings=_settings(request))

    html_text, cache_status = await _cached_html(
        request, f"reader:{chapter_id}", build
    )
    return HTMLResponse(
        content=html_text,
        headers=_headers(cache_status, _BOT_HTML_CACHE_CONTROL)
        | {"X-Robots-Tag": "noindex, follow"},
    )


@router.get("/catalogue", include_in_schema=False)
@router.get("/catalog", include_in_schema=False)
@router.get("/catalog/genres", include_in_schema=False)
async def catalogue_route(request: Request) -> Response:
    base = _base(request)
    if not is_bot(request.headers.get("user-agent")):
        return await _spa_response(request, _catalogue_canonical(request, base))

    q_raw = request.query_params.get("q")
    has_q = "q" in request.query_params
    q = (q_raw or "").strip()
    params: dict[str, Any] = {"sort": "popular", "page": 1, "limit": 24}
    if q:
        params["query"] = q
    for key in ("source", "genre", "genres", "year", "status"):
        value = request.query_params.get(key)
        if value:
            params[key] = value
    try:
        response = await _call(request, "manga_list", params)
    except Exception:
        logger.warning("catalog list failed for catalogue prerender", exc_info=True)
        return HTMLResponse(
            content=render_fallback_html(
                canonical=_catalogue_canonical(request, base),
                base=base,
                settings=_settings(request),
            ),
            headers=_headers("fallback", _FALLBACK_CACHE_CONTROL),
        )

    items = list(getattr(response, "items", []) or [])
    total = int(getattr(response, "total", len(items)) or 0)
    empty_query = has_q and not q
    robots = (
        "index,follow,max-image-preview:large"
        if total > 0 and not empty_query
        else "noindex,follow"
    )

    async def build() -> str:
        return render_catalogue_html(
            request=request,
            items=items,
            total=total,
            robots=robots,
            base=base,
            settings=_settings(request),
            query=q,
        )

    key = f"catalogue:{request.url.query}:{robots}"
    html_text, cache_status = await _cached_html(request, key, build)
    headers = _headers(cache_status, _BOT_HTML_CACHE_CONTROL)
    if robots.startswith("noindex"):
        headers["X-Robots-Tag"] = "noindex, follow"
    return HTMLResponse(content=html_text, headers=headers)


@router.get("/library", include_in_schema=False)
@router.get("/profile", include_in_schema=False)
@router.get("/admin", include_in_schema=False)
@router.get("/login", include_in_schema=False)
@router.get("/register", include_in_schema=False)
async def private_route(request: Request) -> Response:
    base = _base(request)
    if not is_bot(request.headers.get("user-agent")):
        return await _spa_response(request, f"{base}{request.url.path}")
    return HTMLResponse(
        content=render_private_html(
            route=request.url.path, base=base, settings=_settings(request)
        ),
        headers=_headers("private", _FALLBACK_CACHE_CONTROL)
        | {"X-Robots-Tag": "noindex, nofollow"},
    )
