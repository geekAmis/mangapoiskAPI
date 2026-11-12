# Catalogue ingestion and metadata

This document is the operational contract for the resumable MangaPoisk /
MangaLib catalogue crawler.  Code lives in:

- `services/parser/app/adapters/mangapoisk.py` — `catalogue()` / `catalog()`
- `services/parser/app/adapters/mangalib.py` — `catalogue()` / `catalog()`
- `services/catalog/app/{models,repository,service,api}.py`
- `services/scheduler/app/catalogue.py`

## Source pagination

| Source | Upstream call | Page size | Total exposed |
| --- | --- | --- | --- |
| MangaPoisk | `GET /manga?page=N&sortBy=…` (Inertia JSON) | 40 | `meta.total` / `meta.last_page` |
| MangaLib | `GET https://api.lib.social/api/manga?site_id[]=1&page=N&limit=60&sort_by=…` | 60 | no total; follow `meta.has_next_page` |

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
| `CATALOGUE_FULL_REFRESH_INTERVAL_SECONDS` | `604800` | Full pass / metadata refresh weekly. |
| `CATALOGUE_FULL_RETRY_SECONDS` | `900` | Retry delay after a failed page. |
| `CATALOGUE_ENRICHMENT_CONCURRENCY` | `2` | Detail fetches per source. |
| `CATALOGUE_ENRICHMENT_BATCH_SIZE` | `50` | Pending titles fetched per poll. |

A full pass is resumable through the `crawl_state` table.  The weekly pass
marks every source title for metadata re-enrichment; enrichment runs alongside
the page crawl and is bounded by the adapter limiter.

## Storage

`manga` / `chapters` keep metadata and chapter rows.  Added tables:

- `manga_covers`: one row per `(manga_id, source)` with `source_id`, `url`,
  `rating`, `quality`, `chapters_count`, `updated_at`/`source_updated_at` and
  `is_primary`.  Primary = highest rating, then quality, chapter count,
  freshness.  All group covers are returned in manga detail.
- `crawl_state`: `source`, `mode` (`full`/`incremental`), `page`, `status`,
  `last_error`, `next_run_at`, `total_pages`, `items_seen`, `items_imported`.

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
- `GET|PUT /internal/crawl-state/{source}?mode=full` — persistent cursor.
- `GET /internal/manga/pending?source=…&limit=…` — enrichment queue.
- `POST /internal/maintenance/reset-enrichment?source=…` — weekly refresh.

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
