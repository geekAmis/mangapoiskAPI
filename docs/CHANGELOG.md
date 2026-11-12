# Changelog

All notable changes are documented here.  Format: Keep a Changelog; versioning:
SemVer.

## [Unreleased]

- Public reader profiles (#47): `/u/{username}`, XP/levels/ranks,
  achievements, activity feed, privacy controls and profile moderation.
- Catalogue list performance (#68): `has_chapters` visibility flag, materialised
  `catalog_groups`/`catalog_source_groups` card tables, bounded SQLite
  `PRAGMA optimize`, slow-query logging and p50/p95 list latency in admin stats.
  Measured p95 7.9 ms internal / 8.9 ms public at 100k manga rows and 1.76M
  chapters.
- Shared database or replication for multi-node catalogue/library failover.
- Alembic migrations for destructive schema changes.
- Redis-backed global rate limiting.
- S3-compatible media storage.
- More verified sources (MangaDex/ReadManga).

### Security

- Bumped `Pillow` to `>=13.0.0,<14` in the media service and `cryptography` to
  `>=50.0.2,<51` in the control and notifier services (#77). This resolves the
  40 Pillow 12.3.0 and 7 cryptography 47.0.0 advisories reported by
  `pip-audit`; the updated environment reports 0 known vulnerabilities.
- Added `docs/SECURITY.md` and `docs/DEPENDENCIES.md` with the reporting
  process, audit cadence, pinning rules and upgrade checklist.

## [1.2.0] — unreleased (EPIC #48)

### Added

- SEO: per-route metadata, JSON-LD, `robots.txt` and a dynamic sitemap (#38).
- SEO v2 (#38): stable `/manga/{id}-{slug}` URLs with 301 from old/stale
  slugs, transliterated `url_slug` with a batched background backfill,
  gateway prerender for crawlers/social bots (HTML card + JSON-LD, humans keep
  the SPA), server-side noindex for reader/search/admin/library, slug-only
  sitemap excluding 18+, and env-driven Google/Yandex verification tags.

## [1.1.0] — 2026-11-12 (draft)

### Added

- Web/Capacitor offline library: download a chapter or a whole title, resume an
  interrupted queue, delete downloads and read without network. Browsers use
  IndexedDB; Capacitor uses Filesystem + Preferences; image bytes are never
  stored in `localStorage`.
- Inline `DancingSpinner` for buttons/status rows, a boot loader and route
  fallbacks built on the existing 16 dancing GIFs.
- Admin security: production refuses the default `ADMIN_PASSWORD`; admin JWTs
  carry an HMAC credential fingerprint (`av`) and old sessions return
  `401 admin_session_expired` after `ADMIN_USERNAME`/`ADMIN_PASSWORD` rotation.
- Replica service: periodic SQLite snapshots and chapter-archive sync between
  nodes, with manual promotion. This is **in progress** and not enabled on the
  demo/production deployment yet.
- Remanga adapter: search, catalogue/popular, title details, chapter list and
  reader pages; free chapters work anonymously, paid chapters return a typed
  `chapter_paid` error instead of bypassing the paywall. Source cookies are
  optional and managed from the admin panel.
- Prepare-then-download: idempotent `POST/GET /manga/{id}/prepare`, persistent
  `prepared/pending/failed` progress and client batches of five chapters.
- Comments service (`:8109`): title-only threads, one-level replies, likes,
  spoilers, reports, admin moderation and reply/like notifications.
- Source cookie store: persistent `PARSER_COOKIE_STORE_PATH` (mode `0600`),
  admin status/set/clear routes and `.har` import (server endpoint plus
  browser-side extraction for large files).
- Chapter archive LRU: about 25 GiB, `last_accessed_at`, prune on startup and
  after archiving; metadata and covers are not evicted.
- HTTPS is live at `https://85.192.37.58.nip.io:8443` (Let's Encrypt, HSTS,
  CSP); HTTP `:8088` remains as a compatibility fallback.

### Changed

- Server manager reliability: merge partial deploys into the server inventory,
  stream deploy logs, finish self-deploys, reach remote nodes, allow services on
  jump hosts and order jump hosts after regular app servers in the registry.
- Gateway registry routing: deterministic priority-weighted rendezvous hash,
  with fallbacks tried last. Writes and stateful reads stay on the leader.
- README and docs now distinguish Compose ports (8000–8006) from production
  systemd ports (8100–8109, control 8005).
- User-facing CBZ/PDF/HTML export UI removed; the remaining public export
  routes are deprecated and scheduled for cleanup (#36).
- README and corrupted docs restored from the last clean UTF-8 revision and
  re-applied to v1.1 content; BOM removed and encoding check documented.

### Fixed

- Admin UI clears stale server errors and shows jump-host context in the deploy
  log.
- Partial service deploys no longer replace the whole server inventory.

### Security

- Admin credential rotation invalidates previously issued admin tokens.
- Production validation rejects the default admin password.
- Admin login is limited to five failed attempts per IP per five minutes;
  admin tokens default to 60 minutes.
- Gateway rate limiting trusts nginx `X-Real-IP` instead of the
  client-controlled `X-Forwarded-For`.
- Media proxy re-validates every DNS answer and redirect hop, rejects
  private/link-local/metadata hosts and non-raster image types.
- Source cookies are stored with mode `0600`, never returned by the API, never
  written to the audit log and never forwarded to clients.

### Notes

- Translations/variants, the persistent chapter archive and six themes shipped
  in 1.0.0 and remain part of this release; see the 1.0.0 section below.
- Multi-server priority routing and failover are live. Data replication for a
  real catalogue failover is **in progress** and not enabled in production.

## [1.0.0] — 2026-11-11

### Added

- Microservice architecture: gateway, parser, catalog, library, media,
  scheduler, notifier.
- Shared `manga_common` package: settings, logging, SQLAlchemy 2 async, cache,
  HTTP retry/rate limiting, Argon2id, JWT, normalised source models.
- Catalog: PostgreSQL models, idempotent import, search/filters/sorting,
  chapter pages cache, stale refresh, stats.
- Library: accounts, refresh-token rotation, bookmarks, progress, history,
  reader settings.
- Media: disk image cache with SSRF guard, background CBZ/PDF/HTML exports,
  TTL cleanup.
- Parser: adapter framework, MangaPoisk (full), MangaLib
  (search/catalogue/detail/chapters/pages), Remanga (summary, disabled),
  ReadManga/MangaDex (best-effort, disabled).
- Cross-source variants and translator filter
  (`GET /api/v1/manga/{id}/variants`).
- Persistent chapter archive: SQLite BLOBs for small chapters, ZIP for large
  ones, background warm endpoint.
- Gateway `/api/v1`: catalogue, live search, import, reader, image proxy,
  exports, auth, library, rate limit, aggregated health.
- React + TypeScript web app: home, catalogue, manga, reader, library, auth,
  profile, sources, 404; six themes; mobile bottom navigation.
- Android Jetpack Compose client: home, catalogue, manga, reader, library,
  settings, auth, offline downloads.
- Node.js/Capacitor Android shell built from the React app.
- Docker Compose stack, nginx, healthchecks, GitHub Actions CI, issue/PR
  templates, MIT license.
- Documentation: README, architecture, API, sources, development, deployment,
  legal, legacy mapping.

### Changed

- Removed legacy `app.py`, custom `.mlx` templates, copied bundles and
  hard-coded tokens from `main` (history preserved).
- Replaced direct HTML scraping with normalised adapters and a catalogue cache.

### Security

- Secrets moved to `.env`; production startup refuses default secrets.
- Internal routes require `X-Internal-Token`.
- Public image proxy only accepts URLs resolved from the catalogue.
- Media allowlist and private-host blocking prevent SSRF.
- Refresh tokens stored as SHA-256 hashes; passwords as Argon2id.
