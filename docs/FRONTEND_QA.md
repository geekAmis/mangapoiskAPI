# Frontend QA вЂ” MangaPoisk Reborn

**Date:** 12 Nov 2026, 06:00вЂ“06:50 local (UTC+3)  
**Environment:** production `https://85.192.37.58.nip.io:8443`  
**Build tested:** `index-BvYMjlco.js` / `index-171nzuLo.css`, `Last-Modified: Thu, 12 Nov 2026 03:25:57 GMT`  
**Browser:** Microsoft Edge (Playwright Chromium), desktop 1440Г—900, mobile 390Г—844 and 360Г—800, touch enabled for mobile  
**Accounts:** reader `qa-jump-check@example.com`, admin `lilanga` / `Test13131`  
**Verdict: BLOCK for public release.** The product looks close to a shippable MangaLib-style reader, but the offline promise is not functional after a cold start, horizontal mode is unusable for webtoon pages, the catalogue filters are dead, and most auto-populated catalogue entries are empty stubs.

> Build note: production was redeployed during QA from the 2026-11-11 build to the 2026-11-12 03:25 UTC build. An earlier screenshot (`qa-export-dialog-desktop.png`) shows the old CBZ/PDF/HTML export dialog. That dialog is **not present in the current build**; see the вЂњExport UIвЂќ pass section below. All other findings below refer to the current build unless explicitly stated.

---

## 1. Top issues (prioritized)

### 1. BLOCKER вЂ” Offline reading cannot survive a closed tab / cold start

**Page / step:** any downloaded title в†’ `/offline/read/...` в†’ close/reload while offline  
**Expected:** the PWA app shell and downloaded pages open without the server. The UI says downloaded chapters are вЂњР”РѕСЃС‚СѓРїРЅС‹ Р±РµР· РёРЅС‚РµСЂРЅРµС‚Р°вЂќ.  
**Actual:** `navigator.serviceWorker` is `undefined` because the site is served over plain HTTP (`isSecureContext === false`). The new `sw.js` therefore never registers. Reloading `/offline/read/qa-offline-003/...` while offline produces ChromeвЂ™s `ERR_INTERNET_DISCONNECTED` page. Offline pages only work while the SPA is already open and the server is reachable for navigation.  
**Evidence:** `docs/screenshots/qa-offline-cold-start-failure.png`  
**Recommendation:** serve production over HTTPS and verify SW install/precache + cold offline deep links; until then remove or qualify the вЂњavailable without internetвЂќ claim. Add a bottom-sheet/offline readiness check and an explicit вЂњСЂР°Р±РѕС‚Р°РµС‚ С‚РѕР»СЊРєРѕ РІ РѕС‚РєСЂС‹С‚РѕР№ РІРєР»Р°РґРєРµвЂќ state if HTTPS is not available.

### 2. BLOCKER вЂ” Horizontal reader mode destroys webtoon pages

**Page / step:** `/reader/93e640d9-78f7-4f4e-9041-2af236cc260c` в†’ РќР°СЃС‚СЂРѕР№РєРё в†’ РџРѕСЃС‚СЂР°РЅРёС‡РЅС‹Р№  
**Expected:** one readable page per viewport, fitting the screen or offering pan/zoom.  
**Actual:** a 690Г—10000 webtoon page is scaled to **52.7Г—763.8 px** on desktop and **48.8Г—707.9 px** on mobile, leaving a narrow unreadable strip in a huge black field. A normal manga page (959Г—1400) renders correctly at 523Г—764, so the bug is specific to very tall webtoon pages.  
**Evidence:** `docs/screenshots/qa-reader-horizontal-webtoon-desktop.png`, `docs/screenshots/qa-reader-horizontal-mobile-390.png`  
**Recommendation:** segment tall pages into viewport-sized slices for horizontal mode, or automatically force vertical mode when `height/width > ~3`; optionally implement fit-to-width + vertical pan. Do not ship a mode that turns pages into 50 px columns.

### 3. HIGH вЂ” Genre and status filters always return zero results

**Page / step:** `/catalogue` в†’ Р¤РёР»СЊС‚СЂС‹ в†’ РЎС‚Р°С‚СѓСЃ вЂњР’С‹С…РѕРґРёС‚вЂќ or Р–Р°РЅСЂ вЂњР¤СЌРЅС‚РµР·РёвЂќ  
**Expected:** matching titles, or at least a correct вЂњno matchesвЂќ message.  
**Actual:** both filters return `РќР°Р№РґРµРЅРѕ: 0`. The API stores status as `РћРЅРіРѕРёРЅРі` but the UI sends `ongoing`; status `РћРЅРіРѕРёРЅРі` returns 32 items while `ongoing` returns 0. Genre filters return 0 even for titles that have genre arrays. The empty state then says вЂњР’ РєР°С‚Р°Р»РѕРіРµ РїРѕРєР° РїСѓСЃС‚Рѕ / РџРѕРґРєР»СЋС‡РёС‚Рµ РёСЃС‚РѕС‡РЅРёРє РёР»Рё РёРјРїРѕСЂС‚РёСЂСѓР№С‚Рµ РјР°РЅРіСѓвЂќ even though the catalogue has 151 titles and two active filter chips.  
**Evidence:** `docs/screenshots/qa-catalogue-status-filter-bug-desktop.png`, `docs/screenshots/qa-catalogue-genre-filter-bug-desktop.png`  
**Recommendation:** map UI enum values to the actual stored values (or normalize at the API boundary), normalize genre casing/slugs, and change the filter-empty copy to вЂњРќРёС‡РµРіРѕ РЅРµ РЅР°Р№РґРµРЅРѕ РїРѕ РІС‹Р±СЂР°РЅРЅС‹Рј С„РёР»СЊС‚СЂР°РјвЂќ with only вЂњРЎР±СЂРѕСЃРёС‚СЊ С„РёР»СЊС‚СЂС‹вЂќ (no import CTA).

### 4. HIGH вЂ” Catalogue is auto-populated, but half of it is dead-end stubs

**Page / step:** `/` and `/catalogue` в†’ first items; `/manga/<id>` for вЂњРњРёР»С‹Р№ РґРѕРјвЂќ  
**Expected:** an auto-populated catalogue that leads to readable titles and useful metadata.  
**Actual:** the catalogue did auto-populate without manual URL import вЂ” 27 titles at the start of QA, 136 after the bulk import, 151 after live-search imports. But a snapshot of the top 100 by popularity showed **52 items with 0 chapters**, **98 without genres** and **98 without descriptions**. The first popular result, вЂњРњРёР»С‹Р№ РґРѕРјвЂќ, opens a dead-end page: вЂњ0 РіР»Р°РІвЂќ, вЂњР“Р»Р°РІ РїРѕРєР° РЅРµС‚вЂќ, вЂњРћРїРёСЃР°РЅРёРµ РїРѕРєР° РЅРµ РґРѕР±Р°РІР»РµРЅРѕвЂќ, no genres; the only recovery is manually pressing вЂњР—Р°РіСЂСѓР·РёС‚СЊ РіР»Р°РІС‹вЂќ. The live-search flow also auto-imports every result, including fan art / artbooks (вЂњРџР°РјСЏС‚РЅРёРє Р‘РµСЂСЃРµСЂРєСѓвЂќ, вЂњР°СЂС‚Р±СѓРє РїРѕ С„РёР»СЊРјСѓ Р‘РµСЂСЃРµСЂРєвЂќ), and grew the catalogue from 27 to 151 during this QA session.  
**Evidence:** `docs/screenshots/qa-home-desktop-full.png`, `docs/screenshots/qa-manga-stub-desktop-1440.png`, `docs/screenshots/qa-manga-stub-mobile-390.png`  
**Recommendation:** do not surface 0-chapter records in вЂњРџРѕРїСѓР»СЏСЂРЅРѕРµвЂќ, вЂњРћР±РЅРѕРІР»РµРЅРёСЏвЂќ, вЂњРЎРµР№С‡Р°СЃ С‡РёС‚Р°СЋС‚вЂќ or the catalogueвЂ™s popular sort; hydrate full metadata during import; add a background/queue refresh; make live search an explicit add action or only auto-import complete records; deduplicate case variants (вЂњРњР°РіРёСЏ Рё РњСѓСЃРєСѓР»С‹вЂќ vs вЂњРњР°РіРёСЏ Рё РјСѓСЃРєСѓР»С‹вЂќ, duplicated вЂњР”СЂР°РіРѕС†РµРЅРЅР°СЏ РґРѕС‡СЊвЂ¦вЂќ).

### 5. HIGH вЂ” Android APK banner covers content and primary actions on mobile

**Page / step:** Android UA, 390Г—844 / 360Г—800, any public page after 1.4 s  
**Expected:** a dismissible promo that does not overlap usable controls.  
**Actual:** `.apk-banner` is `position: fixed; bottom: 78px; z-index: 85`, 366Г—68.7 px, and no page/body bottom padding is reserved. It visibly covers the second library cardвЂ™s вЂњРџСЂРѕРґРѕР»Р¶РёС‚СЊвЂќ button, the downloads empty-state CTA, and source cards; its close target is only 32Г—32. On desktop the banner is hidden (UA-gated), so this is mobile-only.  
**Evidence:** `docs/screenshots/qa-library-reading-mobile-390.png`, `docs/screenshots/qa-library-downloads-mobile-390.png`, `docs/screenshots/qa-sources-mobile-390.png`  
**Recommendation:** render the promo in flow above the mobile nav or reserve scroll padding while it is visible; make the close target at least 44Г—44; never cover a primary CTA.

### 6. HIGH (accessibility) вЂ” Reader settings switches have no accessible name

**Page / step:** online/offline reader в†’ РќР°СЃС‚СЂРѕР№РєРё С‡С‚РµРЅРёСЏ  
**Expected:** every checkbox/toggle has a programmatic label.  
**Actual:** Axe reports `label` at **critical** impact for the three switches вЂњРџСЂРѕРєСЂСѓС‡РёРІР°С‚СЊ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёвЂќ, вЂњРќРѕРјРµСЂР° СЃС‚СЂР°РЅРёС†вЂќ and вЂњР Р°Р·РјС‹РІР°С‚СЊ РѕР±Р»РѕР¶РєРё 18+вЂќ. The offline settings sheet has the same defect for its two switches. The visible label text is in a sibling `.setting-row__main`, not associated with the input.  
**Evidence:** `docs/screenshots/qa-reader-settings-desktop.png`, `docs/screenshots/qa-offline-reader-settings-mobile.png` (Axe JSON captured during QA)  
**Recommendation:** add `aria-label`/`aria-labelledby` (and preferably `role="switch"` semantics) to each checkbox, or wrap the whole setting row in a real `<label>`.

### 7. MEDIUM-HIGH вЂ” Mobile catalogue pagination buttons have no accessible name

**Page / step:** `/catalogue` at 390Г—844 в†’ scroll to pagination  
**Expected:** вЂњРќР°Р·Р°РґвЂќ/вЂњР’РїРµСЂС‘РґвЂќ remain understandable and screen-reader accessible.  
**Actual:** CSS hides the `<span>РќР°Р·Р°Рґ</span>`/`<span>Р’РїРµСЂС‘Рґ</span>` text at mobile width, leaving icon-only buttons with no `aria-label`, `title` or visible text. Axe reports `button-name` **critical** for both buttons. Desktop keeps the text.  
**Evidence:** `docs/screenshots/qa-catalogue-pagination-mobile-390.png`  
**Recommendation:** add `aria-label="РџСЂРµРґС‹РґСѓС‰Р°СЏ СЃС‚СЂР°РЅРёС†Р°"` / `"РЎР»РµРґСѓСЋС‰Р°СЏ СЃС‚СЂР°РЅРёС†Р°"` (or keep visible labels) and keep the 44 px hit area.

### 8. MEDIUM вЂ” Chapter selection is a tiny, unnamed-looking target

**Page / step:** reader footer at 390Г—844; offline reader footer  
**Expected:** a clear 44 px вЂњР“Р»Р°РІС‹вЂќ/chapter picker control.  
**Actual:** the online readerвЂ™s chapter picker is the page counter button, measured **32.5Г—24 px**; the offline picker is **26.8Г—24 px**. There is no visible вЂњР“Р»Р°РІР°/РћРіР»Р°РІР»РµРЅРёРµвЂќ affordance вЂ” only the `1 / 18` counter. The APK close button is also 32Г—32. Prev/next chapter buttons pass at 44Г—44.  
**Evidence:** `docs/screenshots/qa-reader-vertical-mobile-390.png`, `docs/screenshots/qa-offline-chapter-picker-mobile.png`  
**Recommendation:** make the picker 44Г—44+ with an explicit вЂњР“Р»Р°РІС‹вЂќ icon/label; keep the counter as text; increase the banner close target.

### 9. MEDIUM вЂ” Mobile navigation and library tabs hide important destinations

**Page / step:** 390Г—844 home, library  
**Expected:** clear access to all top-level destinations and all library tabs.  
**Actual:** the bottom nav contains only Р“Р»Р°РІРЅР°СЏ / РљР°С‚Р°Р»РѕРі / Р‘РёР±Р»РёРѕС‚РµРєР° / РџСЂРѕС„РёР»СЊ. **РСЃС‚РѕС‡РЅРёРєРё is missing** from mobile navigation (only reachable from the footer). The header вЂњР’РѕР№С‚РёвЂќ link is icon-only and has no accessible name (Axe `link-name`, serious). The library tab strip is 517 px wide inside a 356 px viewport; вЂњРЎРєР°С‡Р°РЅРѕвЂќ is fully off-screen at first and there is no scroll affordance. The home вЂњРЎРєР°С‡Р°РЅРѕвЂќ CTA points to `/library?tab=downloads`, which is a protected route; guests can start a device download from a title page but are redirected to login when they try to find it via вЂњРЎРєР°С‡Р°РЅРѕвЂќ.  
**Evidence:** `docs/screenshots/qa-home-mobile-390.png`, `docs/screenshots/qa-library-reading-mobile-390.png`  
**Recommendation:** add РСЃС‚РѕС‡РЅРёРєРё to the mobile nav or a вЂњР•С‰С‘вЂќ menu; give the icon-only login link `aria-label="Р’РѕР№С‚Рё"`; add a gradient/arrow or make all tabs fit at 390; either require login before downloading or allow the downloads tab for guests.

### 10. MEDIUM вЂ” Manga detail is much thinner than MangaLibвЂ™s information architecture

**Page / step:** `/manga/4536d178-...` vs MangaLib reference  
**Expected (MangaLib):** cover + title/score, tabs вЂњРћ С‚Р°Р№С‚Р»Рµ / Р“Р»Р°РІС‹ / РљРѕРјРјРµРЅС‚Р°СЂРёРё / РћР±СЃСѓР¶РґРµРЅРёСЏ / РљР°СЂС‚С‹ / РћС‚Р·С‹РІС‹вЂќ, a metadata card with type/format/release/country/chapters/status/authors/artist/publishers/alt names, genre chips.  
**Actual:** our page has cover, title, rating/source/update, year/status/type/chapter count, a source picker, description, and then a single 5,320 px-tall page containing a 60-row chapter list. There is no author/artist/publisher/country/format metadata, no tabbed sections, and descriptions/genres are frequently placeholders or empty. Duplicate titles are not merged.  
**Evidence:** `docs/screenshots/qa-manga-desktop-1440.png`, `docs/screenshots/qa-ref-mangalib-manga-desktop.png`  
**Recommendation:** add a compact metadata block and tabs; hide empty вЂњРћРїРёСЃР°РЅРёРµвЂќ/genre sections; enrich imports; dedupe variants; keep the chapter list in its own tab or a compact scroll panel.

---

## 2. Additional defects / notes

| Severity | Issue | Evidence | Recommendation |
|---|---|---|---|
| Medium | **Contrast**: metadata text is `#85796a` at 3.61:1 on `#f1ece2` (catalogue) and 4.18:1 on home cards; brand subtitle is 3.61:1 at 9.28 px. WCAG AA wants 4.5:1 for normal text. | Axe results on home/catalogue/manga; `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png` | Darken muted text, or raise size/weight; test all themes. |
| Medium | **Adult covers blurred by default**: `blurAdultPosters` defaults to `true`; home/catalogue show several featureless grey rectangles with only an `18+` badge. This reads as broken images, and the reveal control is buried in Profile/reader settings. | `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png` | Default to visible, or add an inline вЂњ18+ В· РџРѕРєР°Р·Р°С‚СЊвЂќ control and a clear placeholder pattern. |
| Medium | **Admin health count is inconsistent**: `primary-85` shows вЂњР—Р”РћР РћР’Р¬Р• 9 / 8вЂќ. | `qa-admin-dashboard-desktop-1440.png`, `qa-admin-servers-mobile-390.png` | Fix the healthy-count query (dedupe scheduler/replica services). |
| Medium | **Admin mobile audit table**: 720 px table inside a 332 px scroll area and the wrapper has no `tabindex`, so keyboard users cannot reach the horizontal scroll; Axe `scrollable-region-focusable`. Mobile topbar drops the username and вЂњРћС‚РєСЂС‹С‚СЊ СЃР°Р№С‚вЂќ; only the logout icon remains. | `qa-admin-dashboard-mobile-390.png`, `qa-admin-servers-mobile-390.png` | `tabindex="0"` + `aria-label` on the table wrapper; keep the site link/username in a compact menu. |
| Medium | **Guest downloads are not discoverable**: `/library?tab=downloads` is behind `ProtectedRoute`, while the title page allows guest вЂњРЎРєР°С‡Р°С‚СЊ РІСЃС‘ РЅР° СѓСЃС‚СЂРѕР№СЃС‚РІРѕвЂќ. | `qa-home-mobile-390.png`, source `ProtectedRoute.tsx` | Login-gate the download action, or expose an offline downloads route for guests. |
| Low-Medium | **Tab/radiogroup keyboard model**: library tabs (`role="tab"`) and reader settings radiogroups do not implement arrow-key navigation or roving tabindex; each button is tabbable. | source inspection + reader settings screenshots | Add the standard tablist/radiogroup keyboard handler or remove ARIA roles. |
| Low | **Reader footer chapter nav says only вЂњР“Р»Р°РІР°вЂќ** on both sides; the destination chapter number is only in a `title` tooltip. | `qa-reader-vertical-mobile-390.png` | Show `Р“Р»Р°РІР° N` or the chapter title visibly. |
| Low | **Brand/cover links** produce `label-content-name-mismatch`: `aria-label` omits visible text such as вЂњ18+вЂќ and timestamps. | Axe home/catalogue results | Include visible text in accessible names, or mark decorative text `aria-hidden`. |
| Low | **Offline empty state/poster fallback** and other icon-only links need a final axe pass after the new offline sheet changes. | `qa-offline-reader-settings-mobile.png` | Re-run axe in CI on all routes and themes. |

### Observed production incident (not a frontend code defect)

From roughly **03:05 to 03:21 UTC** every `/api/v1/*` request returned **502** (`/api/v1/health` included). The frontend handled it gracefully with вЂњРЎРµСЂРІРµСЂ РІСЂРµРјРµРЅРЅРѕ РЅРµРґРѕСЃС‚СѓРїРµРЅвЂќ and вЂњРџРѕРІС‚РѕСЂРёС‚СЊвЂќ on home, catalogue, sources and manga; there was no infinite spinner and no React crash. It recovered when the new build was deployed.  
**Evidence:** `docs/screenshots/qa-api-down-home.png`, `qa-api-down-catalogue.png`, `qa-api-down-manga.png`, `qa-api-down-sources.png`.  
**Recommendation:** add external health monitoring and deploy draining; do not deploy while the catalog gateway is unavailable.

---

## 3. Catalogue auto-population and filters вЂ” test details

- **Auto-population:** yes, titles appear without a manual URL import. Initial snapshot at ~06:00: **27 titles**, 24 cards on page 1, `РќР°Р№РґРµРЅРѕ: 27`. After the bulk import at ~06:30: **136**. After live-search imports during QA: **151**. This proves auto-population works.
- **Search:** local search `q=РјР°РіРёСЏ` в†’ 5 results. Search input/debounce/chips work.
- **Sort:** вЂњРџРѕ Р°Р»С„Р°РІРёС‚СѓвЂќ updates the order; вЂњРџРѕ РїРѕРїСѓР»СЏСЂРЅРѕСЃС‚Рё/СЂРµР№С‚РёРЅРіСѓ/РѕР±РЅРѕРІР»РµРЅРёСЋвЂќ are wired.
- **Pagination:** page 2 loads 24 cards, вЂњРЎС‚СЂР°РЅРёС†Р° 2 РёР· 7вЂќ, scrolls to results. Works.
- **Source/year filters:** `source=mangapoisk` в†’ 3 items, `year=2021` в†’ 4 items. Work.
- **Status filter:** UI sends `ongoing`; API data stores `РћРЅРіРѕРёРЅРі`; `ongoing` в†’ 0, `РћРЅРіРѕРёРЅРі` в†’ 32. **Broken.**
- **Genre filter:** all tested genre values (including lower-case and upper-case Russian) в†’ 0, despite two items having genre arrays. **Broken.**
- **Empty state:** when filters are active and return 0, the page says вЂњР’ РєР°С‚Р°Р»РѕРіРµ РїРѕРєР° РїСѓСЃС‚РѕвЂќ and offers вЂњРРјРїРѕСЂС‚РёСЂРѕРІР°С‚СЊ РјР°РЅРіСѓвЂќ. This is misleading because the catalogue is not empty. **Broken copy.**
- **Live search:** works (e.g. вЂњBerserkвЂќ в†’ 12 rows, вЂњVinland SagaвЂќ в†’ 3 rows) and saves results to the catalogue. Posters load once given a few seconds. The auto-import-everything behavior is a product/IA concern, not a loading bug.

---

## 4. Offline reader and settings вЂ” what works / what is broken

**Works (while the tab is open and server reachable):**
- A seeded IndexedDB manifest is read by `/offline/manga/<id>`; the offline title page shows chapters, page counts, size, downloaded-at, and an вЂњРћС‚РєСЂС‹С‚СЊ РѕС„Р»Р°Р№РЅвЂќ action.
- `/offline/read/<manga>/<chapter>` loads blob images from IndexedDB, shows page counter, slider, prev/next chapter, chapter picker and progress; progress is saved to IndexedDB.
- The new offline settings sheet exists and includes theme, reading mode (РЅРµРїСЂРµСЂС‹РІРЅС‹Р№/РїРѕСЃС‚СЂР°РЅРёС‡РЅС‹Р№), fit, gap, autoscroll, page numbers, zoom hint and shortcuts. Changing to вЂњРџРѕСЃС‚СЂР°РЅРёС‡РЅС‹Р№вЂќ works for normal 800Г—1200 pages.
- The offline chapter picker sheet works (3 chapters listed, navigation changes the URL and page content).
- The missing-title state is correct: вЂњРўР°Р№С‚Р» РЅРµ РЅР°Р№РґРµРЅ РЅР° СѓСЃС‚СЂРѕР№СЃС‚РІРµвЂќ + вЂњРљ СЃРєР°С‡Р°РЅРЅРѕРјСѓвЂќ.

**Broken / missing:**
- **Cold start offline fails** (blocker #1). The new `sw.js` is inert over HTTP.
- Offline settings switches are unlabeled for assistive tech (issue #6).
- Chapter picker is 26.8Г—24 px (issue #8).
- There is no offline banner/readiness indicator explaining the tab-only limitation.

**Evidence:** `qa-offline-manga-mobile-new.png`, `qa-offline-reader-mobile-new.png`, `qa-offline-reader-settings-mobile.png`, `qa-offline-reader-horizontal-mobile.png`, `qa-offline-chapter-picker-mobile.png`, `qa-offline-cold-start-failure.png`.

---

## 5. Responsiveness

- **1440Г—900:** no page-level horizontal overflow on home, catalogue, manga, reader, sources, 404, admin. Admin audit table scrolls internally but not by keyboard.
- **390Г—844:** no page-level horizontal overflow. However fixed overlays (APK banner) cover content; library tabs overflow; catalogue pagination loses labels; reader footer targets are small.
- **360Г—800:** no horizontal overflow on home, catalogue, manga, reader. Same fixed-banner and label issues. Screenshots: `qa-home-mobile-360-new.png`, `qa-catalogue-mobile-360-new.png`, `qa-manga-mobile-360-new.png`, `qa-reader-mobile-360-new.png`.
- **Tap targets < 44 px:** reader chapter picker (32Г—24), offline picker (26.8Г—24), APK close (32Г—32), reader page slider thumb/height (18 px track), many card title links (15вЂ“39 px high; cover link is large), admin table wrapper not focusable.
- **Clipped / hidden controls:** library вЂњРЎРєР°С‡Р°РЅРѕвЂќ tab off-screen at 390; APK banner over library/source CTAs; no page overflow.

---

## 6. Accessibility

**Axe checks run on home, catalogue, manga, reader settings, library downloads, sources, 404, admin.**

- **Critical:** unlabeled reader settings switches (`label`), mobile pagination icon-only buttons (`button-name`).
- **Serious:** mobile header login link has no accessible name (`link-name`); colour contrast 3.61вЂ“4.18:1 on metadata; cover links / brand `label-content-name-mismatch`.
- **Moderate:** admin audit scroll region not keyboard-focusable; tab/radiogroup keyboard navigation missing.
- **Passes:** form inputs have `<label for>`; login/register validation messages are associated via `aria-describedby`; buttons/links generally have 2 px accent focus outlines; the skip link works and becomes visible on focus; search input has a visible focus ring via `.searchbox:focus-within`; headings are hierarchical (one H1 per page); reader images have descriptive alts; cover links have aria-labels.
- **Contrast detail:** metadata `#85796a` on `#f1ece2` = 3.61:1; home compact metadata = 4.18:1; brand subtitle = 3.61:1 at 9.28 px. WCAG AA normal text requires 4.5:1.

**Evidence:** axe JSON was captured in `results-*.json` during QA; visual evidence in `qa-home-desktop-full.png`, `qa-catalogue-desktop-1440.png`, `qa-reader-settings-desktop.png`, `qa-catalogue-pagination-mobile-390.png`.

---

## 7. Console / network / loading states

- **Healthy pages:** 0 uncaught JS errors, 0 failed API requests. `ERR_ABORTED` appears only for cover images aborted by navigation/lazy loading; images that remain in view load correctly (`qa-home-covers-loaded-desktop.png`).
- **API outage:** 502 on all API routes for ~16 minutes; frontend showed explicit error states and retry buttons, no infinite spinner. `qa-api-down-*.png`.
- **Loading:** boot loader is removed after ReactвЂ™s first paint; no eternal spinner observed on home, catalogue, manga, reader, library, sources, login, register, 404, admin.
- **Reader:** skeletons and вЂњР—Р°РіСЂСѓР¶Р°РµРј СЃС‚СЂР°РЅРёС†С‹ РіР»Р°РІС‹вЂ¦вЂќ resolve; image failures show a retry card rather than a blank page.
- **Live search:** loading skeleton and result list work; posters can take a few seconds to load (normal network).

---

## 8. Admin

Tested `/admin` at 1440Г—900 and 390Г—844.

- Login `lilanga / Test13131` works; dashboard shows 3 server cards, 9 registry groups, 68 audit rows.
- Inventory cards, health badges, service chips, deploy/edit/health/disable actions render.
- **Data bug:** `primary-85` shows health **вЂњ9 / 8вЂќ**.
- Mobile: cards stack without page-level overflow; audit table is 720 px wide in a 332 px viewport with no keyboard-focusable wrapper; topbar hides username and вЂњРћС‚РєСЂС‹С‚СЊ СЃР°Р№С‚вЂќ, leaving only a logout icon.
- Desktop layout is polished and consistent with the admin design language; no clipping on 1440.

**Evidence:** `qa-admin-login-desktop-1440.png`, `qa-admin-dashboard-desktop-1440.png`, `qa-admin-servers-mobile-390.png`.

---

## 9. Export UI check вЂ” PASS

Verified against the **current** build (`index-BvYMjlco.js`, 03:25 UTC) by scanning rendered text and every button/link on `/`, `/catalogue`, `/manga/*`, `/library`, `/sources`, `/login`, `/register`, `/404`, `/reader/*`:

- No `CBZ`, `PDF`, `HTML`, `Р­РєСЃРїРѕСЂС‚` strings or buttons are rendered.
- The only download actions are вЂњРЎРєР°С‡Р°С‚СЊ РіР»Р°РІСѓ РЅР° СѓСЃС‚СЂРѕР№СЃС‚РІРѕвЂќ and вЂњРЎРєР°С‡Р°С‚СЊ РІСЃС‘ РЅР° СѓСЃС‚СЂРѕР№СЃС‚РІРѕвЂќ, which write pages to IndexedDB (device library), not a file-format export.
- Footer copy is corrected: вЂњСЃРєР°С‡РёРІР°Р№С‚Рµ РіР»Р°РІС‹ РЅР° СѓСЃС‚СЂРѕР№СЃС‚РІРѕ РґР»СЏ С‡С‚РµРЅРёСЏ Р±РµР· РёРЅС‚РµСЂРЅРµС‚Р°вЂќ.
- Note: `qa-export-dialog-desktop.png` is a historical screenshot from the pre-03:25 build and shows the removed CBZ/PDF/HTML dialog. Do not treat it as a current defect.

---

## 10. Comparison with MangaLib (IA / visual language)

**Home:** current build is much closer than the previous editorial hero вЂ” header, update grid, вЂњР“РѕСЂСЏС‡РёРµ РЅРѕРІРёРЅРєРёвЂќ, вЂњРЎРµР№С‡Р°СЃ С‡РёС‚Р°СЋС‚вЂќ ranking, cover/timestamp labels. It still feels lighter and less dense than MangaLib, and the stub/adult-blur cards make it look unfinished. **Close enough in direction; fix data, not the shell.**

**Header:** desktop matches the MangaLib pattern (logo left, nav/search, auth/theme right). Mobile diverges: no РСЃС‚РѕС‡РЅРёРєРё in the bottom nav, icon-only login, and the APK promo occupies the same visual zone as navigation.

**Catalogue cards:** 6-up at 1440 vs MangaLibвЂ™s ~8-up; same poster/title/meta grammar. Adult blur and 0-chapter stubs are the main visual differences.

**Manga header:** the biggest IA mismatch. MangaLib has tabbed content and a full metadata card (authors, artist, publisher, country, format, alt names, score split, etc.). Ours is a single very long page with only year/status/type/chapter count, a source picker, a description card and a 60-row chapter list. See `qa-manga-desktop-1440.png` vs `qa-ref-mangalib-manga-desktop.png`.

**Chapter list:** both show volume/chapter/title/date/pages/translator. Ours already has translator filtering and sort вЂ” good. Ours needs a tab/compact container to avoid a 5,320 px page; MangaLib separates chapters from the title overview.

**Reader chrome/settings:** settings sheet is structurally close to MangaLib (mode, fit, gap, autoscroll, display, theme, shortcuts). Our persistent chrome is more cluttered, but functional. The horizontal webtoon failure and unlabeled switches are the blocking gaps. Reference: `qa-ref-mangalib-reader-desktop.png`, `qa-ref-mangalib-reader-mobile.png`.

---

## 11. Recommended fix order

1. **HTTPS + verified service worker cold offline start** (blocker #1). Add an end-to-end test: download в†’ close tab в†’ go offline в†’ reopen `/offline/read/...`.
2. **Horizontal/webtoon reading** (blocker #2): segment tall pages or force vertical; add a regression test using a 690Г—10000 page.
3. **Catalogue filter contract** (high #3): map status values and normalize genres; fix the filter-empty copy; add API/UI tests.
4. **Catalogue data quality** (high #4): hide 0-chapter entries from curated/home surfaces; hydrate metadata; dedupe; make live-search import explicit.
5. **Mobile APK banner placement** (high #5) and tap targets (medium #8).
6. **Accessibility pass** (high #6, medium-high #7): reader switch labels, mobile pagination labels, login link name, contrast, tab keyboard model.
7. **Manga metadata/IA** (medium #10) and library tab affordance/guest downloads (medium #9).
8. **Admin health count and mobile table accessibility** (medium).

---

## 12. Verdict

**BLOCK.** The current build is visually coherent and much closer to MangaLib than the previous one, and it passes the export-removal and offline-settings checks. But a public release would ship with:

- a broken cold-start offline promise on the actual HTTP production URL,
- an unusable horizontal reader for the dominant webtoon page shape,
- dead genre/status filters,
- a catalogue where the top item has zero chapters and the majority of sampled titles lack genres/descriptions,
- a mobile promo overlay that covers primary actions,
- and critical accessibility gaps in reader settings and mobile pagination.

Fix the two blockers, the filter contract and catalogue hydration, then re-run this QA pass. The accessibility and mobile-overlay items can be fixed in the same release cycle.

---

## Appendix вЂ” evidence files

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
