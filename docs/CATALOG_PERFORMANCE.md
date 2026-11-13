# Catalogue list performance (#68)

**Status:** deployed in v1.3.0. Production deploy check after rollout: p95
~45 ms at the gateway / ~34 ms at catalog for the public list. The
2.9–8.2 s p50 numbers below are the **pre-optimization** baseline.

**Scope:** catalog service list/search visibility, SQLite planner statistics,
benchmark and rollout notes. Public API contract is unchanged.

## Problem

At 78,393 manga rows and 1.73M chapter rows the catalogue list did three
expensive things on every request:

1. a correlated `EXISTS(SELECT 1 FROM chapters ...)` for every candidate row;
2. `count(*) ... GROUP BY group_key` to count deduplicated cards;
3. a window function over all matching rows to choose a representative variant.

Production measured `GET /api/v1/manga?limit=20` at p50 2.9–8.2 s and the
internal list at up to 16 s under crawl load.  A manual `ANALYZE` took 21 s and
only helped until the next import.

## Design

### 1. `manga.has_chapters`

A new boolean column answers "does this variant have real chapter rows?" without
touching the chapter table:

* `upsert_manga_detail()` sets it from the actual chapter-row count after import;
  a source-reported `chapters_count` alone is **not** enough.
* `upsert_manga_summary()` never sets it: a summary row stays hidden until a
  detail import creates chapters.
* `ensure_runtime_schema()` repairs existing data with two targeted statements:
  * stale `true` flags with no chapter rows become `false`;
  * rows with chapter rows and a stale `false` flag become `true`.

The production 20 rows with `chapters_count > 0` but no chapter rows therefore
stay out of the catalogue.  `chapters_count` is still kept for popularity,
dedup representative selection and enrichment priority; it is no longer the
visibility gate.

Partial indexes:

```sql
CREATE INDEX ix_manga_visible_group
    ON manga (group_key) WHERE has_chapters = 1;
CREATE INDEX ix_manga_visible_chapters_group
    ON manga (chapters_count, group_key) WHERE has_chapters = 1;
```

`EXPLAIN QUERY PLAN` for a group representative uses
`SEARCH manga USING INDEX ix_manga_visible_group (group_key=?)`.

### 2. Materialised card tables

`catalog_groups` stores one row per visible canonical group:

* `group_key` (PK), representative `manga_id`, title, source, status/year,
  genres key, rating, rating count, chapters count, last chapter/created/updated;
* representative order is exactly the old one: most chapters, then best rating,
  then freshest row, then manga id as a deterministic tie-breaker;
* sort indexes mirror the five public sort modes; `manga_id` is indexed for the
  final join that loads the 20–100 full cards.

`catalog_source_groups` stores one representative per `(group_key, source)`.
This exists because a source filter is variant-specific: if a group contains
both MangaPoisk and MangaLib variants, `?source=mangalib` must still return the
best MangaLib variant, not another source's representative.  It has a
`(source, rating_count, rating, updated_at, group_key)` index for the popular
source listing.

`catalog_state` is a one-row marker (`cards_version`, `cards_count`,
`built_at`).  Startup rebuilds the tables only when the marker is missing,
the version changed, or the tables are empty while visible manga exist.  Normal
restarts skip the window/insert work.

`include_empty=true` remains a rare QA/admin path and still uses the live grouped
query, so historical empty-stub semantics are preserved.  Search and
suggestions keep their FTS/ranking path and now filter with `has_chapters`
instead of `EXISTS`.

### 3. Planner statistics

* SQLite connections run `PRAGMA analysis_limit=400; PRAGMA optimize` on close.
* The catalog lifespan runs the same bounded optimize every 15 minutes
  (`STATS_OPTIMIZE_INTERVAL_SECONDS`, default 900).
* `POST /internal/maintenance/optimize` performs one bounded refresh; it is
  suitable for a scheduler/operator after a full crawl.
* `rebuild_catalog_groups()` runs `ANALYZE catalog_groups` and
  `ANALYZE catalog_source_groups` only (two small tables), never a full
  `ANALYZE` over `manga`/`chapters`.

`analysis_limit=400` keeps the operation bounded: measured 0.79 s on the
100k-row / 1.76M-chapter fixture, below the 1 s acceptance budget.

### 4. Observability

* SQLAlchemy `before/after_cursor_execute` logs statements slower than
  `SLOW_QUERY_MS` (default 500 ms) as `catalog_slow_sql`.
* `CatalogService.list()` records a rolling latency window and logs
  `catalog_slow_list` with sort/filter flags above the same threshold.
* `/internal/stats` (and therefore `GET /api/v1/admin/catalogue`) includes
  `list_latency: {samples, p50_ms, p95_ms, max_ms}`.  This is catalog-specific
  and additive; #58 owns gateway-wide HTTP metrics.

## Migration and rollout

The migration is additive and idempotent:

1. `has_chapters` column + partial indexes;
2. `catalog_groups`, `catalog_source_groups`, `catalog_state` tables;
3. visibility repair;
4. first card-table build (skipped afterwards).

Recommended production rollout:

```powershell
# 1. Backup the SQLite file (VACUUM INTO is already used by ops).
# 2. Pre-build the additive schema/cards while the old version is still serving.
.venv/Scripts/python scripts/reindex_catalog.py --rebuild-catalog

# 3. Deploy the new catalog image; startup sees the current cards_version and
#    skips the rebuild.
```

The pre-build takes the SQLite write lock for the duration of the card insert
(measured 6.5–12.0 s for 100k rows / 1.76M chapters on a laptop; production has
fewer visible groups).  Readers in WAL mode continue to read during the insert;
run it outside peak crawl/backup windows.  A normal restart after the marker is
written measured ~0.2 s on the same fixture.

Verification:

```sql
SELECT count(*) FROM catalog_groups;                 -- ~visible groups
SELECT count(*) FROM catalog_source_groups;          -- groups × sources
SELECT count(*) FROM catalog_groups c
 WHERE NOT EXISTS (SELECT 1 FROM chapters ch WHERE ch.manga_id = c.manga_id);
-- must be 0
```

Rollback is non-destructive: old code ignores the new column/tables.  Dropping
them is optional and only needed to reclaim space.

## Benchmark

Fixture: temporary SQLite database, WAL + `synchronous=NORMAL`, **100,000 manga
rows**, **20,000 canonical groups**, **1,760,000 chapter rows**, 80,000 visible
variants and 20,000 summary-only variants.  Each endpoint was warmed up and then
measured 20 times.  The concurrent scenario runs a writer that updates random
manga and card rows every 20 ms while the same popular query is measured.

Command:

```powershell
.venv/Scripts/python scripts/benchmark_catalog.py \
  --titles 100000 --groups 20000 --chapters-per-title 22 --runs 20 \
  --json-out docs/benchmarks/catalog-list-100k.json
```

| Scenario | p50 | p95 |
|---|---:|---:|
| `GET /internal/manga?limit=20` popular | 7.4 ms | **7.7 ms** |
| `GET /api/v1/manga?limit=20` popular | 8.5 ms | **9.2 ms** |
| internal genre=fantasy | 13.0 ms | 14.8 ms |
| internal genres=fantasy+horror | 13.7 ms | 15.9 ms |
| internal source=mangapoisk | 13.0 ms | 18.5 ms |
| public source=mangapoisk | 12.9 ms | 14.6 ms |
| internal popular + concurrent writer | 9.5 ms | **13.5 ms** |
| public popular + concurrent writer | 13.1 ms | **17.7 ms** |
| first card-table build | — | 6.5–12.0 s one-time |
| normal restart after the marker | — | ~0.2 s |
| bounded planner optimize | — | 0.79 s |
| empty cards in `catalog_groups` | — | **0** |

Before/after on the same fixture (legacy SQL still includes the correlated
`EXISTS` and window/group-by shapes):

| Query | Before #68 | After |
|---|---:|---:|
| deduplicated count | 921 ms | <1 ms (`count(*)` on 20k cards) |
| representative list, limit 20 | 906 ms | 7–9 ms |

The 300 ms p95 target is met with a wide margin, including the concurrent-writer
scenario.  A separate worst-case run with 100,000 unique groups (100,000 cards)
measured p95 47 ms for the internal popular list.

## Tests

* `tests/catalog/test_catalog_list_performance.py`:
  * no cards without chapter rows, including source-reported counts;
  * group dedup and stable pagination with forced sort-key ties;
  * genre AND/status/title filters on the materialised table;
  * source filter still returns the requested source's variant;
  * runtime migration repairs stale visibility flags;
  * p50/p95 exposure and bounded planner optimize;
  * `EXPLAIN QUERY PLAN` uses the materialised indexes.
* Existing catalogue/search/filter/recommendation suites remain green.
* `ruff check services/catalog tests/catalog scripts`.

## Risks

* `catalog_groups` is a cache of `manga`; any write path that bypasses the
  catalog service (manual SQL, ad-hoc scripts) must run
  `scripts/reindex_catalog.py --rebuild-catalog` or bump
  `CATALOG_CARDS_VERSION`.  Service imports and the search backfill worker keep
  it current.
* `has_chapters` is maintained on the import path.  Direct chapter inserts must
  update the flag or run the runtime repair; the production service only creates
  chapters through `upsert_manga_detail`.
* The one-time first build takes the SQLite write lock.  Pre-build before deploy
  or run it outside peak traffic; normal restarts skip it.
* Every import refreshes one group's card rows (a few small writes).  The
  concurrent-read benchmark stays under 20 ms p95, but monitor crawler import
  throughput after rollout.
* `include_empty=true` listings still use the live grouped query.  They are
  internal/QA paths and are not part of the public catalogue p95 target.
* PostgreSQL uses autovacuum/autoanalyze; the explicit maintenance statement
  targets the small card tables only.
