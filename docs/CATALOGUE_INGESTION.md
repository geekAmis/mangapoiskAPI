# Catalogue ingestion and metadata

This document is the operational contract for the resumable MangaPoisk /
MangaLib / Remanga catalogue crawler.  Code lives in:

- `services/parser/app/adapters/mangapoisk.py` — `catalogue()` / `catalog()`
- `services/parser/app/adapters/mangalib.py` — `catalogue()` / `catalog()`
- `services/parser/app/adapters/remanga.py` — `catalogue()`
- `services/catalog/app/{models,repository,service,api}.py`
- `services/scheduler/app/catalogue.py`

## Source pagination

| Source | Upstream call | Page size | Total exposed |
| --- | --- | --- | --- |
| MangaPoisk | `GET /manga?page=N&sortBy=…` (Inertia JSON) | 40 | `meta.total` / `meta.last_page` |
| MangaLib | `GET https://api.lib.social/api/manga?site_id[]=1&page=N&limit=60&sort_by=…` | 60 | no total; follow `meta.has_next_page` |
| Remanga | `GET https://api.remanga.org/api/v2/search/catalog/?page=N&count=30&ordering=…` | 30 | hard cap: page 999 is the last valid page (`page=1000` → HTTP 422) |

Supported adapter sort names: `popular`, `updated`, `new`, `rating`, `title`,
`chapters`.  MangaPoisk maps them to `sortBy` values; MangaLib maps them to
`sort_by` values (`views`, `last_chapter_at`, `created_at`, `rate_avg`, `name`,
`chap_count`).

## Crawl settings (`services/scheduler/app/main.py`)

| Setting | Default | Meaning |
| --- | --- | --- |
| `CATALOGUE_CRAWL_ENABLED` | `true` | Start the background crawler. |
| `CATALOGUE_SOURCES` | `mangapoisk,mangalib,remanga` | Sources to crawl. |
| `CATALOGUE_CRAWL_DELAY_SECONDS` | `1.75` | Extra delay between catalogue pages (1.5–2 s window). |
| `SCRAPER_REQUESTS_PER_MINUTE` | `36` | Per-source adapter limiter (1.67 s/request). |
| `CATALOGUE_INCREMENTAL_INTERVAL_SECONDS` | `900` | Refresh first pages every 15 min. |
| `CATALOGUE_INCREMENTAL_PAGES` | `2` | Pages refreshed for `updated` and `popular`. |
| `CATALOGUE_FULL_REFRESH_INTERVAL_SECONDS` | `604800` | Full catalogue pass weekly. |
| `CATALOGUE_FULL_RETRY_SECONDS` | `900` | Base retry delay after a failed page. |
| `CATALOGUE_PAGE_RETRIES` | `2` | Extra attempts for one catalogue page before it counts as a failure. |
| `CATALOGUE_FAILURE_THRESHOLD` | `3` | Consecutive failures before the per-source circuit is `blocked`. |
| `CATALOGUE_CIRCUIT_BASE_SECONDS` | `900` | First circuit backoff. |
| `CATALOGUE_CIRCUIT_MAX_SECONDS` | `86400` | Maximum circuit backoff (24 h). |
| `CATALOGUE_ENRICHMENT_CONCURRENCY` | `3` | Detail fetches per source (bounded by the 36/min limiter). |
| `CATALOGUE_ENRICHMENT_BATCH_SIZE` | `100` | Pending titles fetched per poll. |
| `CATALOGUE_ENRICHMENT_FAILURE_THRESHOLD` | `5` | Source failures before enrichment circuit opens. |
| `CATALOGUE_METADATA_REFRESH_BATCH` | `100` | Bounded metadata rotation per incremental cycle. |
| `CATALOGUE_METADATA_REFRESH_MAX_BACKLOG` | `5000` | Rotation is paused while this many details are pending. |

A full pass is resumable through the `crawl_state` table.  It never resets the
whole source: new titles are queued by `last_synced_at IS NULL`, and existing
titles are refreshed by a bounded rotation (100 per incremental cycle) once the
backlog is below the configured threshold.

### End states, retries, circuit breaker

- A documented catalogue end is a successful response with no items and
  `has_next=false` (MangaLib page 698 in the current API; MangaPoisk's last
  page).  That is recorded as `completed`.
- Remanga publishes a hard API cap.  Page 999 is valid and still advertises a
  `next` link to page 1000, but requesting page 1000 returns HTTP 422
  (`detail.loc=["page"]`, `type="less_than"`).  The adapter declares
  `max_catalogue_pages = 999` and reports `has_next=false` when `next` would be
  1000 or later.  A cursor already persisted at page 1000 is answered with an
  empty final page without an upstream request; in addition, exactly the
  page-limit 422 is converted into end-of-catalogue.  The crawl therefore
  completes on the next run without a manual page/status reset.  Other 422
  responses (bad `ordering`, `count`, page 1, …) still fail normally and never
  mark the crawl complete.
  Because the scheduler sees a normal successful page, it records
  `status=completed`, clears `last_error`, resets `health` to `ok` and does not
  open the circuit.
- A `404`/`403`/timeout/5xx on one page is retried up to
  `CATALOGUE_PAGE_RETRIES` times with jittered backoff.  It is **not** treated
  as end-of-catalogue: during the reliability audit MangaLib pages 200/201/202
  returned normal payloads and the real end was an empty page 698.
- Persistent failures open a per-source circuit stored in `crawl_state` mode
  `health`/`enrichment`: `status=blocked`, `failure_count`, `failure_kind`,
  `last_success_at`, `next_run_at`.  The scheduler sleeps until `next_run_at`
  instead of retrying every 15 minutes.  A success resets the circuit to `ok`.
- Enrichment failures are persisted per title in `manga.enrichment_retry_at`
  with exponential backoff, so a block of failing titles is skipped instead of
  starving the queue.

## Storage

`manga` / `chapters` keep metadata and chapter rows.  Added tables:

- `manga_covers`: one row per `(manga_id, source)` with `source_id`, `url`,
  `rating`, `quality`, `chapters_count`, `updated_at`/`source_updated_at` and
  `is_primary`.  Primary = highest rating, then quality, chapter count,
  freshness.  All group covers are returned in manga detail.
- `crawl_state`: `source`, `mode` (`full`/`incremental`/`health`/`enrichment`),
  `page`, `status`, `last_error`, `next_run_at`, `total_pages`, `items_seen`,
  `items_imported`, `last_success_at`, `failure_count`, `failure_kind`.
- `manga` enrichment columns: `enrichment_attempts`, `enrichment_retry_at`,
  `enrichment_last_attempt_at`, `enrichment_last_error`.

Migrations are additive and run in `ensure_runtime_schema()` for SQLite and
PostgreSQL.  New tables are also created by `create_all`.

## Internal API contract

- `GET /internal/manga?genres=horror+fantasy&include_empty=false` — AND genre
  filter using canonical English slugs; default excludes titles with no
  chapter rows.  `include_empty=true` is for admin/debug.
- `GET /internal/manga/search?q=…&include_empty=false` — same filter.
- `GET /internal/manga/{id}` — direct detail still works for a stub and returns
  `description_missing` + `description_fallback`.
- `GET /internal/genres` — `{items:[{slug,label,count}], total}`.
- `GET /internal/home/updates?limit=25` — latest chapters across titles with
  `manga_id`, `manga_title`, `poster_url`, `source`, chapter id/number/title,
  `published_at`, `added_at`.
- `GET|PUT /internal/crawl-state/{source}?mode=full|incremental|health|enrichment`
  — persistent cursor and circuit state.
- `GET /internal/manga/pending?source=…&limit=…` — enrichment queue
  (popularity-first, future retry titles skipped).
- `GET /internal/enrichment/stats` — backlog, retry/failed counters, per-source
  last success and ETA.
- `POST /internal/manga/{id}/enrichment-failure` — persist retry backoff.
- `POST /internal/maintenance/rotate-enrichment?source=…&limit=100` — bounded
  metadata refresh; `reset-enrichment` is a bounded alias.

`MangaOut` now includes `description_missing`, `description_fallback`,
`genre_slugs`, `genre_details` and `covers`.  `genres` stays a human-readable
list; filtering uses canonical slugs.

## Retention plan

Metadata and cover rows are retained indefinitely.  Chapter image archives are
owned by the media service and are LRU-evicted between
`CHAPTER_ARCHIVE_MIN_GB=20` and `CHAPTER_ARCHIVE_MAX_GB=25` by default
(`CHAPTER_ARCHIVE_POLICY=lru`).  Catalogue rows and chapter metadata are never
evicted by this policy.

## Expected first pass

MangaPoisk exposes 6,484 titles (163 pages × 40).  MangaLib does not publish a
total; its catalogue currently ends around page 697 at 60/page (~41.8k source
variants).  At 36 requests/minute per source, detail + chapter-list calls
dominate (roughly two HTTP requests per title):

- MangaPoisk: ~6.5k titles ≈ 13k requests ≈ 6 h.
- MangaLib: ~42k titles ≈ 84k requests ≈ 39 h.
- They run concurrently; expect roughly 36–45 h wall-clock for a full first
  pass including chapter lists, with usable titles appearing progressively as
  enrichment completes.  A description-only pass would be about half that.
  Incremental refreshes and weekly full passes are much cheaper after that.

## Enrichment backlog

The queue is drained at the source limiter rate (36 requests/min per source,
≈2 requests per title).  Sources run in parallel, so the 27.6k historical
backlog splits roughly as:

- MangaLib 11.5k → ≈ 10.7 h
- Remanga 9.9k → ≈ 9.2 h
- MangaPoisk 6.1k → ≈ 5.7 h

Overall ≈ **11 h** if all sources are healthy; the serial-equivalent total is
`27,600 × 2 / 36 ≈ 1,533 minutes ≈ 26 h`.  A circuit-blocked source does not
stop the other queues.

Titles are ordered by popularity (`rating_count`, then `rating`) and failures
receive persistent exponential retry delays (5 min → 10 min → … → 6 h), so the
queue keeps moving through healthy titles.  `/internal/enrichment/stats` and
the admin «Каталог и обогащение» panel show the live backlog and ETA.
