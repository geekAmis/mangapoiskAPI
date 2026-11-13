# Frontend QA — MangaPoisk Reborn

> **Historical QA (12.11.2026).** The audited build predates the 80/443
> migration and v1.3.x. Current production is
> <https://85.192.37.58.nip.io>; `:8443` is legacy API only for APK 1.3.0 and
> `:8088` redirects (except `/ads.txt`). Re-verify findings against current
> v1.3.2 before acting on them.

**Date:** 12 Nov 2026, 06:00–06:50 local (UTC+3)  
**Environment:** production `https://85.192.37.58.nip.io:8443` (historical)<br>
**Build tested:** `index-BvYMjlco.js` / `index-171nzuLo.css`, `Last-Modified: Thu, 12 Nov 2026 03:25:57 GMT`  
**Browser:** Microsoft Edge (Playwright Chromium), desktop 1440×900, mobile 390×844 and 360×800, touch enabled for mobile  
**Accounts:** reader `qa-jump-check@example.com`, admin credentials redacted  
**Verdict: BLOCK for public release.** The product looks close to a shippable MangaLib-style reader, but the offline promise is not functional after a cold start, horizontal mode is unusable for webtoon pages, the catalogue filters are dead, and most auto-populated catalogue entries are empty stubs.

> Build note: production was redeployed during QA from the 2026-11-11 build to the 2026-11-12 03:25 UTC build. An earlier screenshot (`qa-export-dialog-desktop.png`) shows the old CBZ/PDF/HTML export dialog. That dialog is **not present in the current build**; see the “Export UI” pass section below. All other findings below refer to the current build unless explicitly stated.

> **Update 13.11.2026:** this audit covered the older `:8443` deployment.
> Production moved to 80/443 in v1.3.2; the service-worker/offline findings
> below still need re-verification on the current HTTPS deployment. Admin
> credentials in this report are redacted.

---

## 1. Top issues (prioritized)

### 1. BLOCKER — Offline reading cannot survive a closed tab / cold start

**Page / step:** any downloaded title → `/offline/read/...` → close/reload while offline  
**Expected:** the PWA app shell and downloaded pages open without the server. The UI says downloaded chapters are “Доступны без интернета”.  
**Actual:** `navigator.serviceWorker` is `undefined` because the site is served over plain HTTP (`isSecureContext === false`). The new `sw.js` therefore never registers. Reloading `/offline/read/qa-offline-003/...` while offline produces Chrome’s `ERR_INTERNET_DISCONNECTED` page. Offline pages only work while the SPA is already open and the server is reachable for navigation.  
**Evidence:** `docs/screenshots/qa-offline-cold-start-failure.png`  
**Recommendation:** serve production over HTTPS and verify SW install/precache + cold offline deep links; until then remove or qualify the “available without internet” claim. Add a bottom-sheet/offline readiness check and an explicit “работает только в открытой вкладке” state if HTTPS is not available.

### 2. BLOCKER — Horizontal reader mode destroys webtoon pages

**Page / step:** `/reader/93e640d9-78f7-4f4e-9041-2af236cc260c` → Настройки → Постраничный  
**Expected:** one readable page per viewport, fitting the screen or offering pan/zoom.  
**Actual:** a 690×10000 webtoon page is scaled to **52.7×763.8 px** on desktop and **48.8×707.9 px** on mobile, leaving a narrow unreadable strip in a huge black field. A normal manga page (959×1400) renders correctly at 523×764, so the bug is specific to very tall webtoon pages.  
**Evidence:** `docs/screenshots/qa-reader-horizontal-webtoon-desktop.png`, `docs/screenshots/qa-reader-horizontal-mobile-390.png`  
**Recommendation:** segment tall pages into viewport-sized slices for horizontal mode, or automatically force vertical mode when `height/width > ~3`; optionally implement fit-to-width + vertical pan. Do not ship a mode that turns pages into 50 px columns.

### 3. HIGH — Genre and status filters always return zero results

**Page / step:** `/catalogue` → Фильтры → Статус “Выходит” or Жанр “Фэнтези”  
**Expected:** matching titles, or at least a correct “no matches” message.  
**Actual:** both filters return `Найдено: 0`. The API stores status as `Онгоинг` but the UI sends `ongoing`; status `Онгоинг` returns 32 items while `ongoing` returns 0. Genre filters return 0 even for titles that have genre arrays. The empty state then says “В каталоге пока пусто / Подключите источник или импортируйте мангу” even though the catalogue has 151 titles and two active filter chips.  
**Evidence:** `docs/screenshots/qa-catalogue-status-filter-bug-desktop.png`, `docs/screenshots/qa-catalogue-genre-filter-bug-desktop.png`  
**Recommendation:** map UI enum values to the actual stored values (or normalize at the API boundary), normalize genre casing/slugs, and change the filter-empty copy to “Ничего не найдено по выбранным фильтрам” with only “Сбросить фильтры” (no import CTA).

### 4. HIGH — Catalogue is auto-populated, but half of it is dead-end stubs

**Page / step:** `/` and `/catalogue` → first items; `/manga/<id>` for “Милый дом”  
**Expected:** an auto-populated catalogue that leads to readable titles and useful metadata.  
**Actual:** the catalogue did auto-populate without manual URL import — 27 titles at the start of QA, 136 after the bulk import, 151 after live-search imports. But a snapshot of the top 100 by popularity showed **52 items with 0 chapters**, **98 without genres** and **98 without descriptions**. The first popular result, “Милый дом”, opens a dead-end page: “0 глав”, “Глав пока нет”, “Описание пока не добавлено”, no genres; the only recovery is manually pressing “Загрузить главы”. The live-search flow also auto-imports every result, including fan art / artbooks (“Памятник Берсерку”, “артбук по фильму Берсерк”), and grew the catalogue from 27 to 151 during this QA session.  
**Evidence:** `docs/screenshots/qa-home-desktop-full.png`, `docs/screenshots/qa-manga-stub-desktop-1440.png`, `docs/screenshots/qa-manga-stub-mobile-390.png`  
**Recommendation:** do not surface 0-chapter records in “Популярное”, “Обновления”, “Сейчас читают” or the catalogue’s popular sort; hydrate full metadata during import; add a background/queue refresh; make live search an explicit add action or only auto-import complete records; deduplicate case variants (“Магия и Мускулы” vs “Магия и мускулы”, duplicated “Драгоценная дочь…”).

### 5. HIGH — Android APK banner covers content and primary actions on mobile

**Page / step:** Android UA, 390×844 / 360×800, any public page after 1.4 s  
**Expected:** a dismissible promo that does not overlap usable controls.  
**Actual:** `.apk-banner` is `position: fixed; bottom: 78px; z-index: 85`, 366×68.7 px, and no page/body bottom padding is reserved. It visibly covers the second library card’s “Продолжить” button, the downloads empty-state CTA, and source cards; its close target is only 32×32. On desktop the banner is hidden (UA-gated), so this is mobile-only.  
**Evidence:** `docs/screenshots/qa-library-reading-mobile-390.png`, `docs/screenshots/qa-library-downloads-mobile-390.png`, `docs/screenshots/qa-sources-mobile-390.png`  
**Recommendation:** render the promo in flow above the mobile nav or reserve scroll padding while it is visible; make the close target at least 44×44; never cover a primary CTA.

### 6. HIGH (accessibility) — Reader settings switches have no accessible name

**Page / step:** online/offline reader → Настройки чтения  
**Expected:** every checkbox/toggle has a programmatic label.  
**Actual:** Axe reports `label` at **critical** impact for the three switches “Прокручивать автоматически”, “Номера страниц” and “Размывать обложки 18+”. The offline settings sheet has the same defect for its two switches. The visible label text is in a sibling `.setting-row__main`, not associated with the input.  
**Evidence:** `docs/screenshots/qa-reader-settings-desktop.png`, `docs/screenshots/qa-offline-reader-settings-mobile.png` (Axe JSON captured during QA)  
**Recommendation:** add `aria-label`/`aria-labelledby` (and preferably `role="switch"` semantics) to each checkbox, or wrap the whole setting row in a real `<label>`.

### 7. MEDIUM-HIGH — Mobile catalogue pagination buttons have no accessible name

**Page / step:** `/catalogue` at 390×844 → scroll to pagination  
**Expected:** “Назад”/“Вперёд” remain understandable and screen-reader accessible.  
**Actual:** CSS hides the `<span>Назад</span>`/`<span>Вперёд</span>` text at mobile width, leaving icon-only buttons with no `aria-label`, `title` or visible text. Axe reports `button-name` **critical** for both buttons. Desktop keeps the text.  
**Evidence:** `docs/screenshots/qa-catalogue-pagination-mobile-390.png`  
**Recommendation:** add `aria-label="Предыдущая страница"` / `"Следующая страница"` (or keep visible labels) and keep the 44 px hit area.

### 8. MEDIUM — Chapter selection is a tiny, unnamed-looking target

**Page / step:** reader footer at 390×844; offline reader footer  
**Expected:** a clear 44 px “Главы”/chapter picker control.  
**Actual:** the online reader’s chapter picker is the page counter button, measured **32.5×24 px**; the offline picker is **26.8×24 px**. There is no visible “Глава/Оглавление” affordance — only the `1 / 18` counter. The APK close button is also 32×32. Prev/next chapter buttons pass at 44×44.  
**Evidence:** `docs/screenshots/qa-reader-vertical-mobile-390.png`, `docs/screenshots/qa-offline-chapter-picker-mobile.png`  
**Recommendation:** make the picker 44×44+ with an explicit “Главы” icon/label; keep the counter as text; increase the banner close target.

### 9. MEDIUM — Mobile navigation and library tabs hide important destinations

**Page / step:** 390×844 home, library  
**Expected:** clear access to all top-level destinations and all library tabs.  
**Actual:** the bottom nav contains only Главная / Каталог / Библиотека / Профиль. **Источники is missing** from mobile navigation (only reachable from the footer). The header “Войти” link is icon-only and has no accessible name (Axe `link-name`, serious). The library tab strip is 517 px wide inside a 356 px viewport; “Скачано” is fully off-screen at first and there is no scroll affordance. The home “Скачано” CTA points to `/library?tab=downloads`, which is a protected route; guests can start a device download from a title page but are redirected to login when they try to find it via “Скачано”.  
**Evidence:** `docs/screenshots/qa-home-mobile-390.png`, `docs/screenshots/qa-library-reading-mobile-390.png`  
**Recommendation:** add Источники to the mobile nav or a “Ещё” menu; give the icon-only login link `aria-label="Войти"`; add a gradient/arrow or make all tabs fit at 390; either require login before downloading or allow the downloads tab for guests.

### 10. MEDIUM — Manga detail is much thinner than MangaLib’s information architecture

**Page / step:** `/manga/4536d178-...` vs MangaLib reference  
**Expected (MangaLib):** cover + title/score, tabs “О тайтле / Главы / Комментарии / Обсуждения / Карты / Отзывы”, a metadata card with type/format/release/country/chapters/status/authors/artist/publishers/alt names, genre chips.  
**Actual:** our page has cover, title, rating/source/update, year/status/type/chapter count, a source picker, description, and then a single 5,320 px-tall page containing a 60-row chapter list. There is no author/artist/publisher/country/format metadata, no tabbed sections, and descriptions/genres are frequently placeholders or empty. Duplicate titles are not merged.  
**Evidence:** `docs/screenshots/qa-manga-desktop-1440.png`, `docs/screenshots/qa-ref-mangalib-manga-desktop.png`  
**Recommendation:** add a compact metadata block and tabs; hide empty “Описание”/genre sections; enrich imports; dedupe variants; keep the chapter list in its own tab or a compact scroll panel.

---

## 2. Additional defects / notes

| Severity | Issue | Evidence | Recommendation |
|---|---|---|---|
| Medium | **Contrast**: metadata text is `#85796a` at 3.61:1 on `#f1ece2` (catalogue) and 4.18:1 on home cards; brand subtitle is 3.61:1 at 9.28 px. WCAG AA wants 4.5:1 for normal text. | Axe results on home/catalogue/manga; `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png` | Darken muted text, or raise size/weight; test all themes. |
| Medium | **Adult covers blurred by default**: `blurAdultPosters` defaults to `true`; home/catalogue show several featureless grey rectangles with only an `18+` badge. This reads as broken images, and the reveal control is buried in Profile/reader settings. | `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png` | Default to visible, or add an inline “18+ · Показать” control and a clear placeholder pattern. |
| Medium | **Admin health count is inconsistent**: `primary-85` shows “ЗДОРОВЬЕ 9 / 8”. | `qa-admin-dashboard-desktop-1440.png`, `qa-admin-servers-mobile-390.png` | Fix the healthy-count query (dedupe scheduler/replica services). |
| Medium | **Admin mobile audit table**: 720 px table inside a 332 px scroll area and the wrapper has no `tabindex`, so keyboard users cannot reach the horizontal scroll; Axe `scrollable-region-focusable`. Mobile topbar drops the username and “Открыть сайт”; only the logout icon remains. | `qa-admin-dashboard-mobile-390.png`, `qa-admin-servers-mobile-390.png` | `tabindex="0"` + `aria-label` on the table wrapper; keep the site link/username in a compact menu. |
| Medium | **Guest downloads are not discoverable**: `/library?tab=downloads` is behind `ProtectedRoute`, while the title page allows guest “Скачать всё на устройство”. | `qa-home-mobile-390.png`, source `ProtectedRoute.tsx` | Login-gate the download action, or expose an offline downloads route for guests. |
| Low-Medium | **Tab/radiogroup keyboard model**: library tabs (`role="tab"`) and reader settings radiogroups do not implement arrow-key navigation or roving tabindex; each button is tabbable. | source inspection + reader settings screenshots | Add the standard tablist/radiogroup keyboard handler or remove ARIA roles. |
| Low | **Reader footer chapter nav says only “Глава”** on both sides; the destination chapter number is only in a `title` tooltip. | `qa-reader-vertical-mobile-390.png` | Show `Глава N` or the chapter title visibly. |
| Low | **Brand/cover links** produce `label-content-name-mismatch`: `aria-label` omits visible text such as “18+” and timestamps. | Axe home/catalogue results | Include visible text in accessible names, or mark decorative text `aria-hidden`. |
| Low | **Offline empty state/poster fallback** and other icon-only links need a final axe pass after the new offline sheet changes. | `qa-offline-reader-settings-mobile.png` | Re-run axe in CI on all routes and themes. |

### Observed production incident (not a frontend code defect)

From roughly **03:05 to 03:21 UTC** every `/api/v1/*` request returned **502** (`/api/v1/health` included). The frontend handled it gracefully with “Сервер временно недоступен” and “Повторить” on home, catalogue, sources and manga; there was no infinite spinner and no React crash. It recovered when the new build was deployed.  
**Evidence:** `docs/screenshots/qa-api-down-home.png`, `qa-api-down-catalogue.png`, `qa-api-down-manga.png`, `qa-api-down-sources.png`.  
**Recommendation:** add external health monitoring and deploy draining; do not deploy while the catalog gateway is unavailable.

---

## 3. Catalogue auto-population and filters — test details

- **Auto-population:** yes, titles appear without a manual URL import. Initial snapshot at ~06:00: **27 titles**, 24 cards on page 1, `Найдено: 27`. After the bulk import at ~06:30: **136**. After live-search imports during QA: **151**. This proves auto-population works.
- **Search:** local search `q=магия` → 5 results. Search input/debounce/chips work.
- **Sort:** “По алфавиту” updates the order; “По популярности/рейтингу/обновлению” are wired.
- **Pagination:** page 2 loads 24 cards, “Страница 2 из 7”, scrolls to results. Works.
- **Source/year filters:** `source=mangapoisk` → 3 items, `year=2021` → 4 items. Work.
- **Status filter:** UI sends `ongoing`; API data stores `Онгоинг`; `ongoing` → 0, `Онгоинг` → 32. **Broken.**
- **Genre filter:** all tested genre values (including lower-case and upper-case Russian) → 0, despite two items having genre arrays. **Broken.**
- **Empty state:** when filters are active and return 0, the page says “В каталоге пока пусто” and offers “Импортировать мангу”. This is misleading because the catalogue is not empty. **Broken copy.**
- **Live search:** works (e.g. “Berserk” → 12 rows, “Vinland Saga” → 3 rows) and saves results to the catalogue. Posters load once given a few seconds. The auto-import-everything behavior is a product/IA concern, not a loading bug.

---

## 4. Offline reader and settings — what works / what is broken

**Works (while the tab is open and server reachable):**
- A seeded IndexedDB manifest is read by `/offline/manga/<id>`; the offline title page shows chapters, page counts, size, downloaded-at, and an “Открыть офлайн” action.
- `/offline/read/<manga>/<chapter>` loads blob images from IndexedDB, shows page counter, slider, prev/next chapter, chapter picker and progress; progress is saved to IndexedDB.
- The new offline settings sheet exists and includes theme, reading mode (непрерывный/постраничный), fit, gap, autoscroll, page numbers, zoom hint and shortcuts. Changing to “Постраничный” works for normal 800×1200 pages.
- The offline chapter picker sheet works (3 chapters listed, navigation changes the URL and page content).
- The missing-title state is correct: “Тайтл не найден на устройстве” + “К скачанному”.

**Broken / missing:**
- **Cold start offline fails** (blocker #1). The new `sw.js` is inert over HTTP.
- Offline settings switches are unlabeled for assistive tech (issue #6).
- Chapter picker is 26.8×24 px (issue #8).
- There is no offline banner/readiness indicator explaining the tab-only limitation.

**Evidence:** `qa-offline-manga-mobile-new.png`, `qa-offline-reader-mobile-new.png`, `qa-offline-reader-settings-mobile.png`, `qa-offline-reader-horizontal-mobile.png`, `qa-offline-chapter-picker-mobile.png`, `qa-offline-cold-start-failure.png`.

---

## 5. Responsiveness

- **1440×900:** no page-level horizontal overflow on home, catalogue, manga, reader, sources, 404, admin. Admin audit table scrolls internally but not by keyboard.
- **390×844:** no page-level horizontal overflow. However fixed overlays (APK banner) cover content; library tabs overflow; catalogue pagination loses labels; reader footer targets are small.
- **360×800:** no horizontal overflow on home, catalogue, manga, reader. Same fixed-banner and label issues. Screenshots: `qa-home-mobile-360-new.png`, `qa-catalogue-mobile-360-new.png`, `qa-manga-mobile-360-new.png`, `qa-reader-mobile-360-new.png`.
- **Tap targets < 44 px:** reader chapter picker (32×24), offline picker (26.8×24), APK close (32×32), reader page slider thumb/height (18 px track), many card title links (15–39 px high; cover link is large), admin table wrapper not focusable.
- **Clipped / hidden controls:** library “Скачано” tab off-screen at 390; APK banner over library/source CTAs; no page overflow.

---

## 6. Accessibility

**Axe checks run on home, catalogue, manga, reader settings, library downloads, sources, 404, admin.**

- **Critical:** unlabeled reader settings switches (`label`), mobile pagination icon-only buttons (`button-name`).
- **Serious:** mobile header login link has no accessible name (`link-name`); colour contrast 3.61–4.18:1 on metadata; cover links / brand `label-content-name-mismatch`.
- **Moderate:** admin audit scroll region not keyboard-focusable; tab/radiogroup keyboard navigation missing.
- **Passes:** form inputs have `<label for>`; login/register validation messages are associated via `aria-describedby`; buttons/links generally have 2 px accent focus outlines; the skip link works and becomes visible on focus; search input has a visible focus ring via `.searchbox:focus-within`; headings are hierarchical (one H1 per page); reader images have descriptive alts; cover links have aria-labels.
- **Contrast detail:** metadata `#85796a` on `#f1ece2` = 3.61:1; home compact metadata = 4.18:1; brand subtitle = 3.61:1 at 9.28 px. WCAG AA normal text requires 4.5:1.

**Evidence:** axe JSON was captured in `results-*.json` during QA; visual evidence in `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png`, `qa-reader-settings-desktop.png`, `qa-catalogue-pagination-mobile-390.png`.

---

## 7. Console / network / loading states

- **Healthy pages:** 0 uncaught JS errors, 0 failed API requests. `ERR_ABORTED` appears only for cover images aborted by navigation/lazy loading; images that remain in view load correctly (`qa-home-covers-loaded-desktop.png`).
- **API outage:** 502 on all API routes for ~16 minutes; frontend showed explicit error states and retry buttons, no infinite spinner. `qa-api-down-*.png`.
- **Loading:** boot loader is removed after React’s first paint; no eternal spinner observed on home, catalogue, manga, reader, library, sources, login, register, 404, admin.
- **Reader:** skeletons and “Загружаем страницы главы…” resolve; image failures show a retry card rather than a blank page.
- **Live search:** loading skeleton and result list work; posters can take a few seconds to load (normal network).

---

## 8. Admin

Tested `/admin` at 1440×900 and 390×844.

- Login with the admin account works (credentials redacted); dashboard shows 3 server cards, 9 registry groups, 68 audit rows.
- Inventory cards, health badges, service chips, deploy/edit/health/disable actions render.
- **Data bug:** `primary-85` shows health **“9 / 8”**.
- Mobile: cards stack without page-level overflow; audit table is 720 px wide in a 332 px viewport with no keyboard-focusable wrapper; topbar hides username and “Открыть сайт”, leaving only a logout icon.
- Desktop layout is polished and consistent with the admin design language; no clipping on 1440.

**Evidence:** `qa-admin-login-desktop-1440.png`, `qa-admin-dashboard-desktop-1440.png`, `qa-admin-servers-mobile-390.png`.

---

## 9. Export UI check — PASS

Verified against the **current** build (`index-BvYMjlco.js`, 03:25 UTC) by scanning rendered text and every button/link on `/`, `/catalogue`, `/manga/*`, `/library`, `/sources`, `/login`, `/register`, `/404`, `/reader/*`:

- No `CBZ`, `PDF`, `HTML`, `Экспорт` strings or buttons are rendered.
- The only download actions are “Скачать главу на устройство” and “Скачать всё на устройство”, which write pages to IndexedDB (device library), not a file-format export.
- Footer copy is corrected: “скачивайте главы на устройство для чтения без интернета”.
- Note: `qa-export-dialog-desktop.png` is a historical screenshot from the pre-03:25 build and shows the removed CBZ/PDF/HTML dialog. Do not treat it as a current defect.

---

## 10. Comparison with MangaLib (IA / visual language)

**Home:** current build is much closer than the previous editorial hero — header, update grid, “Горячие новинки”, “Сейчас читают” ranking, cover/timestamp labels. It still feels lighter and less dense than MangaLib, and the stub/adult-blur cards make it look unfinished. **Close enough in direction; fix data, not the shell.**

**Header:** desktop matches the MangaLib pattern (logo left, nav/search, auth/theme right). Mobile diverges: no Источники in the bottom nav, icon-only login, and the APK promo occupies the same visual zone as navigation.

**Catalogue cards:** 6-up at 1440 vs MangaLib’s ~8-up; same poster/title/meta grammar. Adult blur and 0-chapter stubs are the main visual differences.

**Manga header:** the biggest IA mismatch. MangaLib has tabbed content and a full metadata card (authors, artist, publisher, country, format, alt names, score split, etc.). Ours is a single very long page with only year/status/type/chapter count, a source picker, a description card and a 60-row chapter list. See `qa-manga-desktop-1440.png` vs `qa-ref-mangalib-manga-desktop.png`.

**Chapter list:** both show volume/chapter/title/date/pages/translator. Ours already has translator filtering and sort — good. Ours needs a tab/compact container to avoid a 5,320 px page; MangaLib separates chapters from the title overview.

**Reader chrome/settings:** settings sheet is structurally close to MangaLib (mode, fit, gap, autoscroll, display, theme, shortcuts). Our persistent chrome is more cluttered, but functional. The horizontal webtoon failure and unlabeled switches are the blocking gaps. Reference: `qa-ref-mangalib-reader-desktop.png`, `qa-ref-mangalib-reader-mobile.png`.

---

## 11. Recommended fix order

1. **HTTPS + verified service worker cold offline start** (blocker #1). Add an end-to-end test: download → close tab → go offline → reopen `/offline/read/...`.
2. **Horizontal/webtoon reading** (blocker #2): segment tall pages or force vertical; add a regression test using a 690×10000 page.
3. **Catalogue filter contract** (high #3): map status values and normalize genres; fix the filter-empty copy; add API/UI tests.
4. **Catalogue data quality** (high #4): hide 0-chapter entries from curated/home surfaces; hydrate metadata; dedupe; make live-search import explicit.
5. **Mobile APK banner placement** (high #5) and tap targets (medium #8).
6. **Accessibility pass** (high #6, medium-high #7): reader switch labels, mobile pagination labels, login link name, contrast, tab keyboard model.
7. **Manga metadata/IA** (medium #10) and library tab affordance/guest downloads (medium #9).
8. **Admin health count and mobile table accessibility** (medium).

---

## 12. Verdict

**BLOCK.** The current build is visually coherent and much closer to MangaLib than the previous one, and it passes the export-removal and offline-settings checks. But a public release would ship with:

- a broken cold-start offline promise on the then-HTTP production URL,
- an unusable horizontal reader for the dominant webtoon page shape,
- dead genre/status filters,
- a catalogue where the top item has zero chapters and the majority of sampled titles lack genres/descriptions,
- a mobile promo overlay that covers primary actions,
- and critical accessibility gaps in reader settings and mobile pagination.

Fix the two blockers, the filter contract and catalogue hydration, then re-run this QA pass. The accessibility and mobile-overlay items can be fixed in the same release cycle.

---

## Appendix — evidence files

Key current-build screenshots:

- `qa-home-desktop-full.png`, `qa-home-mobile-390.png`, `qa-home-mobile-360-new.png`
- `qa-catalogue-desktop-1440.png`, `qa-catalogue-mobile-390.png`, `qa-catalogue-mobile-360-new.png`
- `qa-catalogue-status-filter-bug-desktop.png`, `qa-catalogue-genre-filter-bug-desktop.png`
- `qa-catalogue-pagination-mobile-390.png`, `qa-catalogue-page2-mobile-390.png`
- `qa-manga-desktop-1440.png`, `qa-manga-mobile-390.png`, `qa-manga-stub-desktop-1440.png`, `qa-manga-stub-mobile-390.png`
- `qa-reader-vertical-desktop.png`, `qa-reader-vertical-mobile-390.png`, `qa-reader-settings-desktop.png`, `qa-reader-settings-mobile-390.png`
- `qa-reader-horizontal-webtoon-desktop.png`, `qa-reader-horizontal-mobile-390.png`, `qa-reader-horizontal-manga-desktop.png`
- `qa-offline-manga-mobile-new.png`, `qa-offline-reader-mobile-new.png`, `qa-offline-reader-settings-mobile.png`, `qa-offline-reader-horizontal-mobile.png`, `qa-offline-chapter-picker-mobile.png`
- `qa-offline-cold-start-failure.png`, `qa-offline-reader-mobile-390.png`, `qa-offline-downloads-mobile-390.png`
- `qa-library-reading-mobile-390.png`, `qa-library-downloads-mobile-390.png`, `qa-library-bookmarks-mobile-390.png`, `qa-library-history-mobile-390.png`
- `qa-sources-mobile-390.png`, `qa-sources-desktop-1440.png`, `qa-404-mobile-390.png`, `qa-login-mobile-390.png`, `qa-register-mobile-390.png`
- `qa-admin-login-desktop-1440.png`, `qa-admin-dashboard-desktop-1440.png`, `qa-admin-servers-mobile-390.png`, `qa-admin-dashboard-mobile-390.png`
- MangaLib references: `qa-ref-mangalib-home-desktop.png`, `qa-ref-mangalib-manga-desktop.png`, `qa-ref-mangalib-manga-mobile.png`, `qa-ref-mangalib-reader-desktop.png`, `qa-ref-mangalib-reader-mobile.png`
- Operational incident: `qa-api-down-home.png`, `qa-api-down-catalogue.png`, `qa-api-down-manga.png`, `qa-api-down-sources.png`
- Historical only: `qa-export-dialog-desktop.png` (old build; not a current defect)

Test notes:
- Reader account used to seed one bookmark and progress; no source edits were made.
- Offline manifests `qa-offline-001..004` were seeded only in browser IndexedDB contexts for testing; they are not production content.
- Data counts changed during QA because live search auto-imports results; the 136/151 figures are timestamps, not fixed product state.
