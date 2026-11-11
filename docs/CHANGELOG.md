# Changelog

All notable changes are documented here.  Format: Keep a Changelog; versioning:
SemVer.

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
- Parser: adapter framework, MangaPoisk (full), MangaLib (search/catalogue),
  Remanga (summary, disabled), ReadManga/MangaDex (best-effort, disabled).
- Gateway `/api/v1`: catalogue, live search, import, reader, image proxy,
  exports, auth, library, rate limit, aggregated health.
- React + TypeScript web app: home, catalogue, manga, reader, library, auth,
  profile, sources, 404; six themes; mobile bottom navigation.
- Android Jetpack Compose client: home, catalogue, manga, reader, library,
  settings, auth.
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

## [Unreleased]

- Alembic migrations for destructive schema changes.
- Redis-backed global rate limiting.
- S3-compatible media storage.
- More verified sources.
