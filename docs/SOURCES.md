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
- Chapter pages are embedded in `props.chapter.data.pages`; the adapter reads them
  directly from the Inertia payload, and no separate page XHR was observed in our
  live probes.
- Page images on `static2.mangapoisk.me` load with a normal browser
  `User-Agent`; `Referer` is optional in our probes. No signed URL/query token is
  required.
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

### MangaLib (`mangalib.me`, API `api.imglib.info` / `api.lib.social`) — search/catalogue/detail/chapters/pages

- `GET https://api.imglib.info/api/manga?q=<query>&site_id[]=1&page=1&limit=20`
  → `data[]` with `id, name, rus_name, eng_name, slug, slug_url, cover,
  ageRestriction, type, rating, status, releaseDateString`. `api.lib.social`
  accepts the same requests. HARs use `fields[]`/`site_id[0]` and `per_page=60`;
  the documented `limit` range is 10–60.
- An empty `q` returns the catalogue. `sort_by=last_chapter_at` gives the
  "latest updates" ordering used by `/internal/home`.
- `GET https://api.imglib.info/api/manga/{slug_url}` requires `Site-Id: 1`
  (without it the API returns 404). The public response includes `rus_name`,
  `eng_name`, `slug_url`, `cover`, `ageRestriction`, `type`, `status` and
  `releaseDateString`; the parser prefers `rus_name` as `title`. The HAR also
  shows authenticated fields such as `items_count`, `scanlateStatus` and
  `metadata`, which are optional.
- `GET https://api.imglib.info/api/manga/{slug}/chapters` returns the full
  chapter list in one response (249 chapters observed; no pagination envelope).
  `GET /api/manga/{slug_url}/chapters/players` exists but was empty in the HARs
  and is not needed for our contract.
- Reader pages: `GET https://api.imglib.info/api/manga/{slug_url}/chapter?volume={volume}&number={number}`
  → `data.pages[]` with `image, width, height, url`, all pages in one response.
  `url` is protocol-relative, e.g.
  `//manga/{slug}/chapters/{chapter_id}/{image}`. HAR image requests go to
  `https://img3.cdnlibs.org` (the `compress` server; no URL signature/query
  token). `/api/constants` lists `img2.imglib.info` as `main` and
  `img3.cdnlibs.org` as `compress`; `img2` returns 403 without
  `Referer: https://mangalib.me/`, while `img3` works. The parser emits
  `https://img3.cdnlibs.org/...` and `capabilities.pages=true`.
- API headers observed in the HARs: `Origin: https://mangalib.me`,
  `Referer: https://mangalib.me/`, `Site-Id: 1`, `Client-Time-Zone`, and an
  `Authorization` header. Public probes succeeded without `Authorization`; the
  detail endpoint specifically needs `Site-Id: 1`. API requests did not need
  cookies; image requests carried DDoS-Guard `__ddg*` cookies, which were not
  required for `img3` in our probes and must never be hardcoded.
- Chapter payloads do not expose previous/next links in the verified response,
  so `prev_url`/`next_url` are null unless a future response adds them. A numeric
  chapter id alone cannot be resolved to a reader URL: callers must pass the full
  chapter URL or a `<slug_url>/<volume>-<number>` source_id.
- The API advertises `x-ratelimit-limit: 100` in the HARs (no 403/429 observed).
  The adapter keeps the conservative 30 req/min default and concurrency at 1–2.

### Remanga (`remanga.org`, API `api.remanga.org`) — search/detail/chapters/pages (opt-in)

- Search: `GET https://api.remanga.org/api/v2/search/?query=<q>&page=<n>` →
  `{"meta": {"total_items", "total_pages", "page"}, "results": [...]}`. The API
  returns 20 results per page. Each result has `id, main_name, secondary_name,
  another_name, type, status, translate_status, issue_year, avg_rating,
  total_votes, count_chapters, cover{low,mid,high}, dir, is_erotic, is_yaoi,
  is_forbidden`. `dir` is the stable title identifier.
- Detail: `GET /api/v2/titles/{dir}/` requires the `dir` slug; a numeric title
  id returns 404 (verified), so the adapter rejects bare numeric title ids with
  a typed validation error. The response includes `main_name`, `secondary_name`,
  `another_name`, HTML `description`, `genres[]`, `categories[]`, `issue_year`,
  `status`, `translate_status`, `age_limit`, `avg_rating`, `total_votes`,
  `cover`, `count_chapters` and `branches[]`. The branch with the most
  `count_chapters` is used for the chapter list; `branches[].publishers[]`
  contains team/publisher metadata, which the normalised chapter contract does
  not expose separately.
- Chapters: `GET /api/v2/titles/chapters/?branch_id=<branch_id>&page=<n>&ordering=-index`
  → `{"next", "previous", "results": [...]}`. Chapters are newest first, 30 per
  page, and `next` is the next page number (integer) or null. A result provides
  `id, tome, chapter, name, upload_date, pub_date, is_paid, is_bought,
  publishers[]`. The list does not include page counts, so `page_count` is 0
  until the reader endpoint is opened.
- Reader: `GET /api/v2/titles/chapters/{chapter_id}/` works anonymously for free
  chapters and returns chapter metadata plus `pages` as nested arrays of
  `{id, link, width, height}`; the adapter flattens them in document order.
  `previous`/`next` objects contain the neighbouring chapter ids. The actual
  site reader URL is `https://remanga.org/manga/{dir}/{chapter_id}`; the legacy
  `/manga/{dir}/chapter/{id}` form is accepted only as an input alias.
  Free pages are public, so `capabilities.pages=true` and
  `requires_auth_for_pages=false`; no cookies are required.
- Paid/locked chapters: the API returns HTTP 200 with `is_paid: true`,
  `is_bought: false` and `pages: []`. The adapter raises a typed `UpstreamError`
  with code `chapter_paid` (including title id and price) instead of bypassing
  the paywall. A non-paid chapter with no pages raises `pages_unavailable`.
  `count_chapters` is read for branch selection; the parser contract has no
  standalone count field, and catalog derives `chapters_count` from the imported
  chapter list.
- Images: `pages[].link` is absolute. Verified hosts:
  `img3.reimg2.org` works with a normal browser/project `User-Agent` and needs
  no `Referer`; `img-reserve.reimg2.org` returns 403 unless
  `Referer: https://remanga.org/` is sent (UA alone is not enough).
  `img3.reimg.org` and `img.reimg.org` are the `server.link` primary hosts in
  the API payload but returned 403 from our network; page links already use the
  `.reimg2.org` mirrors. Covers use `remanga.org/media/...` and load with a
  normal UA. A media allowlist should include `remanga.org`,
  `img3.reimg2.org` and `img-reserve.reimg2.org` (optionally the primary
  `.reimg.org` hosts), and the media fetcher must be able to send
  `Referer: https://remanga.org/` for `img-reserve.reimg2.org`. No signed query
  token or cookie is required.
- Headers/rate: HAR API requests send `Origin: https://remanga.org`,
  `Referer: https://remanga.org/`, `Accept: */*` and (because the HAR was
  logged in) an `Authorization` header. Anonymous probes succeeded without
  `Authorization` or cookies; the adapter sends `Accept: application/json`.
  Responses are served behind `server: ddos-guard`; no `x-ratelimit-*` headers
  were observed. Keep the shared 30 req/min default and concurrency 1.
- Robots: `robots.txt` disallows `/api`, `/search`, `/manga?*` and `/manga/*?`.
  Treat Remanga as **opt-in per deployment**: the current `main` registers the
  adapter for the existing operator deployment, but a new host must make an
  explicit decision (`PARSER_ENABLED_SOURCES=remanga`) after permission from the
  site. Enabling it without permission would violate the robots policy.

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
