# Parser service

Internal FastAPI microservice that turns public manga catalogue pages into the
normalised contracts from `packages/manga_common/manga_common/source_models.py`.
It owns all HTML/JSON selectors; gateway, catalog and clients never see upstream
markup.

- Port: **8001**
- Auth: every `/internal/*` route requires `X-Internal-Token`
- Cache: Redis when `REDIS_URL` is set, otherwise an in-process LRU cache
- Politeness: one token bucket per adapter, concurrency ceiling, exponential
  backoff (shared `manga_common.http`), `Retry-After`, robots.txt checks for HTML
  adapters

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Process health |
| GET | `/ready` | Readiness; checks the cache |
| GET | `/internal/sources` | All sources, including disabled ones, with capabilities |
| GET | `/internal/search?source=&q=&page=` | Source search |
| GET | `/internal/manga?source=&source_id=&url=&chapters_limit=` | Manga detail + chapters |
| GET | `/internal/chapter?source=&source_id=&url=` | Chapter + page URLs |
| GET | `/internal/home?source=` | Popular/latest landing lists |

`source_id` and `url` are alternatives. `url` must point at the adapter's own
host; arbitrary URLs are rejected to avoid SSRF. `chapters_limit` defaults to
100 and is capped at 1000; `0` returns metadata without chapters.

Example:

```bash
curl -H "X-Internal-Token: $INTERNAL_TOKEN" \
  "http://localhost:8001/internal/search?source=mangapoisk&q=overgeared"
```

Errors use the shared shape:

```json
{"error": {"code": "source_disabled", "message": "Source 'remanga' is disabled", "details": {"...": "..."}}}
```

Disabled and unknown sources both return `404`; upstream failures return `502`,
timeouts `504`, and robots.txt denials `403`.

## Sources

| Code | Status | Search | Manga | Chapters | Pages | Notes |
|---|---|---|---|---|---|---|
| `mangapoisk` | enabled | yes | yes | yes | yes | Full Inertia.js support; some chapters legitimately have zero pages |
| `mangalib` | enabled | yes | yes | yes | yes | Detail via `/api/manga/{slug_url}` with `Site-Id: 1` (`rus_name` preferred); reader pages via `volume`/`number`; images from `img3.cdnlibs.org` |
| `remanga` | **disabled** | yes | yes | yes | yes | `robots.txt` disallows `/api`; enable only with permission |
| `readmanga` | **disabled** | yes | yes | yes | yes | HTML selectors fixture-tested only; network reset from the dev host |
| `mangadex` | **disabled** | yes | yes | yes | yes | Russian `translatedLanguage` filter; network blocked from the dev host |

`GET /internal/sources` is the authoritative capability list. A disabled source
is never used as a fallback.

To enable an opt-in adapter (only after checking the site's terms/robots):

```bash
PARSER_ENABLED_SOURCES=remanga  # comma-separated source codes
```

## Configuration

All shared `manga_common.config.Settings` variables are accepted. The ones that
matter most:

| Variable | Default | Meaning |
|---|---|---|
| `INTERNAL_TOKEN` | dev value | Required `X-Internal-Token` |
| `REDIS_URL` | empty | Redis URL; empty uses `MemoryCache` |
| `SCRAPER_REQUESTS_PER_MINUTE` | `30` | Token bucket per adapter |
| `SCRAPER_CACHE_TTL_SECONDS` | `600` | Search/manga/chapter cache TTL |
| `SCRAPER_MAX_RETRIES` | `3` | Retries for transient upstream errors |
| `SCRAPER_BACKOFF_SECONDS` | `1.5` | Base for exponential backoff |
| `HTTP_TIMEOUT_SECONDS` | `30` | Upstream request timeout |
| `HTTP_USER_AGENT` | project UA | Identify the crawler honestly |
| `MANGAPOISK_COOKIE` | empty | Optional operator cookie; never logged/cached |
| `MANGALIB_COOKIE` | empty | Optional operator cookie |
| `REMANGA_COOKIE` | empty | Optional operator cookie |
| `PARSER_ENABLED_SOURCES` | empty | Comma-separated opt-in for disabled adapters |

Never commit real cookies. Do not enable a source that requires bypassing login,
paywall, CAPTCHA or DRM.

## Local development

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX:   source .venv/bin/activate
pip install -e packages/manga_common
cd services/parser
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

`requirements.txt` intentionally contains only third-party runtime packages, so
it can be installed from any working directory. The shared package is always
installed explicitly (`pip install -e packages/manga_common` here;
`pip install /app/packages/manga_common` in the Docker image).

### Docker

From the repository root:

```bash
docker build -f services/parser/Dockerfile -t mangapoisk-parser .
docker run --rm -p 8001:8001 \
  -e INTERNAL_TOKEN=change-me \
  mangapoisk-parser
```

The image installs `packages/manga_common` explicitly, runs as a non-root user
and exposes `/health` as its healthcheck.

## Tests

```bash
python -m pytest tests/parser -q
```

The suite uses `respx` and saved fixtures; it is fast and offline. A live
MangaPoisk smoke test is opt-in:

```bash
RUN_NETWORK_TESTS=1 python -m pytest tests/parser/test_network_smoke.py -m network -q
```

## Cache keys

Keys are `parser:<source>:<namespace>:<normalised-params>:<digest>`. Search,
manga, chapter and home responses are cached for
`SCRAPER_CACHE_TTL_SECONDS`. The MangaPoisk Inertia version and robots policies
have their own keys. Cookies are never part of cache values.

## Adding a source

1. Create `app/adapters/<code>.py` subclassing `BaseAdapter`.
2. Set `info` with honest `SourceCapabilities`.
3. Implement `search`, `get_manga`, `get_chapter`, `latest`.
4. Use `self.request`, `self.request_json`/`request_text`, `self.cache_*` and
   `self.ensure_robots_allowed` instead of creating clients or sleeping.
5. Raise `NotFoundError` for a missing resource and `UpstreamError` for an
   unverified/broken upstream. Never return fabricated page URLs.
6. Add fixtures and tests in `tests/parser/fixtures` and `tests/parser`.
7. Register the adapter in `app/registry.py` and update `docs/SOURCES.md`.

## Image proxy notes

The parser returns page-image URLs; the media service performs the download.
Verified header requirements for the current CDNs:

- **MangaLib / `img3.cdnlibs.org`:** send a normal browser `User-Agent` and
  `Referer: https://mangalib.me/`. `Accept: image/*` is optional. The HAR also
  carries DDoS-Guard `__ddg*` cookies, but they were not required in our probes;
  never hardcode user cookies.
- **MangaLib / `img2.imglib.info`:** works only with
  `Referer: https://mangalib.me/`; without it the CDN returns 403 (the
  production symptom). Prefer the `img3.cdnlibs.org` URLs returned by the parser.
- **MangaPoisk / `static2.mangapoisk.me`:** normal browser `User-Agent` is
  sufficient in our probes; `Referer` is accepted but not required.

## Known limitations

- **MangaPoisk:** chapter pages can legitimately be empty for licensed or
  upcoming chapters; the adapter returns `pages: []` rather than an error.
  Previous-chapter links are not present in the payload, so `prev_url` is null.
- **MangaLib:** the manga detail endpoint is `/api/manga/{slug_url}` and requires
  `Site-Id: 1`; the adapter falls back to a search hit if it fails. The detail
  response provides `rus_name` (preferred title), `eng_name`, cover, status,
  type and year, but not rating/description. Reader pages come from
  `/api/manga/{slug_url}/chapter?volume=&number=`; numeric chapter ids alone
  cannot be resolved, so pass the full chapter URL (catalog does). Previous/next
  links are not in the verified response.
- **Remanga:** implemented and probe-verified, but disabled because robots.txt
  disallows `/api`. Paid chapters are rejected rather than bypassed.
- **ReadManga:** selectors are conservative and fixture-tested; the live site was
  unreachable from the development network. Disabled by default.
- **MangaDex:** standard public API, but blocked from the development network.
  Disabled until an operator verifies connectivity.
