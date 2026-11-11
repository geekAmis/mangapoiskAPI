# Android client — MangaPoisk Reborn

Native Kotlin/Jetpack Compose client for the public `/api/v1` contract in
[`API.md`](API.md). This document covers architecture, screens, build/run,
API configuration, verification results and known limitations.

## Status

The project is complete and compile-ready. On the validation machine it builds
successfully:

- `assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`
- `assembleRelease` (R8) → `app/build/outputs/apk/release/app-release-unsigned.apk`

The app was installed and smoke-tested on a connected TECNO KL6
(1080×2460, Android) through `adb reverse tcp:8000 tcp:8000`: home, catalogue
filtering, detail, reader pager/tap zones/resume, reader settings,
sources and settings were exercised. There are no automated
unit/instrumentation tests yet.

## Stack and versions

| Component | Version |
|---|---|
| Kotlin | 2.0.21 |
| Android Gradle Plugin | 8.6.1 |
| Gradle wrapper | 8.9 |
| compileSdk / targetSdk | 34 / 34 |
| minSdk | 26 (Android 8.0) |
| Compose | BOM 2024.06.00 (Material 3 1.2.1) |
| Navigation Compose | 2.7.7 |
| Retrofit / OkHttp | 2.11.0 / 4.12.0 |
| kotlinx.serialization | 1.7.3 |
| Coil | 2.7.0 |
| Room | 2.6.1 (KSP) |
| DataStore Preferences | 1.1.1 |
| WorkManager | 2.9.1 |
| security-crypto | 1.1.0-alpha06 |

`compileSdk` is 34 rather than 35 because the build environment only had the
Android 34 platform installed. The required environment instruction was to use
34. To move to 35 later: install `platforms;android-35`, raise
`compileSdk`/`targetSdk`, and use a dependency set built against 35. The current
pins are deliberately chosen to stay compatible with compileSdk 34.

## Architecture

```
Compose screens
    │  collectAsStateWithLifecycle / viewModel(factory = …)
ViewModels (StateFlow, UiState, events, debounced progress)
    │  suspend calls, Result<T>, AppError
Repositories
    ├── CatalogRepository ── Retrofit MangaApi
    ├── AuthRepository ───── Retrofit + SessionManager
    ├── LibraryRepository ── Retrofit + Room (bookmarks/progress)
    └── DownloadRepository ─ WorkManager + Room + OkHttp
Data
    ├── Room: bookmarks, reading_progress, downloads
    ├── DataStore: base URL, theme, reader defaults
    ├── EncryptedSharedPreferences: access/refresh tokens, cached user
    └── Coil: gateway image URLs (no auth required)
```

Dependency injection is manual through [`AppContainer`](../apps/android/app/src/main/java/ru/mangapoisk/reborn/di/AppContainer.kt).
There is no Hilt, no service locator, and no reflection beyond Room/WorkManager.
Each screen creates its ViewModel with an explicit `viewModelFactory`; the
container is provided through `LocalAppContainer` only for UI-level actions
such as clearing the Coil cache.

### Package map

| Path | Responsibility |
|---|---|
| `data/local` | Room database/DAOs/entities; `SettingsStore`, encrypted `TokenStore`, `SessionManager` |
| `data/remote` | `MangaApi`, DTOs, lenient serializers, base-URL/auth interceptors, 401 authenticator, `AppError` mapping |
| `data/repo` | catalogue, auth, library/bookmarks/progress, downloads |
| `download` | `DownloadWorker` (WorkManager) |
| `ui/theme` | six palettes, typography, edge-to-edge system bar styling |
| `ui/components` | poster/cards, skeletons, empty/error states, section headers |
| `ui/<feature>` | home, catalog, detail, reader, library, settings, auth |
| `ui/navigation` | route table, adaptive bottom bar / navigation rail |
| `di` | `AppContainer` |

### State and errors

Each ViewModel exposes an immutable `UiState` in a `StateFlow`, plus one-shot
events (`SharedFlow`) for snackbars. Network calls go through `apiCall`, which
maps `HttpException`, `IOException`, timeouts and serialization failures to an
`AppError` enum (`NETWORK`, `TIMEOUT`, `UNAUTHORIZED`, `NOT_FOUND`,
`RATE_LIMIT`, `SERVER`, `INVALID_RESPONSE`, `UNKNOWN`). UI maps these to Russian
strings; no raw server errors are shown.

### Library persistence and sync

- Bookmarks are written to Room first, so they work offline and for guests.
  When signed in they are mirrored to `POST/DELETE /library/bookmarks` on a
  best-effort basis.
- Reading progress is always written locally; remote writes happen when signed
  in. Reader writes are debounced by 800 ms and flushed on `ON_STOP` and on
  screen disposal.
- `LibraryRepository.syncRemote()` pulls remote bookmarks and continue-reading
  entries and upserts them into Room. Local-only entries are preserved.
- Library JSON is parsed defensively (`LibraryJsonParser`) because
  `docs/API.md` only sketches the envelope (“list bookmarks with embedded
  manga”, “continue-reading list”). The parser accepts arrays and `{items:[]}`
  / `{bookmarks:[]}` / `{progress:[]}` envelopes, plus flat or nested manga
  fields. **Verify against the real gateway response before release.**

## Screens

Navigation is single-activity, Compose Navigation, with a bottom bar on phones
and a navigation rail at `>= 720dp`. The reader, detail and auth screens hide
navigation chrome. The navigation host stays in a stable composition slot so
hiding the bar does not reset destination state.

### Home

- Editorial hero in the approved order: **theme artwork as a separate banner**
  (240 dp on phones) and a solid `surface` copy panel below it; on wide layouts
  copy and artwork are side-by-side. No headline or body copy sits on artwork.
- Hero content: Russian-first title, alternative title, rating/year/status/
  chapters, clamped description, genre pills, “Читать” and bookmark actions.
  “Читать” resolves the featured title's oldest chapter and opens the reader
  directly (falling back to the detail screen if chapters are unavailable).
- Continue-reading row from Room progress.
- Popular as a 2-column phone grid (3–4 columns on wider screens) and
  “Обновления” as a divided list; both capped at six items with “Все”.
- Source strip from `/sources` with a link to the full Sources screen.
- Refresh action in the top bar; partial-failure banner; legal note.

### Catalogue / search

- Debounced query (350 ms), source filter chips, sort menu
  (`popular`, `rating`, `updated`, `title`).
- Search uses `/manga/search` when the query is non-empty, otherwise `/manga`.
- `GridCells.Adaptive(148dp)` (2 columns on a 360 dp phone, more on tablets).
- Infinite scroll with duplicate-ID filtering, loading footer, retry footer,
  skeleton grid, empty/reset-filters state.

### Manga detail

- Poster, title/alternative title, rating, year, status, content type, source,
  chapter count, genre chips and expandable description (HTML stripped).
- Bookmark action in the top bar and in the action row; works as a guest
  (local) and mirrors to the account when signed in.
- Primary “Читать”/“Продолжить” action resumes the saved chapter/page;
  “С начала” opens the oldest chapter.
- Chapter list from `MangaDetailOut.chapters`, with page count, date,
  per-chapter download action/status and current-chapter progress.
- Offline-export availability note (CBZ/PDF/HTML via web/API); starting an
  export job from Android is not implemented.

### Reader

- Reader shell is always `#050506`, independent of the six themes. Theme colours
  only affect the 2 dp progress line, active controls, progress and the
  settings sheet; there is no theme artwork in reader content or chrome.
- Vertical continuous mode is the default; horizontal paged mode is a toggle.
  Both persist in DataStore. Vertical content is capped at 780 dp wide.
- Tap zones are 30 % / 40 % / 30 %: in horizontal mode left/right page, centre
  toggles chrome; in vertical mode centre toggles chrome and side taps do
  nothing. Swipe paging is always available in horizontal mode.
- Inline resume banner («Вы остановились на странице N») with “Продолжить” and
  “С начала”; progress is not overwritten while the prompt is pending.
- Page counter, 2 dp progress line under the top bar, previous/next chapter
  buttons, bookmark toggle, and `prev_chapter_id`/`next_chapter_id` from
  `ChapterDetailOut`. Chapter switching happens inside the reader screen.
- Progress sync: page changes debounce 800 ms, write Room immediately, and send
  `PUT /library/progress` (1-based page) when authenticated. Flush on stop and
  dispose.
- Auto-scroll is off by default, lives in the settings sheet with a speed
  slider (10–100, persisted), pauses when the sheet opens or the reader is
  tapped, and stops at the chapter end.
- Settings sheet: mode, fit width/height/screen, page gap 0–32 dp, theme
  switcher, auto-scroll + speed, keep-screen-on.
- Keep-screen-on via `FLAG_KEEP_SCREEN_ON`, persisted as a reader default.
- Immersive fullscreen: system bars are hidden with
  `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE` and restored on exit.
- Horizontal mode: double-tap to zoom (2.5×), pinch/pan while zoomed, tap to
  reset. Next two pages are preloaded through Coil.
- Downloaded chapters are preferred from local files; if the API is
  unreachable, the reader falls back to the local chapter completely.
- If a chapter is not downloaded and the API fails, a retry/back error screen is
  shown.

**Limitation:** pinch zoom is available in horizontal paged mode. Vertical
continuous mode intentionally does not intercept gestures so normal scrolling
and auto-scroll stay smooth. The top bar uses bookmark/mode/settings because
immersive fullscreen is always active; a separate fullscreen toggle was not
added.

### Library

Four tabs, aligned with the approved information architecture:

- **Продолжить** — continue-reading cards with chapter/page/progress and resume.
- **Закладки** — adaptive grid of local/bookmarked manga.
- **История** — reading history cards with progress, resume and remove actions.
- **Загрузки** — downloaded chapters with queued/running/done/failed status,
  progress, retry, cancel/delete and offline-open.

Empty states link to the catalogue.

### Sources

- Cards for every `/sources` entry, including disabled ones.
- Name, language, availability badge, capabilities (search/catalog/latest/
  chapters/pages) and a cookies warning when applicable.
- A legal/attribution card at the top, no raw upstream URLs.
- Reachable from Home → «Источники → Все» and from Settings → «Источники».

### Profile / settings

- Guest/login/register/logout; account card shows display name and email.
- Six themes with the exact approved palettes and names: `midnight` (Полночь),
  `noir` (Нуар), `oni` (Они), `crimson` (**Багровый**), `sunset` (Закат),
  `paper` (Бумага). Each option shows a 2×3 theme-art thumbnail and palette
  dots; selection uses border + check, not colour alone. Theme changes apply
  immediately and persist in DataStore.
- First visit follows the system appearance: light → `paper`, dark → `midnight`.
- Configurable API base URL with validation; changing it while signed in logs
  out. Reset-to-default action. Release builds reject `http://` URLs.
- Reader defaults: vertical/horizontal, page fit, auto-scroll speed,
  keep-screen-on, page gap.
- Clear Coil image cache, all downloads, and reading history (with
  confirmations). History clearing also removes remote progress entries
  best-effort.
- Version, API URL, Sources entry and legal/about text.

### Auth

- Phone layout is a solid surface form card on the theme background; no full
  screen theme image behind fields. At ≥ 720 dp the form column is paired with
  a separate theme-art panel and a solid quote card, following the art rule.
- Login/register with client validation, password visibility, loading/error
  states, and backend error mapping. Segmented login/register control and
  “Продолжить без аккаунта” exit.
- Tokens are stored in EncryptedSharedPreferences backed by an Android Keystore
  AES-256-GCM master key. If the encrypted store cannot be created, a logged
  fallback to private preferences is used so the app remains usable (rare on
  API 26+).
- OkHttp `Authenticator` refreshes once on 401 using a separate no-auth client,
  persists the rotated token pair, and replays the request. A failed refresh
  clears the session and surfaces “unauthorized”.
- Logout posts the refresh token to `/auth/logout` best-effort, then clears
  local tokens; local library/download data is preserved.

## API mapping

| App use | Endpoint |
|---|---|
| Source chips/filter | `GET /sources` |
| Home popular/latest, browse catalogue | `GET /manga?sort=&page=&limit=` |
| Search | `GET /manga/search?q=&source=&page=&limit=` |
| Manga detail + chapters | `GET /manga/{id}` |
| Reader chapter + pages | `GET /chapters/{id}` |
| Page images | Page `url` values from `ChapterDetailOut`, resolved and loaded by Coil |
| Register/login/refresh/logout/me | `/auth/*` |
| Bookmarks | `GET/POST/DELETE /library/bookmarks` |
| Continue reading | `GET /library/progress`; `PUT /library/progress` |
| History reset | `DELETE /library/progress/{manga_id}` |
| Exports | Not started; informational note only |

Pages are requested exactly as returned (1-based numbers); the app only turns
relative gateway paths into absolute URLs. It never rewrites image URLs to an
upstream host. `GET /health`, `/manga/import` and per-manga chapter pagination
are unused.

## Networking and URLs

- Retrofit has a placeholder base (`http://localhost/`). `BaseUrlInterceptor`
  rewrites scheme, host, port and path to the configured `AppSettings.baseUrl`
  on every request, so changing servers needs no restart.
- **Debug default: `http://127.0.0.1:8000/api/v1/`**, intended for
  `adb reverse tcp:8000 tcp:8000` on a physical device or emulator.
- Emulator alternative: `http://10.0.2.2:8000/api/v1/` (host loopback alias).
- Physical device on the same LAN: `http://<host-lan-ip>:8000/api/v1/`.
- Production/release: HTTPS only. The release build keeps the emulator default
  as a build-time fallback and must be pointed at the real gateway in Settings.
- `MediaUrlResolver` converts relative poster/page paths to absolute gateway
  URLs. Absolute URLs are left untouched.
- Coil has a dedicated `ImageLoader` with a browser-like User-Agent and a
  MangaLib `Referer`; this is required because `cover.imglib.info`
  (DDoS-Guard) returns 403 to OkHttp's default User-Agent. Requests to the
  gateway are unaffected.
- Debug cleartext is enabled in `app/src/debug/res/xml/network_security_config.xml`.
  The main/release config sets `cleartextTrafficPermitted="false"`.
- Logging is BASIC and debug-only; tokens and bodies are not logged.

## Themes and responsive behaviour

| Theme | Palette / mood | Headings |
|---|---|---|
| `midnight` | navy, ice blue, cyan; rainy neon city | sans |
| `noir` | black, bone white, silver; gothic | serif |
| `oni` | charcoal, blood red, warm paper | sans |
| `crimson` | black, crimson, pale grey | sans |
| `sunset` | plum, coral, amber, rose | sans |
| `paper` | paper white, ink, vermilion (light scheme) | serif |

The palettes above are the exact tokens from `docs/DESIGN_SYSTEM.md`
(`bg`, `surface`, `surface-2`, `text`, `muted`, `border`, `border-strong`,
`accent`, `accent-text`, `accent-2`, `on-accent`, `danger`, `success`).
Material You dynamic colour is not enabled. `noir`/`paper` use
`FontFamily.Serif` for display/headline/title-large; card titles stay sans.

All six optimised WebP backgrounds are bundled and obey the handoff art rule:
- home hero: art banner/panel, copy on solid surface, never text over art;
- auth: art only in the separate wide-layout side panel, hidden on phones;
- theme switcher: small preview thumbnails.
No art is used behind lists, forms, reader content or reader chrome.

- `< 720dp`: bottom navigation; adaptive catalogue/library grids; hero art
  240 dp banner above a solid copy card; reader tuned for 360 dp.
- `>= 720dp`: navigation rail (native tablet adaptation of the handoff top nav);
  hero splits 56/44 with masked art; content stays max-width constrained;
  detail/settings are centered; reader pages are capped at 780 dp.
- Edge-to-edge with per-screen status/navigation insets; `paper` switches system
  bar icon appearance to dark.
- Touch targets follow Material defaults; icon buttons have Russian content
  descriptions. Decorative imagery uses `contentDescription = null`.
- All user-visible strings are in `res/values/strings.xml`. No external fonts
  are fetched.

## Build and run

### Android Studio

Open `apps/android` (not the repository root), allow Gradle sync, select an
API 26+ emulator/device, and run `app`.

### Command line (validated environment)

```powershell
cd apps/android
$env:JAVA_HOME = "D:\tools\jdk-17\jdk-17.0.20.1+1"
$env:ANDROID_HOME = "D:\Android\sdk"
$env:ANDROID_SDK_ROOT = "D:\Android\sdk"
.\gradlew.bat assembleDebug
```

Generic:

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
./gradlew assembleDebug
```

`local.properties` is machine-specific and ignored by git. The checked-in
`gradle.properties` sets `android.overridePathCheck=true` because this
workspace path contains Cyrillic characters; AGP otherwise refuses to configure
on Windows. It is harmless elsewhere.

### Verification performed

| Check | Result |
|---|---|
| `assembleDebug` | **SUCCESS** — `app/build/outputs/apk/debug/app-debug.apk` |
| `assembleRelease` (R8/resources shrink) | **SUCCESS** — `app/build/outputs/apk/release/app-release-unsigned.apk` |
| Kotlin compile | Success (Kotlin 2.0.21, JVM 17) |
| Resource/manifest validation | Success (AAPT2 via assemble) |
| Lint | `lintDebug` passes with no errors after the `NewApi` style fix |
| Device run | TECNO KL6, 1080×2460, via `adb reverse`; smoke-tested Home, Catalog, Detail, Reader, Sources, Settings, Auth |
| Poster rendering | Verified on device after adding the browser UA/Referer to Coil: MangaLib `cover.imglib.info` covers now render |
| Reader navigation | Verified on device: Home hero «Читать» and Detail «Читать» both open the reader |
| Unit/instrumentation tests | None added |

R8 initially reported missing compile-time Tink/ErrorProne annotations; the
release build was fixed with a `-dontwarn com.google.errorprone.annotations.**`
rule and then succeeded.

## Known limitations

1. **compileSdk 34**, not 35, due to the validation SDK. See above.
2. **Reader zoom** works in horizontal paged mode; vertical continuous mode
   trades pinch-zoom for uninterrupted scroll/auto-scroll.
3. **Export jobs** are not started from Android; the detail screen only notes
   that CBZ/PDF/HTML export is available through web/API.
4. **Remote library JSON shape** is not fully specified in `docs/API.md`; the
   tolerant parser needs verification against the live gateway. Remote bookmark
   deletions made on another device are not propagated (sync only upserts).
5. **Theme and reader defaults are local-only.** They are not written to
   `/library/settings`, although that endpoint exists. Theme selection in the
   reader updates the app palette immediately while the reader shell stays dark.
6. **Downloads** use WorkManager without a foreground notification. Large
   chapters may be deferred by the OS; there is no notification/progress UI
   outside the app. Files are app-private and removed on uninstall.
7. **No import UI** for `POST /manga/import`; browsing is limited to the
   catalogue/search results returned by the gateway.
8. **Adult posters are not blurred**; an `18+` badge is shown instead. The
   `blur_adult_posters` server setting is not consumed.
9. **Chapter list pagination** beyond `MangaDetailOut.chapters` (capped at 500
   by the API) is not implemented.
10. **Release APK is unsigned.** Add signing config for distribution.
11. **No offline catalogue/home.** Offline support covers downloaded chapters,
    local bookmarks, history and settings.
12. **No localization beyond Russian.** All strings are externalized, so adding
    locales is a `values-xx` task.
13. `security-crypto` is pinned to `1.1.0-alpha06` for compileSdk-34
    compatibility; consider the stable release when moving to API 35.
14. **Reader specifics:** per-page number labels and a separate fullscreen
    button were not added; the top bar keeps bookmark/mode/settings and the
    reader is immersive by default. The top progress line and page counter
    cover the page-number need.
15. **Theme switcher** uses theme-art thumbnails + palette dots rather than the
    web 16:9 cards with mood copy. It remains a 2×3 grid with border + check.
16. **Page image availability depends on the gateway/media service.** During the
    smoke test the API returned chapter metadata, but the current media endpoint
    did not deliver page bytes for some chapters, so Coil showed the placeholder.
    The Android reader handles that state without crashing; verify with a
    healthy media service before assessing reader artwork.

## Manual verification checklist

1. Start the gateway on the host and confirm
   `http://localhost:8000/api/v1/health`.
2. Phone: `adb reverse tcp:8000 tcp:8000`, keep the debug
   `127.0.0.1` default; open Home and confirm API data and posters.
   Emulator fallback: set `http://10.0.2.2:8000/api/v1/` in Settings.
3. Search with query/source/sort, scroll to trigger page 2+, open a manga.
4. Reader: vertical scroll, horizontal pager, tap zones 30/40/30, chapter
   prev/next, page counter, resume banner, settings theme/gap, auto-scroll,
   keep-screen-on, immersive exit, progress after relaunch.
5. Register/login, verify tokens survive app restart, then expire/refresh an
   access token and confirm a single 401 retry.
6. Add/remove bookmark, read a chapter, check Library → Продолжить /
   Закладки / История, then check the same account on the web.
7. Download a chapter, enable airplane mode, reopen it from Library → Загрузки.
8. Switch all six themes (especially `paper` light + serif and `noir` serif),
   verify art placement, test tablet width (rail + grid columns), rotate.
9. Open Sources from Home → Все and Settings; check disabled sources,
   capabilities and legal note.
10. Change API URL and confirm logout; test invalid URL and HTTP in release.
11. Compare gateway library responses with `LibraryJsonParser` assumptions.
