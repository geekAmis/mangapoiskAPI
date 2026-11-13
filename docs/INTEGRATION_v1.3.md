# Integration record — v1.3.0 release candidate

Branch: `release/v1.3-integration`  
Base: `main` @ `fe43baf826ef97694d3c6b280670d974df622ae5`  
Code freeze SHA: `5cf9f023b3b32757204d6f420eaa0ff1b8048239` (feature-complete
merge tip; this document is the following commit).  
Status: **release candidate, not merged to `main`, not deployed.**

This document records the integration order, resolved conflicts, verification
matrix, migration checks, known gaps and the deployment order for v1.3.0.
The lead owns the merge to `main` and the production deploy.

## 1. Merge order

All merges used `--no-ff` and landed directly on
`release/v1.3-integration`, in this order:

| # | Branch | Feature commit | Merge commit | Scope |
|---:|---|---|---|---|
| 1 | `ci/hardening` | `c57b311` | `0e0ae3f` | docs encoding, web unit, mobile build, ops shell checks |
| 2 | `fix/backup-vacuum` | `815d249` | `c3505b2` | `VACUUM INTO` backup, 6 h timeout, weekly WAL checkpoint |
| 3 | `fix/remanga-page-cap` | `c8c8827` | `2ea5033` | Remanga 999-page cap and end-of-catalogue handling |
| 4 | `fix/android-signing` | `b6f5ec0` | `30f54b2` | signed 1.1.0 APK and keystore runbook |
| 5 | `fix/security-hardening` | `468e913` | `5c4dd5f` | production hardening runbook and unit templates |
| 6 | `feat/observability` | `7a5cf4b` | `5b5c115` | metrics, p95/5xx/lock counters, backup age, watchdog, admin panel |
| 7 | `feat/profiles` | `c86cf12` | `94f819b` | public profiles, XP, achievements, events, privacy, moderation |
| 8 | `feat/collections` | `661c8f7` | `d095885` | similar titles, public collections, admin curation, discovery metrics |
| 9 | `feat/seo-production` | `f8c6a5b` | `9dbc166` | slug URLs, bot prerender, server-side noindex, sitemap slugs |
| 10 | `feat/legal-pages` | `efee7f0` | `1b0d690` | terms/privacy/DMCA/contacts/age, consent banner, 18+ gate |
| 11 | `fix/dependency-upgrade` | `5af962f` | `a66ab0f` | Pillow 13.0.0, cryptography 50.0.2, pip-audit policy |
| 12 | `feat/yandex-auth` | `60df4b5` | `4c13de6` | Yandex ID OAuth, DB-backed integration settings, account linking |
| 13 | `perf/catalog-list` | `7445851` | `7918f2f` | materialised catalogue cards, `has_chapters`, partial indexes, latency metrics |
| 14 | `feat/admin-tabs-console` | `1036f351` | `5cf9f02` | tabbed admin, deep links, restricted server console, deploy status |

## 2. Resolved conflicts

Nothing was dropped to make a merge pass. The non-trivial resolutions:

| File / area | Resolution |
|---|---|
| `scripts/ops/mangapoisk-backup.sh` | Kept the `VACUUM INTO` + WAL checkpoint rewrite from #66 and layered the `status.json` running/ok/failed lifecycle from #54/#58 on top. |
| `services/gateway/app/{main,api,clients,config}.py` | Kept observability collector, profile router, SEO/prerender router, collections/discovery clients, Yandex OAuth routes and admin integration routes side by side. |
| `services/catalog/app/{main,migrations,models,repository,service,observability}.py` | Combined `url_slug`/SEO, collections tables, profiles/library migrations, `has_chapters`, `catalog_groups`, partial indexes and slow-query/planner metrics. Sitemap now scans `catalog_groups` and joins `manga` for `url_slug`/title; `similar`/`related` keep `retry_on_locked`. |
| `services/library/app/{main,models,repository,service,migrations}.py` | Kept profile tables/service and Yandex columns/tables/routes; `create_all` + additive Yandex migration run on every startup. |
| `services/control/app/{api,models,service,deployer}.py` | Kept Yandex integration settings, DB-only encrypted secrets, console policy/endpoints and deploy status. |
| `apps/web/src/pages/AdminPage.tsx` | Replaced the monolithic page with the tabbed lazy layout. Added observability to `overview`, collections to `crawler`, profile reports to `comments`, and the real Yandex panel to `integrations`. All previous panels remain reachable. |
| `apps/web/src/styles/admin.css` | Merged tab/console styles with observability, collections, Yandex and profile blocks. The branch CSS was CP1251; the merged file is normalised to UTF-8. |
| `apps/web/{package.json,vite.config.ts}` | Kept Vitest + Testing Library, the legal build-time `__LEGAL_*__` defines, the SEO verification plugin, node progress/profile tests and the admin-tabs test script. |
| `docs/{API,SECURITY,SEO,CHANGELOG}.md` | Kept collections/SEO/Yandex API rows, the security-policy section plus the hardening runbook, legal SEO rows and all changelog entries. |
| `tests/gateway/test_seo.py`, `apps/web/tests/legal-pages.test.tsx` | Kept legal sitemap entries and slug URLs; the consent test now ignores the unrelated `/auth/providers` fetch performed by the Yandex button. |

## 3. Verification matrix (final pass)

Run on the merged tree at `5cf9f023b3b32757204d6f420eaa0ff1b8048239`.

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check packages services tests` | PASS, 0 findings |
| Backend | `pytest` | **552 passed, 1 skipped** (network marker) in 357.61 s |
| Fresh-venv audit | `pip-audit` on all merged requirements | **0 known vulnerabilities** (`manga-common` skipped: local editable package, not on PyPI) |
| Web types | `npm run typecheck` | PASS |
| Web build | `npm run build` | PASS, 207 modules |
| Web component tests | `npm test` (Vitest) | 15/15 PASS |
| Web node tests | `npm run test:unit` | 4/4 PASS (progress + profiles) |
| Admin tab tests | `npm run test:admin-tabs` | 3/3 PASS |
| Mobile web bundle | `npm run build:www` | PASS, 78 files copied, no plain-HTTP API fallback |
| Docs encoding | `python scripts/check_docs_encoding.py` | 39/39 clean UTF-8 |
| Ops syntax | `bash -n scripts/ops/*.sh` | PASS |
| Legal build | `LEGAL_CONTACT_EMAIL=xgemxsite@gmail.com LEGAL_OWNER_NAME=Roman LEGAL_JURISDICTION=Russia npm run build` | PASS; built bundle contains all three real values, no placeholder substitution |
| SEO bot smoke | local gateway + catalog, Googlebot/YandexBot | 301 old/stale slug, canonical 200 with title/canonical/JSON-LD/OG, reader `noindex`, admin/library/empty-search `noindex`, sitemap includes slug + legal URLs |
| Yandex auth smoke | control + gateway TestClient | `/api/v1/auth/providers` = `false` before DB config and `true` after; admin GET masks `client_id`/`client_secret` (hints only), secret absent from responses |
| Console rejection | control API, `{"command":"uptime; id"}` | **422** `console_injection` |
| Admin tabs | deep-link parser and tab definitions | all tabs accepted, unknown falls back to `overview` |

## 4. Migration / startup checks

Production DB copies were not downloadable from this workstation: SSH to both
`jump-83` and `primary-85` returned `Permission denied (publickey,password)`
with the available deploy key. The checks below use a **production-like 100k-row
catalogue** (`catalog-perf/data/bench-timing.db`, 100 000 manga / 80 000
chapters) plus existing QA library/control databases. The lead must repeat the
same smoke on real production copies before deploying.

| Check | Result |
|---|---|
| Catalogue cold startup, 100k rows | **5.381 s** < 10 s; schema 1.39 s; search bootstrap 3.4 s |
| Catalogue `url_slug` migration | column + index created; first 500 slugs backfilled within 4 s of startup without blocking health |
| Catalogue collections | `manga_collections`, `manga_collection_items`, `manga_collection_audit` created; 5 smart collections seeded |
| Catalogue pre-build (`ensure_runtime_schema` + `rebuild_catalog_groups`) | **0.707 s** locally; 20 000 `catalog_groups`, 20 000 `catalog_source_groups`, 0 representatives without chapter rows, 0 cards with `chapters_count <= 0` |
| Catalogue pre-built startup | **2.186 s** < 10 s, `/health` + `/ready` 200, data unchanged |
| `reindex_catalog.py --rebuild-catalog` on 100k copy | total 505.81 s including 100 000-row FTS normalization at 202.94 rows/s; card rebuild itself was sub-second |
| Data preservation | manga 100 000, chapters 80 000 before and after |
| Library migration | startup **0.104 s**; 6 users / 9 progress / 4 bookmarks preserved; `user_profiles`, `xp_events`, `profile_events`, `user_achievements`, `profile_reports`, `profile_blocks` created; `users.yandex_id`, `auth_provider`, `oauth_states`, `oauth_handoff_codes` created |
| Control migration | startup **0.103 s**; 2 servers / 24 audit rows / 5 jobs preserved; `integration_secrets`, `integration_settings` created; `PRAGMA integrity_check` ok |
| Rollback (restore pre-migration copy) | original DBs have no `url_slug`/collections/profile/Yandex tables, same row counts, `integrity_check` ok; additive migrations are backward-compatible |

## 5. Known gaps / lead follow-ups

1. **Production DB copies not verified here** (SSH public key rejected). Repeat
   the catalogue/library/control smoke on copies pulled from `primary-85`
   before the deploy.
2. **PostgreSQL branches not exercised.** Production is SQLite; the PG
   `ALTER TABLE ... IF NOT EXISTS` and index paths are code-reviewed only.
3. **Android APK not rebuilt.** `build:www` passed; `assembleDebug` needs the
   Android SDK and signing material on the release host.
4. **Catalog pre-build timing** is 0.7 s on this workstation; the branch
   measured 6.5–12 s on the production host. Plan a maintenance window for the
   one-time rebuild and keep the pre-build DB copy.
5. **Legal contacts are build-time values.** The RC build used the owner’s
   values; the lead must set `LEGAL_CONTACT_EMAIL`, `LEGAL_OWNER_NAME`,
   `LEGAL_JURISDICTION` in the deploy environment and rebuild the web image.
6. **Yandex credentials** must be entered in Admin → Integrations (DB wins over
   env) or set as bootstrap env values; `/auth/providers` stays `false` until
   all three values are present.
7. **Admin CSS encoding:** the feature branch file was CP1251; it is UTF-8 in
   the merge. A browser smoke of the admin tabs is still recommended.
8. **Web chunk size** is ~642 kB (warning limit 900 kB); not a blocker.

## 6. Deployment order (lead)

Do not merge to `main` or deploy from this branch until the lead signs off.
The order matters because control owns the new config/console APIs and the
catalogue needs its one-time card pre-build.

1. **Freeze and back up.**
   - Stop writes or quiesce the crawler.
   - Take a restic backup and a local copy of `catalog.db`, `library.db`,
     `control.db`, `comments.db`, `archives.db`.
2. **Control first (manual redeploy required).**
   - Deploy the new control code and restart `mangapoisk-control`.
   - Verify startup created `integration_secrets` / `integration_settings`
     and the console/deploy endpoints answer.
   - Check `GET /internal/integrations/yandex` is masked and
     `GET /internal/jobs` works.
3. **Catalogue pre-build (one-time).**
   - On the catalogue copy/backup, run:
     `python scripts/reindex_catalog.py --rebuild-catalog`
   - Expect 6.5–12 s for the card rebuild on production hardware (plus FTS
     time only if `--rebuild-fts` is requested).
   - Verify `catalog_groups` / `catalog_source_groups` counts, no
     representative without chapter rows, and 0 empty cards.
4. **Backend services.**
   - Deploy `catalog`, then `library`, then `gateway` (new code required for
     SEO/prerender, Yandex auth and console proxy).
   - Deploy `parser`, `scheduler`, `media`, `notifier` as needed; the media
     image must install Pillow 13.0.0 and control/notifier cryptography 50.0.2
     from the merged requirements.
   - Verify `/health`, `/ready`, slug 301, `/api/v1/auth/providers`, admin tabs
     and the restricted console.
5. **Configuration.**
   - Set Yandex credentials in Admin → Integrations → Yandex ID (DB values win
     over env; env is bootstrap only).
   - Set `LEGAL_CONTACT_EMAIL`, `LEGAL_OWNER_NAME`, `LEGAL_JURISDICTION` and
     rebuild the web image; verify the real values appear on `/contacts`.
   - Set `WEB_INTERNAL_URL` for nginx and install `infra/nginx/default.conf`
     SEO routes.
6. **Web and mobile.**
   - Deploy the web build and nginx config; smoke `/`, `/manga/{id}-{slug}`,
     `/terms`, `/privacy`, `/dmca`, `/contacts`, `/age`, `/sitemap.xml`.
   - Deploy `apps/mobile/www` or rebuild the Capacitor shell.
7. **Post-deploy checks.**
   - Bot UA: `curl -A Googlebot` for old URL -> 301, canonical -> 200 HTML,
     reader -> `X-Robots-Tag: noindex`; YandexBot likewise.
   - `/sitemap.xml` contains slug URLs and legal pages, excludes 18+ titles.
   - Admin: deep links for every tab, console rejects `uptime; id` with 422,
     masked Yandex GET, deploy status visible.
   - Backup: watchdog status, backup age and `VACUUM INTO` log line.
8. **Rollback.**
   - Restore the pre-deploy DB copies and redeploy the previous images.
   - Additive columns/tables are safe to leave in place; the card tables can
     be rebuilt again with `--rebuild-catalog`.

## 7. Release notes pointer

Feature-level notes live in `docs/CHANGELOG.md`; operational details in
`docs/OPS.md`, `docs/OBSERVABILITY.md`, `docs/SEO.md`, `docs/LEGAL.md`,
`docs/AUTH_YANDEX.md`, `docs/CATALOG_PERFORMANCE.md`, `docs/ADMIN.md` and
`docs/SERVER_CONSOLE.md`.
