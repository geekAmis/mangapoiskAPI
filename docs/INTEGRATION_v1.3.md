# Integration record — v1.3.0 → v1.3.2

Branch history: `release/v1.3-integration` → `main`.<br>
Base: `main` @ `fe43baf826ef97694d3c6b280670d974df622ae5`  
Code freeze SHA: `5cf9f023b3b32757204d6f420eaa0ff1b8048239` (feature-complete
merge tip).<br>
Status: **v1.3.0 released and deployed; v1.3.2 hotfix deployed.** The
production web runs `main` @ `affe7d0` (`v1.3.2`). Android 1.3.2 is installed on
the QA device, but Android QA is paused (#84) and no GitHub APK asset exists.

This document records the integration order, resolved conflicts, verification
matrix, migration checks, known gaps and the deployment order for v1.3.x.
The lead owns merges to `main` and production deploys.

## 0. Release status

| Release | Ref | Status |
|---|---|---|
| `v1.3.0` | `71be724` | GitHub release published; deployed 13.11.2026 |
| `v1.3.1` | no tag | port-migration stage; Android 1.3.1 remote `server.url` regression (#84) |
| `v1.3.2` | `affe7d0` | deployed web/infra/RTB hotfix; tag only, no GitHub release/APK |

Production facts: site on 80/443, cert SAN apex+www until 2027-02-11, canonical
and sitemap without port (~25,189 URLs), `ads.txt` direct 200 on 80/443/8088,
Yandex ID real login confirmed, RTB provider
`c57fb6e5-23e6-4d97-b7b4-66af8b7b9c43` with `require_consent=false`.

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

## 3.1 Post-deploy verification (v1.3.2, 13.11.2026)

| Check | Result |
|---|---|
| Redirect matrix | 80/443 200; `http`/`www` 301; `:8443` API 200 / web 301; `:8088` 301 except `/ads.txt` |
| Certificate | SAN apex+www; expires 2027-02-11; targeted `certbot renew --dry-run` passed |
| Canonical/OG/sitemap | no `:8443`, no `http://`; sitemap ~25,189 URLs |
| `ads.txt` | 200 `text/plain`, 9 lines, no Location on 80/443/8088 |
| Yandex ID | real login confirmed; redirect URI no port; `login:info` enabled |
| Ads config | guest/auth include `config.block_id=R-A-20411736-1`; no secrets |
| Real RTB | external `PAGE_DISABLED Page "20411736" is disabled`; РСЯ resubmit from 2026-11-20 05:55 |
| Android 1.3.2 | installed over 1.3.1; packaged `www`, origin `https://localhost`, API 443; cold launch/session restore PASS; QA paused |
| CI | backend, web, docs encoding, mobile-web, ops, android and compose jobs configured; docs encoding check passed locally |

## 4. Migration / startup checks

Production DB copies were not downloadable during the RC pass: SSH to both
`jump-83` and `primary-85` returned `Permission denied (publickey,password)`
with the available deploy key. The checks below use a **production-like 100k-row
catalogue** (`catalog-perf/data/bench-timing.db`, 100 000 manga / 80 000
chapters) plus existing QA library/control databases. v1.3.0 was deployed and
the live post-deploy smoke passed; repeat the migration/restore drill on a
fresh backup before the next destructive change.

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

## 5. Known gaps / follow-ups (post-deploy, 2026-11-13)

1. **Android QA paused (#84).** 1.3.2/code 5 is installed and cold launch /
   session restore passed, but reader, downloads, notifications, `/privacy`
   overflow, Yandex ID and the new v1.3 features were not re-checked. Do not
   publish the APK until QA resumes.
2. **Yandex RTB is externally blocked (#83).** Loader, `ads.txt`, CSP, provider
   and `config.block_id` are deployed; the SDK reports
   `PAGE_DISABLED Page "20411736" is disabled` until the owner enables the
   site/block. РСЯ moderation is deferred until ≥100 real visitors/week
   (resubmit from 2026-11-20 05:55).
3. **Search author/typo (#76) is not deployed.** Production still has no
   author search and misses `чензо мен`; the fix is in
   `fix/search-author-typo`.
4. **SSH key-only (#78) and web/admin hardening (#79) remain open.** Root
   password SSH, broad CSP and lack of admin MFA/IP allowlist are documented in
   [`SECURITY.md`](SECURITY.md).
5. **Legacy ports remain (#82).** `:8443` is API-only for APK 1.3.0; `:8088`
   redirects except `/ads.txt`. Remove after old clients are retired.
6. **Metrika/traffic panel (#85) is not in v1.3.2.** Do not describe it as
   live.
7. **Production DB copies were not available during the RC pass.** The
   post-deploy smoke used the live service; re-run the migration/restore drill
   on a fresh backup before the next destructive change.
8. **PostgreSQL branches were not exercised in production.** Production is
   SQLite; PG paths are code-reviewed only.

## 6. Deployment order (v1.3.0, executed; v1.3.2 hotfix)

The v1.3.0 order below was executed by the lead and is kept as a reproducible
runbook. v1.3.2 was a web/infra hotfix: merge `feat/yandex-rtb`, rebuild web
with `VITE_SITE_URL=https://85.192.37.58.nip.io`, apply the CSP/ads.txt nginx
changes, reload `mangapoisk-web.service`, create the RTB provider and verify
the redirect matrix. No DB migration was required.

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
   - Set `WEB_INTERNAL_URL=http://127.0.0.1:8089` for nginx/static prerender
     and install `infra/nginx/default.conf` SEO routes.
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
