---
name: mangapoisk-qa
description: QA and regression workflow for the MangaPoisk Reborn web app, admin panel and Android clients.
---

# MangaPoisk Reborn QA

Use this skill whenever you test the site, reader, offline library or admin panel.

## Targets

- Production web/API: `http://85.192.37.58:8088`, API prefix `/api/v1`.
- Admin: `/admin`. Credentials are in `data.txt` at the workspace root; never include them in reports, screenshots, commits or docs.
- Repo: `repo/`. Run Python from `repo/.venv` (`ruff`, `pytest`), web from `repo/apps/web`.
- Browser automation: Playwright with Edge at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`.
- Android: ADB at `D:\Android\sdk\platform-tools\adb.exe`; package `ru.mangapoisk.reborn` (Capacitor) and `ru.mangapoisk.reborn.debug` (Kotlin).

## Mandatory viewports

- Desktop: `1440x900` and `1280x800`.
- Mobile web: `390x844` with `is_mobile=True, has_touch=True`.
- Small phone: `360x800`.
- Check `document.documentElement.scrollWidth > clientWidth` on every page.

## Core flows

1. Home: auto-populated updates grid, popular grid, ranked lists, source strip; no manual import links required.
2. Catalogue/search: query, source, genre, sort, pagination; first card opens the manga page.
3. Manga: cover/metadata/source variants/translation filter; chapter list; whole-title and single-chapter **device** download; no CBZ/PDF/HTML export UI.
4. Reader: vertical, horizontal and webtoon; fit, gap, theme, font; header title -> manga page; footer -> manga page; prev/next; progress persists; pinch/double-tap zoom on touch.
5. Library: reading, bookmarks, history, downloads; grouped by title; offline title and reader; no horizontal overflow at 390px.
6. Offline: hard reload in airplane/offline mode must open the SPA via service worker; downloaded chapter images come from local storage, not the network.
7. Auth: register/login/logout; protected routes redirect; tokens survive reload.
8. Admin: login, server cards, priority badge, registry, audit, deploy modal, restore-from-replica action.
9. Android: cold boot dancer before content; home/catalogue/search/variants/reader/zoom/library tabs; no console/logcat app errors.

## Failure patterns seen before

- Gateway routing to a secondary node with an empty SQLite DB. Keep `is_fallback=true` on unsynced nodes; primary priority must win.
- Partial deploys erasing the server inventory. Inventory is merged now; verify `primary-85` shows all services.
- `control` self-deploy killing the job. It defers restart by 5s; a job stuck in `running` means an old deployer.
- Standalone nginx config is `/opt/mangapoisk-reborn/nginx/nginx.conf`; system `nginx.service` is unrelated and failed for another project. Never restart system nginx.
- Web offline reload fails without the service worker. Check `navigator.serviceWorker.controller`.
- GIF boot loader is large; check transfer size and cache headers.

## Reporting

- Screenshots go to `docs/screenshots/qa-*` or `perf-*`.
- Write findings with severity, page, viewport, steps, expected/actual, screenshot and fix.
- Block release on: console errors, failed API requests, horizontal overflow, broken auth, empty reader, export-format UI, infinite spinners, admin 5xx, or a page that requires manual import to show content.
