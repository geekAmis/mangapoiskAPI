# Changelog

All notable changes are documented here.  Format: Keep a Changelog; versioning:
SemVer.

## [Unreleased]

- Shared database or replication for multi-node catalogue/library failover.
- Alembic migrations for destructive schema changes.
- Redis-backed global rate limiting.
- S3-compatible media storage.
- More verified sources (MangaDex/ReadManga).
- HentaiLib age-gated source (#45): branch `feat/hentailib-age-gate` is ready
  but the source remains disabled; not in production v1.3.2.
- AI deploy supervisor (#75): branch `feat/ai-deploy-supervisor` is ready but
  needs OpenCode auth and is not deployed.
- Search author/typo fix (#76): branch `fix/search-author-typo` is ready;
  production v1.3.2 still has no author search and misses `чензо мен`.
- Yandex Metrika and traffic panel (#85): in progress, not in production
  v1.3.2.

## [1.3.2] — 2026-11-13

Tag: `v1.3.2` → `affe7d0`. This is a web/infra hotfix release: no GitHub
release and no APK asset were published.

### Added

- Standard public ports **80/443** for `https://85.192.37.58.nip.io`:
  `http://` and `www` redirect 301 to apex HTTPS; canonical/OG/sitemap URLs no
  longer contain `:8443`.
- Let's Encrypt certificate with SAN `85.192.37.58.nip.io` +
  `www.85.192.37.58.nip.io`, valid until **2027-02-11**; renewal switched to
  webroot `/var/www/certbot` with a reload hook for `mangapoisk-web.service`.
- Legacy compatibility: `:8443` serves **API only** for APK 1.3.0 (web pages
  301 to 443); `:8088` redirects to 443 for every path except `/ads.txt`.
- `ads.txt` (9 lines) served directly as `200 text/plain` on ports 80, 443 and
  8088, without redirect; includes `yandex.com, 20411736, DIRECT` and
  `yandex.com, 334843219, DIRECT`.
- Yandex RTB web integration: loader `yaContextCb`/`context.js`, block
  `R-A-20411736-1` in `in-feed`, admin Block ID field, public `config.block_id`
  and CSP allowances for `yandex.ru`, `an.yandex.ru` and `yastatic.net`.
- Production RTB provider `c57fb6e5-23e6-4d97-b7b4-66af8b7b9c43` with
  `require_consent=false` and `exclude_adult=true`.
- Cookie-only consent banner: short `Cookie` text, `Принять` /
  `Только необходимые`; ads continue to render regardless of the choice, while
  other providers with `require_consent=true` still respect it.
- Android APK **1.3.2 / versionCode 5** built from `release/android-1.3.2` with
  packaged `www` (no `server.url`), `androidScheme=https`, origin
  `https://localhost`, API `https://85.192.37.58.nip.io/api/v1`; installed over
  1.3.1 without uninstall, restoring the 1.3.0 session and local data.

### Fixed

- Android 1.3.1 remote `server.url` regression (#84): the remote origin broke
  WebView layout/taps and hid the old `https://localhost` session; 1.3.2
  returns to the packaged `www`.
- `/privacy` horizontal overflow at 390 px: legal tables now scroll inside
  `.legal-table-wrap` instead of widening the page (all five legal routes
  verified at 390×844).

### Notes

- Real Yandex RTB rendering is externally blocked: the SDK reports
  `PAGE_DISABLED Page "20411736" is disabled` until the owner enables the
  site/block. Yandex also rejected РСЯ moderation for <100 real visitors/week;
  resubmission is available from **2026-11-20 05:55**.
- Android QA was paused by the owner after cold-launch/session restoration
  passed; reader/downloads/notifications and other items remain unverified.

## [1.3.1] — 2026-11-13 (hotfix, no tag)

- Port migration to standard HTTPS 443: public web/API moved off `:8443`;
  nginx redirect matrix, certificate SAN/renewal and no-port canonical/OG were
  prepared and deployed in stages.
- Yandex OAuth redirect URI switched to
  `https://85.192.37.58.nip.io/api/v1/auth/yandex/callback`.
- Android 1.3.1 (versionCode 4) was built on 443 but used a remote
  `server.url=https://85.192.37.58.nip.io`. That changed the WebView origin,
  broke layout/taps and hid the old `https://localhost` session; the regression
  is tracked in #84 and fixed in 1.3.2. There is no `v1.3.1` git tag.

## [1.3.0] — 2026-11-13

Tag: `v1.3.0` → `71be724`; GitHub release published.

### Added

- SEO v2 (#38): stable `/manga/{id}-{slug}` URLs with 301 from old/stale
  slugs, transliterated `url_slug` with a batched background backfill,
  gateway prerender for crawlers/social bots (HTML card + JSON-LD, humans keep
  the SPA), server-side noindex for reader/search/admin/library, slug-only
  sitemap excluding 18+, and env-driven Google/Yandex verification tags.
  Production sitemap: ~25,189 URLs with no port.
- Public reader profiles (#47): `/u/{username}`, XP/levels/ranks,
  achievements, activity feed, privacy controls and profile moderation.
- Discovery (#43): “Похожее” (`related`) and public smart/manual collections,
  editorial admin, metrics and caching.
- Yandex ID OAuth (#67): DB-only encrypted credentials managed in
  `Админка → Интеграции → Яндекс ID`, account linking, scopes
  `login:email login:info login:avatar`; real production login confirmed.
- Legal pages (#69): `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`,
  cookie banner, 18+ gate, real contacts
  (`xgemxsite@gmail.com`, owner `Roman`, jurisdiction `Russia`).
- Catalogue list performance (#68): `has_chapters` visibility flag,
  materialised `catalog_groups`/`catalog_source_groups` card tables, bounded
  SQLite `PRAGMA optimize`, slow-query logging and p50/p95 list latency in
  admin stats. Production deploy check: p95 ~45 ms gateway / ~34 ms catalog.
- Admin tabs and restricted server console (#73/#74): lazy tab panels, deep
  links, deploy status, allowlist console and structured actions.
- Observability (#58): p95/5xx/SQLite lock counters, backup age, watchdog and
  admin panel.
- Remanga page-cap fix (#59): 999-page cap and end-of-catalogue handling.
- Backup rewrite (#66): `VACUUM INTO` snapshots, 6 h timeout and weekly WAL
  checkpoint.
- Security hardening (#71): DB/file permissions, UMask, fail2ban, SSH
  hardening, rate-limit verification.
- CI hardening (#70): docs encoding, web unit tests, mobile bundle and ops
  shell checks.
- Android 1.3.0 signed APK (versionCode 3) with production keystore.

### Fixed

- Reader resume prompt (#81): “Продолжить со страницы N?” now appears only
  after a 1.8 s idle grace period and only when the saved page is more than one
  page ahead. Wheel, touch, scroll, page changes, page clicks and keyboard
  navigation dismiss it immediately, so a slow progress response cannot show it
  over a chapter the user has already started reading.

### Security

- Bumped `Pillow` to `>=13.0.0,<14` in the media service and `cryptography` to
  `>=50.0.2,<51` in the control and notifier services (#77). This resolves the
  40 Pillow 12.3.0 and 7 cryptography 47.0.0 advisories reported by
  `pip-audit`; the updated environment reports 0 known vulnerabilities.
- Added `docs/SECURITY.md` and `docs/DEPENDENCIES.md` with the reporting
  process, audit cadence, pinning rules and upgrade checklist.

## [1.2.0] — 2026-11-12 (no separate tag; included in v1.3.0)

### Added

- SEO: per-route metadata, JSON-LD, `robots.txt` and a dynamic sitemap (#38).
- SEO v2 (#38): stable `/manga/{id}-{slug}` URLs with 301 from old/stale
  slugs, transliterated `url_slug` with a batched background backfill,
  gateway prerender for crawlers/social bots (HTML card + JSON-LD, humans keep
  the SPA), server-side noindex for reader/search/admin/library, slug-only
  sitemap excluding 18+, and env-driven Google/Yandex verification tags.

## [1.1.0] — 2026-11-12 (no separate tag; included in v1.3.0)

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
- HTTPS went live on the then-current `:8443` endpoint (Let's Encrypt, HSTS,
  CSP); HTTP `:8088` was the compatibility fallback at that time. Since v1.3.2
  the public site is on 80/443, `:8443` is legacy API only and `:8088`
  redirects to 443 (except `/ads.txt`).

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
