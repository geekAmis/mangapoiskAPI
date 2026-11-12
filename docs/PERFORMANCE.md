# MangaPoisk Reborn вЂ” performance & UX audit

**Audited:** 2026-11-11, 10:50вЂ“11:10 MSK  
**Production:** <https://85.192.37.58.nip.io:8443> (HTTP, nginx 1.28.3, HTTP/1.1)  
**Frontend bundle audited:** `/assets/index-BjlbtnB4.js` (477,131 B), `/assets/index-Dnn-IPAM.css` (109,652 B)  
**Browser:** Microsoft Edge `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, Playwright 1.64.1, fresh context per page, 1440Г—900 and 390Г—844  
**API client:** httpx 0.28.1, 1 warm-up + 10 measured runs per endpoint  
**Repo:** current working tree at the time of the audit (priority-routing merge `02705fd` plus uncommitted docs/source changes from other sessions). No source files were changed by this audit.

> **Production stability caveat.** The site was intermittently unreachable during the audit window (at least three short outages/restarts, в‰€10:58, в‰€11:06 and в‰€11:12); httpx saw `ReadTimeout`/`ReadError` between runs and the last probe did not complete. The page table below is a coherent cold-load snapshot from **Run A (10:50вЂ“10:57)**. **Run B (11:00вЂ“11:04)** was a clean recheck of the same JS bundle and is summarised separately because image/lazy-load variance was large. The API table is from **Run B**, after the first restart.

---

## 1. Executive summary

The frontend is visually polished and has no page-level horizontal overflow, but delivery is still вЂњdevelopment serverвЂќ quality:

1. **No HTTP compression.** The 477 KB JS bundle and 110 KB CSS are sent raw on every cold load (`content-encoding: null`). Gzip would make them 143 KB / 19 KB; Brotli 122 KB / 16 KB. API JSON is also uncompressed: a 269-chapter manga detail is 129вЂ“136 KB raw, 17 KB gzipped.
2. **Reader images dominate the experience.** One 720-px-wide manga page is 686вЂ“885 KB. A reader open fetches 3 pages = **3.0вЂ“3.4 MB**; first image took **1.95 s desktop / 4.29 s mobile** in Run A and **8.45 s / 3.93 s** in Run B. The media proxy has no resize/quality parameters.
3. **The boot dancer is a large blocking-ish asset.** A random 81вЂ“340 KB GIF is loaded by inline HTML before React, on every cold page. The 16 GIFs total 2.45 MB in the build; none has `Cache-Control`.
4. **Manga detail is oversized and causes CLS 0.20.** `/manga/{id}` returns all 269 chapters in one 129вЂ“136 KB JSON payload. On desktop the footer is initially at `y=719` and then jumps out of the viewport when content loads, producing CLS **0.20** (the only page above the 0.1 вЂњgoodвЂќ threshold).
5. **The web offline story is broken.** There is no service worker. With the network disabled, an already-open Library still shows В«РЎРєР°С‡Р°РЅРѕВ», but a reload fails with `net::ERR_INTERNET_DISCONNECTED`; the web offline banner never appears because `OfflineBanner` is Capacitor-only.
6. **Mobile accessibility regressions are easy to fix.** At в‰¤420 px the header вЂњР’РѕР№С‚РёвЂќ text and pagination labels are `display:none`, leaving links/buttons with no accessible name (axe: `button-name` critical Г—2, `link-name` serious). Sources and Admin have serious contrast failures (3.16вЂ“3.89:1).
7. **Admin priority is half-deployed.** The live API already returns `priority` values (`primary-85=10`, `jump-83=50`, `aeza-2=100`), and the repo source contains the priority badge + `#admin-server-priority` field, but the production frontend (`index-BjlbtnB4.js`) renders neither. Also, `primary-85` shows В«Р—Р”РћР РћР’Р¬Р• 8 / 7В» because the numerator includes Scheduler while the denominator excludes it.

---

## 2. Page-load metrics (Run A, cold context)

All times in **ms**, transfer in **MB** (CDP `encodedDataLength`, includes document + images + fetch), JS/CSS in **KB** (KiB).  
`First card` = first `.manga-card` inserted into the DOM; `First image` = first manga cover or first reader page whose `naturalWidth > 0`.  
`Console`/`Failed` are site errors only; the audit harnessвЂ™s own MutationObserver inject was excluded after verification. There were **0 console errors, 0 page errors, 0 failed requests, 0 4xx/5xx** on all normal page loads.

### Desktop 1440Г—900

| Page | TTFB | DCL | Load | FCP | LCP | First card | First image | Transfer | JS | CSS | Req | CLS | H-scroll |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Home | 528 | 1455 | 2339 | 1372 | 1880 | 1935 | 2304 (poster) | 2.83 | 466 | 107 | 29 | 0.02 | no |
| Catalogue | 135 | 971 | 1198 | 788 | 1236 | 2270 | вЂ” | 0.85 | 466 | 107 | 8 | 0.00 | no |
| Search В«РјР°РіРёСЏВ» | 322 | 1268 | 1589 | 1008 | 2272 | 1772 | вЂ” | 1.04 | 466 | 107 | 10 | 0.00 | no |
| Manga | 415 | 1108 | 1158 | 924 | 1172 | вЂ” | 1629 (cover) | 0.97 | 466 | 107 | 8 | **0.20** | no |
| Reader | 182 | 864 | 3192 | 728 | 2228 | вЂ” | 1951 (page 1) | 3.72 | 503 | 113 | 14 | 0.00 | no |
| Library вЂ” РЎРєР°С‡Р°РЅРѕ | 352 | 1212 | 1463 | 1100 | 1484 | вЂ” | вЂ” | 0.77 | 466 | 107 | 5 | 0.01 | no |
| Login | 502 | 1342 | 1360 | 1092 | 1352 | вЂ” | вЂ” | 0.80 | 466 | 107 | 5 | 0.00 | no |
| Sources | 515 | 1575 | 2220 | 1556 | 1636 | вЂ” | вЂ” | 0.82 | 466 | 107 | 7 | 0.03 | no |
| Admin login | 131 | 958 | 1130 | 796 | 1088 | вЂ” | вЂ” | 0.92 | 510 | 126 | 7 | 0.00 | no |
| Admin dashboard | 519 | 1704 | 2193 | 1680 | 2092 | вЂ” | вЂ” | 0.95 | 510 | 126 | 13 | 0.02 | no |

### Mobile 390Г—844

| Page | TTFB | DCL | Load | FCP | LCP | First card | First image | Transfer | JS | CSS | Req | CLS | H-scroll |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Home | 135 | 653 | 1027 | 556 | 756 | 1083 | 1433 (poster) | 0.92 | 466 | 107 | 10 | 0.01 | no |
| Catalogue | 460 | 1694 | 1749 | 1336 | 1768 | 2230 | вЂ” | 0.67 | 466 | 107 | 7 | 0.00 | no |
| Search В«РјР°РіРёСЏВ» | 149 | 665 | 846 | 632 | 864 | 927 | 1437 | 0.81 | 466 | 107 | 8 | 0.00 | no |
| Manga | 513 | 1591 | 2513 | 1480 | 2612 | вЂ” | вЂ” | 0.83 | 466 | 107 | 6 | 0.00 | no |
| Reader | 841 | 1835 | 7085 | 1592 | 4568 | вЂ” | **4291** (page 1) | 3.60 | 503 | 113 | 14 | 0.00 | no |
| Library вЂ” РЎРєР°С‡Р°РЅРѕ | 238 | 966 | 966 | 624 | 732 | вЂ” | вЂ” | 0.67 | 466 | 107 | 8 | 0.00 | no |
| Login | 143 | 1214 | 1504 | 1032 | 1456 | вЂ” | вЂ” | 0.71 | 466 | 107 | 6 | 0.00 | no |
| Sources | 576 | 1648 | 2323 | 1464 | 1880 | вЂ” | вЂ” | 0.87 | 466 | 107 | 6 | 0.08 | no |
| Admin login | 730 | 2096 | 2482 | 1788 | 2540 | вЂ” | вЂ” | 0.71 | 510 | 126 | 6 | 0.00 | no |
| Admin dashboard | 245 | 906 | 906 | 708 | 800 | вЂ” | вЂ” | 1.00 | 510 | 126 | 14 | 0.00 | no |

### Run B recheck / variance (same bundle)

| Observation | Run A | Run B |
|---|---:|---:|
| Home desktop transfer | 2.83 MB, 29 req | 0.73 MB, 9 req |
| Catalogue desktop transfer | 0.85 MB, 8 req | **3.45 MB, 33 req** (all 24 covers lazy-loaded) |
| Reader desktop first image | 1.95 s | **8.45 s** (LCP 8.74 s) |
| Reader mobile first image | 4.29 s | 3.93 s (load 4.76 s) |
| Reader desktop transfer | 3.72 MB | 3.93 MB |
| Library desktop TTFB | 0.35 s | 2.13 s (outlier) |

**Interpretation:** image/lazy-load behaviour is not deterministic. The same catalogue page can download only 3 covers or all 24; ChromeвЂ™s lazy-load threshold, network conditions and layout height interact. For SLO reporting use the worst observed transfer (в‰€3.5 MB desktop catalogue, в‰€4 MB reader), not the best run. The server was also restarted twice, so some of the TTFB spread is deployment noise rather than frontend code.

### Layout / overflow

- `document.documentElement.scrollWidth === innerWidth` on every tested page at both sizes; **no page-level horizontal scroll or offenders** were found.
- Library tabs at 390 px: `clientWidth=356`, `scrollWidth=519`, `scrollLeft=163`; the В«РЎРєР°С‡Р°РЅРѕВ» tab is scrolled into view and the first tab (В«РџСЂРѕРґРѕР»Р¶РёС‚СЊВ») is partially clipped. Internal tab scroll works, but there is no visible cue that more tabs exist.
- Admin audit table at 390 px is horizontally scrollable (`.admin-table-wrap`) but is not keyboard-focusable (axe `scrollable-region-focusable`).

---

## 3. API latency (10 runs, Run B)

Timings are end-to-end from the audit machine (same network path as the browser). `p95` uses linear interpolation.

| Endpoint | p50 | p95 | max | Avg response |
|---|---:|---:|---:|---:|
| `GET /api/v1/health` | 108 ms | 119 ms | 123 ms | 0.1 KB |
| `GET /api/v1/manga?limit=24&sort=popular` | 152 ms | 199 ms | 204 ms | 20.7 KB |
| `GET /api/v1/manga?query=РјР°РіРёСЏ` | 130 ms | 169 ms | 170 ms | 3.8 KB |
| `GET /api/v1/manga/{id}` | 292 ms | 473 ms | 600 ms | 104 KB |
| `GET /api/v1/manga/{id}/chapters` | 153 ms | 594 ms | 844 ms | 23.4 KB |
| `GET /api/v1/chapters/{id}` | 171 ms | 520 ms | 543 ms | 1.4 KB |
| `GET /api/v1/chapters/{id}/pages` | 130 ms | 142 ms | 149 ms | 0.8 KB |
| `GET /api/v1/chapters/{id}/images/1` | **1106 ms** | **1927 ms** | 2071 ms | **885 KB** |
| `GET /api/v1/sources` | 139 ms | 613 ms | 698 ms | 1.3 KB |
| `POST /api/v1/auth/login` | 562 ms | 695 ms | 721 ms | 0.6 KB |
| `GET /api/v1/admin/servers` | 252 ms | 284 ms | 297 ms | 3.2 KB |
| `GET /api/v1/admin/registry` | 117 ms | 182 ms | 200 ms | 4.8 KB |
| `GET /api/v1/admin/audit?limit=100` | 181 ms | 380 ms | 381 ms | 15.3 KB |

**Slow endpoints (>1 s):** only the image proxy. Its p50 is >1 s and p95 в‰€1.9 s because 686вЂ“885 KB is transferred per page; a reader requests several pages at once. Search/chapters were 530/530 ms p50 in the pre-restart run, then 130/153 ms after warm-up вЂ” backend variance, not a frontend regression.

`/manga/{id}` for the 269-chapter title returns **129вЂ“136 KB** (gzip: **17 KB**). That is both a bandwidth and JSON-parse/render cost on the manga page.

---

## 4. Asset delivery and static headers

| Asset | Bytes | Content-Encoding | Cache-Control | Notes |
|---|---:|---|---|---|
| `/` HTML | 5,270 | none | вЂ” | ETag only; no cache policy |
| `/assets/index-BjlbtnB4.js` | 477,131 | **none** | `max-age=2592000` | gzip 143,142 B (30%); Brotli 122,508 B (26%) |
| `/assets/index-Dnn-IPAM.css` | 109,652 | **none** | `max-age=2592000` | gzip 19,422 B (18%); Brotli 16,428 B (15%) |
| `/loading/dance-01.gif` | 180,863 | none | **none** | 16 dance GIFs, total 2,571,407 B; largest 339,550 B |
| `/manifest.webmanifest` | 1,478 | none | вЂ” | served as `application/octet-stream` (should be `application/manifest+json`) |
| `/api/v1/*` JSON | 0.6вЂ“136 KB | **none** | `no-store` | no gzip/Brotli |
| `/api/v1/chapters/*/images/*` | 686вЂ“885 KB | none | `public, max-age=86400, stale-while-revalidate=604800` | JPEG; no `w`/`q`/format variant |

- HTTP/1.1 only; no TLS. With 14вЂ“33 requests and multi-MB images, this misses HTTP/2 multiplexing and adds connection overhead.
- Production headers differ from `infra/nginx/default.conf`: that file has `gzip on` and `add_header Cache-Control "public, immutable"`, but production returns neither compression nor `immutable`. Check the actual deployed nginx config before changing code.
- The boot dancer file is chosen randomly from 16 GIFs and has no long-lived cache header, so cold loads and revalidations repeatedly pay 81вЂ“340 KB.

---

## 5. UX findings

### Boot loader / spinners
- At 390Г—844 with the JS bundle delayed, `#boot-loader` is visible full-screen (`role="status"`, text В«Р—Р°РіСЂСѓР¶Р°РµРј MangaPoiskвЂ¦В», GIF `/loading/dance-13.gif` complete) before any JS. Screenshot: `perf-boot-loader-mobile.png`.
- After React paints, the loader gets `.is-done`, fades, and is removed; verified detached with `#root` populated.
- No circular CSS spinners remain. The only `@keyframes spin` in CSS is unused by rendered elements; all loading indicators are `.dancing-spinner` GIF images.
- Cost: every cold load downloads one 81вЂ“340 KB GIF just to hide it after React boots. The boot image is also not `Cache-Control`-cached.

### Reader
- Header and footer are visible at both sizes. Header back + title link в†’ `/manga/{mangaId}`; footer TOC link в†’ `/manga/{mangaId}`. Prev/next are buttons with proper disabled states; footer counter opens the chapter sheet. This works as intended.
- The first two pages are `loading="eager"`; the rest are `loading="lazy"`. With the current image sizes, the eager pair alone is enough to make mobile reader first paint slow.
- Mobile reader screenshot shows the first page at 390Г—844; the image is visually sharp, but the delivered file is 686вЂ“885 KB for a 720-px-wide source. There is no low-quality placeholder/blurhash; users stare at a skeleton/blank page while the proxy fetch completes.

### Library / offline
- At 390Г—844 the В«РЎРєР°С‡Р°РЅРѕВ» tab shows the correct empty state: В«РќР° СѓСЃС‚СЂРѕР№СЃС‚РІРµ РїРѕРєР° РЅРёС‡РµРіРѕ РЅРµС‚В» with actions В«Р’С‹Р±СЂР°С‚СЊ РјР°РЅРіСѓВ» / В«Рљ РїСЂРѕРґРѕР»Р¶РµРЅРёСЋ С‡С‚РµРЅРёСЏВ».
- Tabs scroll internally: 356 px viewport vs 519 px content; the active tab is auto-scrolled into view. The first tab is clipped at `left=-142` after the auto-scroll; a fade/chevron affordance would help.
- With `context.set_offline(true)` + `window.dispatchEvent(new Event('offline'))`:
  - `navigator.onLine === false`;
  - **offline banner count = 0** (web banner is Capacitor-only);
  - the already-open downloads tab remains usable;
  - `page.reload()` fails with `net::ERR_INTERNET_DISCONNECTED`.
- No service worker is registered in the repo, so the app shell cannot cold-start offline. The copy В«РіР»Р°РІС‹ Р±СѓРґСѓС‚ РґРѕСЃС‚СѓРїРЅС‹ Р±РµР· РёРЅС‚РµСЂРЅРµС‚Р°В» is only true while the SPA stays open (or inside the Capacitor native shell). For the web build this is a UX promise the product does not keep.
- The screenshot after the failed offline reload is `perf-offline-reload-mobile.png` (browser error page).

### Manga page layout shift
- Desktop CLS **0.20**; the layout-shift source is `FOOTER.site-footer`: previous rect `y=719 h=181`, current rect `0Г—0` when content replaces the short loading state. The footer is initially visible near the fold and then jumps below the long loaded page.
- Fix by reserving the loaded pageвЂ™s height (hero + chapters skeleton with matching min-height) or hiding the footer while the manga query is loading. This is a small CSS/JS change with a large perceived-quality gain.

---

## 6. Admin check (no deployment performed)

Login `lilanga / Test13131` works. Dashboard stats observed:

- **3 servers** (2 marked fallback): `jump-83`, `primary-85`, `aeza-2`.
- **15 / 16 healthy HTTP services**; per-card: jump `2/2`, primary **`8/7`**, aeza `7/7`.
- **8 registry groups / 18 endpoints**.
- **60 audit rows** (last 100).
- Server cards render service pills with ports; deploy / edit / health / enable / fallback / delete actions are present.
- Deploy modal: 8 service checkboxes + 1 вЂњupdate images/repoвЂќ switch (9 checkboxes total); configured services are preselected, unconfigured ones are marked вЂњРЅРµ РЅР°СЃС‚СЂРѕРµРЅвЂќ; confirm step lists only the selected configured services. Closing/Escape works. We did **not** submit a deployment.
- The log terminal is only created after a job starts. It is `aria-live="polite"`, auto-scrolls, and the job query polls every **2 s** (`refetchInterval` 2000) while status is queued/running. There is no SSE/WebSocket, so вЂњstreamingвЂќ is really 2-second polling; runtime log streaming was not exercised because no deploy was started.

### Priority field and deployment drift
- API returns `priority`: `primary-85=10`, `jump-83=50`, `aeza-2=100`.
- Repo source already contains the `P{priority}` badge (`AdminServerCard.tsx`) and the numeric `#admin-server-priority` field (`ServerFormModal.tsx`, label В«РџСЂРёРѕСЂРёС‚РµС‚В», 0вЂ“10000).
- The **deployed** frontend (`index-BjlbtnB4.js`) does **not** render the P badge and the edit modal has **no** `#admin-server-priority` field. This is a stale frontend deployment, not a missing source feature.

### Admin UI bug
`primary-85` displays В«Р—Р”РћР РћР’Р¬Р• **8 / 7**В». In `AdminServerCard.tsx:36-37`, `healthy` counts all services (including Scheduler) while `checked` excludes Scheduler. Either exclude Scheduler from the numerator or include it in the denominator; the same issue affects the aggregate вЂњ15 / 16вЂќ semantics if Scheduler is counted inconsistently.

---

## 7. Accessibility (axe-core 4.10.2 + keyboard focus check)

| Page / viewport | Finding | Severity | Detail |
|---|---|---|---|
| All mobile pages в‰¤420 px | Header В«Р’РѕР№С‚РёВ» link has no accessible name | serious | `.header-login span { display:none }` (layout.css:439) removes the only text; no `aria-label` on the link |
| Catalogue mobile | Pagination prev/next buttons have no accessible name (Г—2) | **critical** | `.pagination__button span { display:none }` (components.css:1631); icon-only buttons lack `aria-label` |
| Sources desktop + mobile | 15 color-contrast failures | serious | source code 3.34:1, disabled status 3.16:1, capability labels 3.34:1 (need 4.5:1) |
| Admin dashboard desktop + mobile | 16 color-contrast failures | serious | registry badges / checked labels 3.88вЂ“3.89:1 at 10 px (need 4.5:1) |
| Admin mobile | Audit table scroll region not keyboard focusable | serious | `.admin-table-wrap` needs `tabindex=0` + `aria-label` or a responsive table |
| Login / Admin login | No `<main>` landmark; content outside landmarks | moderate | Auth layout wraps everything in `<div>`; add `<main>` and landmarks |
| Reader desktop + mobile | No `<h1>` | moderate | Page must have a level-one heading; add visually hidden h1 or promote chapter title |
| All pages | Images alt / input labels / button names (except above) | pass | 0 images without `alt`; 0 inputs without label; 0 unnamed buttons on desktop |

**Focus rings:** 16-step keyboard pass on Home and Login found a visible 2 px accent outline (or a `focus-within` ring on the search container) on every focused control. No focus-ring failures. Search input itself has `outline:0`, but its `.searchbox:focus-within` wrapper supplies a 3 px accent-soft ring вЂ” visually acceptable, though `outline` on the input would be more robust for forced-colors mode.

**Contrast of main text/buttons** is acceptable; the failures are small muted labels, disabled badges and registry secondary text.

---

## 8. Console / network errors

- **Site console errors:** 0 on Home, Catalogue, Search, Manga, Reader, Library, Login, Sources, Admin login and Admin dashboard.
- **Page errors:** 0 after excluding one audit-harness-injected `MutationObserver` error (the harness observed `document.documentElement` before it existed; fixed and re-verified with a clean pass). This was not app code.
- **Failed requests / 4xx / 5xx:** 0 on normal loads. The only failure is the deliberate offline reload (`net::ERR_INTERNET_DISCONNECTED`).
- **Availability:** two production restarts during the window caused temporary httpx timeouts/resets; no application-level console error was observed.
- **Vite modulepreload polyfill** creates a `MutationObserver` on `document`; it is valid and not the source of the harness error.

---

## 9. Screenshots

All screenshots are viewport captures at the stated size and are under `docs/screenshots/`.

| File | Content |
|---|---|
| `perf-home-desktop.png` | Home 1440Г—900, hero + start of popular grid |
| `perf-home-mobile.png` | Home 390Г—844 |
| `perf-catalogue-desktop.png` | Catalogue 1440Г—900 with sorting chips |
| `perf-catalogue-mobile.png` | Catalogue 390Г—844, filters and 2-column grid |
| `perf-search-desktop.png` | Search results for В«РјР°РіРёСЏВ», 1440Г—900 |
| `perf-search-mobile.png` | Search results for В«РјР°РіРёСЏВ», 390Г—844 |
| `perf-manga-desktop.png` | Manga detail, blurred 18+ cover, chapters panel |
| `perf-manga-mobile.png` | Manga detail 390Г—844 |
| `perf-reader-desktop.png` | Reader page 1 at 1440Г—900, header + footer visible |
| `perf-reader-mobile.png` | Reader page 1 at 390Г—844 |
| `perf-library-desktop.png` | Library В«РЎРєР°С‡Р°РЅРѕВ» empty state, 1440Г—900 |
| `perf-library-mobile.png` | Library В«РЎРєР°С‡Р°РЅРѕВ» empty state, scrollable tabs, 390Г—844 |
| `perf-login-desktop.png` | Login form 1440Г—900 |
| `perf-login-mobile.png` | Login form 390Г—844 |
| `perf-sources-desktop.png` | Sources cards 1440Г—900 |
| `perf-sources-mobile.png` | Sources cards 390Г—844 |
| `perf-admin-login-desktop.png` | Admin login 1440Г—900 |
| `perf-admin-login-mobile.png` | Admin login 390Г—844 |
| `perf-admin-desktop.png` | Admin dashboard, server cards, registry, audit |
| `perf-admin-mobile.png` | Admin dashboard 390Г—844 |
| `perf-admin-deploy-desktop.png` | Deploy modal, service selection (not submitted) |
| `perf-admin-deploy-mobile.png` | Deploy modal at 390Г—844 |
| `perf-admin-deploy-confirm-desktop.png` | Deploy confirmation step (not submitted) |
| `perf-admin-deploy-confirm-mobile.png` | Deploy confirmation at 390Г—844 |
| `perf-boot-loader-mobile.png` | Boot dancer visible before the JS bundle, 390Г—844 |
| `perf-offline-reload-mobile.png` | Browser error after offline reload |

---

## 10. Recommendations, ranked by impact / effort

Effort: **XS** < 1 h, **S** 1вЂ“4 h, **M** 1вЂ“2 days, **L** > 2 days. Impact is user-perceived and applies to the current architecture.

| # | Recommendation | Impact | Effort | Evidence / expected gain |
|---|---|---|---|---|
| 1 | **Enable Brotli/gzip for HTML, JS, CSS and API JSON.** Add `brotli on` (or `gzip on` + `gzip_proxied any`, `gzip_vary on`) to the deployed nginx; ensure `/api/` is included. | Very high | S | JS 477в†’122 KB Brotli (26%); CSS 110в†’16 KB (15%); manga JSON 129в†’17 KB (13%). Saves ~500 KB on every cold SPA load and ~110 KB on manga detail. |
| 2 | **Resize/re-encode reader images in the media proxy.** Support `?w=360/720/1080/1440&q=70&format=avif|webp`, cache variants by URL+width, and emit `srcset`; keep originals for export. | Very high | M | 686вЂ“885 KB per page today; 720-px AVIF/WebP should be ~40вЂ“90 KB. Reader view 3.0вЂ“3.4 MB в†’ ~0.2вЂ“0.4 MB; first image 1.95вЂ“8.45 s в†’ target <1 s on 4G. |
| 3 | **Replace the 16 boot GIFs with a small inline/CSS/SVG/Lottie animation**, or one в‰¤20 KB WebP, served with `Cache-Control: public, max-age=31536000, immutable`; preload it only when the boot screen is actually used. | High | S | 81вЂ“340 KB removed from every cold page; 2.45 MB removed from the build. Big win on login/library/sources where the GIF is the largest image. |
| 4 | **Stop returning 269 chapters in `/manga/{id}`.** Return title metadata + first 60 chapters (or a chapter summary) and paginate the rest via `/manga/{id}/chapters`; gzip the JSON. | High | M | 129вЂ“136 KB raw / 17 KB gzip today. Manga page mobile LCP was 2.6 s and first run TTFB 0.5 s; smaller payload reduces parse/render and makes the chapter list interactive sooner. |
| 5 | **Fix manga-page CLS 0.20.** Reserve the final hero/chapter height while loading, or hide the footer until the manga query settles; give the cover explicit width/height/aspect-ratio. | Medium-high | S | Layout-shift source is `FOOTER.site-footer` moving from y=719 to 0Г—0. Target CLS <0.05. |
| 6 | **Add a web app shell service worker + web offline banner.** Precache HTML, JS, CSS, icons and the offline fallback; cache-first for hashed assets, network-first for API; show a banner using `navigator.onLine`/`online`/`offline` events (not only Capacitor). | High (UX) | M | Offline reload currently fails; downloaded chapters cannot be reopened after closing the tab. Also aligns the В«РґРѕСЃС‚СѓРїРЅС‹ Р±РµР· РёРЅС‚РµСЂРЅРµС‚Р°В» copy with reality. |
| 7 | **Fix mobile accessible names and contrast.** Add `aria-label` to header login and pagination prev/next; use visually-hidden text instead of `display:none`; raise source/registry muted tokens to в‰Ґ4.5:1; add `tabindex=0` + label to `.admin-table-wrap`. | Medium | S | Axe critical `button-name` Г—2 and serious `link-name`; 31 contrast failures across Sources + Admin; all are CSS/markup-only. |
| 8 | **Deploy the rebuilt frontend for the priority feature (or hide it).** Backend already returns priority; current production UI has no P badge and no priority input. Also fix the `8 / 7` healthy count by excluding Scheduler from the numerator. | High (feature correctness) | S | API values 10/50/100; repo has `#admin-server-priority`; deployed bundle does not. The `8/7` ratio is visibly wrong in the admin card. |
| 9 | **Bound the number of eager/lazy cover images on Home/Catalogue.** Use IntersectionObserver with a small rootMargin, explicit aspect-ratio placeholders, and `fetchpriority="high"` only for the first 1вЂ“2 covers. | Medium | S/M | Same catalogue page loaded 3 covers (0.85 MB) or all 24 (3.45 MB, 33 req). Worst-case home is ~3 MB. |
| 10 | **Serve over HTTPS + HTTP/2 (or HTTP/3) and add `immutable` to hashed assets; fix manifest MIME type.** | Medium | M | 14вЂ“33 requests per page on HTTP/1.1; `immutable` is already in repo nginx config but missing in production; manifest is `application/octet-stream`. |
| 11 | **Add `Content-Type: application/manifest+json` and cache headers for boot assets/icons**; set `Vary: Accept-Encoding` when compression is enabled. | Low-medium | XS | Correct installability/metadata and fewer revalidations. |

### What is already good
- No horizontal overflow at 1440 or 390; responsive layout is solid.
- No console errors, failed requests or 4xx/5xx on normal pages.
- Focus rings are visible and consistent on desktop; all images have `alt`; labels/inputs are associated.
- Reader header/footer navigation, disabled prev/next states and chapter sheet work.
- Admin deploy UI has a clear service selection/confirm flow; no circular CSS spinners remain.
- LCP on Home is 0.76 s mobile / 1.88 s desktop in the representative run; most pages feel fast once assets are cached.

---

## 11. Reproduction notes

- Playwright launched Edge headless with a fresh `BrowserContext` per scenario; no CPU/network throttling was applied. Transfer bytes come from CDP `Network.loadingFinished.encodedDataLength`.
- `.manga-card` and first-poster timings were recorded with a `MutationObserver` + 40 ms polling in an init script.
- API measurements used a single keep-alive httpx client, 1 warm-up + 10 timed requests, sequential.
- Authentication: admin `lilanga / Test13131`; Library used a temporary test account `perf.audit.20261111@example.com` created through the public registration endpoint solely to reach the protected `/library` route. It has no bookmarks/progress/downloads, so the В«РЎРєР°С‡Р°РЅРѕВ» tab exercises the true empty state.
- No deployment was started from the admin UI; only the configure and confirm steps were opened and closed.
