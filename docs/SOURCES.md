# Sources

The parser service isolates every upstream behind an adapter.  This document
records what is verified from the development network (2026-11-11), what is
best-effort, and the rules every adapter must follow.

## Rules

- Public catalogue data only.  No login bypass, no CAPTCHA solving, no DRM or
  paywall circumvention.
- Respect `robots.txt` and each site's terms.  Do not crawl aggressively.
- Shared rate limiter (default 30 req/min/source), exponential backoff,
  `Retry-After`, conditional requests where possible.
- Cache aggressively. Metadata and chapter pages use `SCRAPER_CACHE_TTL_SECONDS`
  (10 min by default); images are cached on disk by `media`.
- Optional cookies are read from environment variables only.  Never log them,
  never commit them, never ship them to clients.
- If an upstream changes or blocks us, the adapter must return a typed
  `UpstreamError`, not crash the service.

## Verified

### MangaPoisk (`mangapoisk.me`) — full support

The site is Inertia.js + Svelte.  The server-rendered `data-page` attribute
contains JSON with `component`, `props`, `url`, `version`.

- `GET /` → parse `data-page` → `props.version` (Inertia version), popular,
  published, newlyAdded, updated, latestUpdated.
- `GET /manga/{slug}` returns `props.manga.data`, but `props.chapters` is empty.
  Request `GET /manga/{slug}?tab=chapters` with `X-Inertia: true` and
  `X-Inertia-Version: <version>` to receive `props.chapters.data` (50 per page)
  plus `props.chapters.meta.last_page`. The parser walks pages up to its
  `chapters_limit`.
- `GET /manga/{slug}/chapter/{volume}-{number}` → `props.chapter.data.pages`
  (array of `{id, link, width, height, number}`) and
  `props.chapter.data.nextChapter` when a next chapter exists. Guest access is
  enough for normal titles; some licensed/upcoming chapters legitimately have
  zero pages (verified: `overgeared-abs3nSd/chapter/1-312` has `pages: []`,
  while `1-300` has 20 pages). The parser returns an empty page list, not an
  exception.
- There is no `previousChapter` field in the chapter payload; `prev_url` stays
  null unless a future upstream adds it.
- `GET /search?q=<query>` → `{"message":"ok","results":[{link,label,value,year,updated,image}]}`
  (plain JSON). Content negotiation matters: send
  `Accept: application/json, text/plain, */*`; a browser-style HTML `Accept`
  header receives the HTML search page instead.
- Robots: `/legal`, `/copyright`, `/password`, comments and chapter-selector
  fragments disallowed; normal manga/chapter pages and `/search` are allowed.
  No sitemap scraping needed.

Mapping:

| Upstream | Normalised |
|---|---|
| `manga.data.id` / `slug` | `source_id` (prefer slug) / `slug` |
| `name` | `title` |
| `name_en`, `name_alt`, `name_jp` | `title_en`, `title_alt` |
| `description` | `description` |
| `year`, `rating`, `ratesCount` | `year`, `rating`, `rating_count` |
| `poster.link`, `link_mini` | `poster_url` |
| `genres[].title` | `genres` |
| `chapters_count` | `chapters_count` |
| `firstChapter` / `lastChapter` | first/last chapter summaries |
| chapter `link` final segment `vol-num` | `volume`, `number` |
| chapter `pages[].link/width/height` | `Page` |

### MangaLib (`mangalib.me`, API `api.lib.social`) — search/catalogue/chapters/pages

- `GET https://api.lib.social/api/manga?q=<query>&site_id[]=1&page=1&limit=20`
  → `data[]` with `id, name, rus_name, eng_name, slug, slug_url, cover,
  ageRestriction, type, rating, status, releaseDateString`. `limit` must be
  between 10 and 60.
- An empty `q` returns the catalogue. `sort_by=last_chapter_at` gives the
  "latest updates" ordering used by `/internal/home`.
- `GET https://api.lib.social/api/manga/{slug}/chapters` and the equivalent
  `/{slug_url}/chapters` → `data[]` with `id, volume, number, name, branches[]`
  (branch timestamps are the chapter publication dates).
- Reader pages: `GET https://api.lib.social/api/manga/{slug_url}/chapter?volume={volume}&number={number}`
  → `data.pages[]` with `image, width, height, url`. `url` is protocol-relative,
  e.g. `//manga/{slug}/chapters/{chapter_id}/{image}`. The parser normalises it
  to `https://img2.imglib.info/...` (`img3.imglib.info` returns 403). Bring
  `Origin: https://mangalib.me` and `Referer: https://mangalib.me/`.
  `capabilities.pages=true`.
- Chapter payloads do not expose previous/next links in the verified response,
  so `prev_url`/`next_url` are null unless a future response adds them. A numeric
  chapter id alone cannot be resolved to a reader URL: callers must pass the full
  chapter URL or a `<slug_url>/<volume>-<number>` source_id.
- The manga detail endpoint `/api/manga/{slug}` still returned 404 in all
  probes; summary is derived from search + chapter list.
- Requires `Origin: https://mangalib.me` and `Referer` headers.  Site is behind
  DDoS-Guard; keep concurrency at 1–2 and cache hard.

### Remanga (`remanga.org`, API `api.remanga.org`) — search/detail/chapters/pages (opt-in)

- `GET https://api.remanga.org/api/v2/search/?query=<q>` → `results[]` with
  `id, main_name, secondary_name, type, status, issue_year, avg_rating,
  total_votes, cover{low,mid,high}, dir, count_chapters`.
- `GET /api/v2/titles/?query=` also works but returns a different envelope.
- Implementation probes found the detail/chapter endpoints reachable after all:
  - `GET /api/v2/titles/{dir}/` → title detail, genres, branches, counts.
  - `GET /api/v2/titles/chapters/?branch_id={branches[0].id}&page=N` → newest
    chapters first, 30 per page, `next` for pagination.
  - `GET /api/v2/titles/chapters/{chapter_id}/` → chapter metadata plus `pages`
    as nested arrays of `{id, link, width, height}`; also `previous`/`next`.
  - Paid chapters (`is_paid: true`) must not be bypassed; the adapter returns a
    typed `chapter_paid` error when the chapter is not bought.
- Robots disallows `/api`; this adapter is therefore **disabled by default**
  and only enabled by an explicit operator flag (`PARSER_ENABLED_SOURCES`),
  with a warning in the UI/docs. Enabling it without permission would violate
  the site's robots policy.

## Best-effort / unverified in the dev network

### ReadManga (`readmanga.live`)

Connection reset from the development network (confirmed again during parser
implementation, `WinError 10054`).  Implemented a conservative HTML adapter
(`/search?q=`, manga page `.element`, chapter page `.page-image`) with
`enabled=false` by default and unit tests using saved fixtures.  Selectors are
deliberately narrow and do not attempt to evade anti-bot protection.

### MangaDex (`api.mangadex.org`)

Standard public API, connection reset here (confirmed again during parser
implementation).  Implemented:
- `GET /manga?title=&translatedLanguage[]=ru&limit=&offset=`
- `GET /manga/{id}/feed?translatedLanguage[]=ru&order[volume]=desc`
- `GET /at-home/server/{chapterId}` → `baseUrl`, `chapter.hash`, `data[]`
- images: `{baseUrl}/data/{hash}/{filename}` (falls back to `data-saver`)
Mark `enabled=false` until an operator confirms network access.  MangaDex is
not a Russian *site* but hosts Russian scanlation groups; metadata is usually
English/Japanese.

## Adding a source

1. Create `services/parser/app/adapters/<code>.py` subclassing `BaseAdapter`.
2. Set `info` with accurate `capabilities`.
3. Implement `search`, `get_manga`, `get_chapter`, `latest`.  Raise
   `UpstreamError`/`NotFoundError`; never return partial garbage silently.
4. Add fixtures + tests in `tests/parser/`.
5. Register it in `adapters/__init__.py` and document it here.
6. Never add a source that requires bypassing an access control.
