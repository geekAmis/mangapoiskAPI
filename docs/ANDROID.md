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
- **Release default (1.3.1+): `https://85.192.37.58.nip.io/api/v1/`** (HTTPS,
  standard port 443).
- **Legacy 1.3.0:** `https://85.192.37.58.nip.io:8443/api/v1/` remains
  API-compatible until the 1.3.1 APK is installed; do not use it in new builds.
- **Current demo:** `https://85.192.37.58.nip.io/api/v1/` (HTTPS; the
  release build can use this URL or your own HTTPS domain).
- Emulator alternative: `http://10.0.2.2:8000/api/v1/` (host loopback alias).
- Physical device on the same LAN: `http://<host-lan-ip>:8000/api/v1/`.
- Production/release: HTTPS only. The release build defaults to the HTTPS
  gateway; a custom server must also be HTTPS.
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
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.21.9-hotspot" # adjust to your JDK 17
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

### Capacitor APK (`ru.mangapoisk.reborn`)

The QA-blocked 1.0 APK was the Node/Capacitor build, not the Kotlin client. It
was built with `server.androidScheme: "http"`, cleartext enabled,
`android.allowMixedContent: true` and an HTTP API base. The production
Capacitor build now uses:

| Setting | Required value |
|---|---|
| API base | `https://85.192.37.58.nip.io:8443/api/v1` |
| `server.androidScheme` | `https` |
| `server.cleartext` | `false` |
| `android.allowMixedContent` | `false` (or omitted) |
| `android:usesCleartextTraffic` | `false` |
| Network security config | `cleartextTrafficPermitted="false"` |

These live in `apps/mobile/capacitor.config.json`,
`apps/mobile/android/app/src/main/AndroidManifest.xml` and
`apps/mobile/android/app/src/main/res/xml/network_security_config.xml`.

#### Build commands (Windows PowerShell)

```powershell
cd apps/mobile
npm install
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.21.9-hotspot" # adjust to your JDK 17
$env:ANDROID_HOME = "D:\Android\sdk"
$env:ANDROID_SDK_ROOT = "D:\Android\sdk"

# Optional: override the HTTPS production API base.
# The default is already https://85.192.37.58.nip.io:8443/api/v1
# $env:CAPACITOR_API_BASE = "https://85.192.37.58.nip.io:8443/api/v1"

npm run sync
cd android
.\gradlew.bat assembleDebug
.\gradlew.bat assembleRelease
```

Linux/macOS uses `./gradlew assembleDebug` / `./gradlew assembleRelease`.

Outputs:

- `apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk` — debug-signed,
  installable with `adb install -r`; still uses the HTTPS production API unless
  `CAPACITOR_API_BASE` was overridden for local development.
- `apps/mobile/android/app/build/outputs/apk/release/app-release-unsigned.apk`
  — release, **unsigned** because the repository has no signing config. Sign it
  with the production key before distribution; see
  [Release signing](#release-signing-production).

`apps/mobile/scripts/build-www.mjs` bakes the API base into the JS bundle and
refuses arbitrary plain-HTTP URLs. Only `https://` and local development hosts
(`localhost`, `127.0.0.1`, `10.0.2.2`) are accepted, so a release build cannot
silently fall back to HTTP. The Android shell still enforces HTTPS in every
build type, so localhost HTTP is only useful for the browser web build.

#### Release signing (production)

The release APK is signed outside Gradle with the production keystore; the
repository intentionally contains no signing config and no keystore.

Current 1.1.0 certificate:

| Field | Value |
|---|---|
| Alias | `mangapoisk` |
| Key | RSA 4096, SHA-384 self-signed |
| Validity | 2026-11-13 to 2054-03-31 (10 000 days) |
| Certificate SHA-256 | `E8:B8:C8:12:EF:40:2E:3E:54:ED:29:32:B7:00:6E:96:E9:8B:30:AE:E5:FD:27:E4:4B:7B:B2:A4:59:E2:BE:74` |

The signing key is immutable for the app's lifetime: Android rejects an update
signed by a different key. Back it up and never rotate it unless the package is
renamed or all users are told to uninstall.

**Where the key lives (production only)**

- `/opt/mangapoisk-reborn/env/android/mangapoisk-release.jks` - PKCS#12
  keystore, `root:root`, directory mode `700`, file mode `600`.
- `/opt/mangapoisk-reborn/env/android/keystore.properties` - `storePassword`,
  `keyPassword`, `keyAlias` and the keystore filename; `root:root`, mode `600`.
- The encrypted off-host restic repository includes this directory because
  `/usr/local/sbin/mangapoisk-backup.sh` copies the whole
  `/opt/mangapoisk-reborn/env` tree into the snapshot. Repository:
  `sftp:mpbackup-jump:/srv/mangapoisk-backups/restic`; password file:
  `/root/.restic-password`.
- A temporary copy on the signing workstation is acceptable for one signing
  session; delete it afterwards. Never put the keystore,
  `keystore.properties` or the password in git, issue comments, chat, CI logs
  or shell history.

**Generate the keystore (one-time; already done for 1.1.0)**

Run on production as root. `keytool` is part of the JDK 17 installation.

```bash
KS_DIR=/opt/mangapoisk-reborn/env/android
install -d -m 700 -o root -g root "$KS_DIR"

read -r -s -p "Keystore password: " KS_PASS; echo
keytool -genkeypair -v \
  -keystore "$KS_DIR/mangapoisk-release.jks" \
  -storetype PKCS12 \
  -alias mangapoisk \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -dname "CN=MangaPoisk Reborn, OU=Android, O=MangaPoisk, L=Moscow, ST=Moscow, C=RU" \
  -storepass:env KS_PASS

umask 077
printf 'storePassword=%s\nkeyPassword=%s\nkeyAlias=mangapoisk\nkeystore=mangapoisk-release.jks\n' \
  "$KS_PASS" "$KS_PASS" > "$KS_DIR/keystore.properties"
unset KS_PASS
chown root:root "$KS_DIR"/*
chmod 600 "$KS_DIR"/*
```

Use a random password of at least 32 bytes, for example
`openssl rand -hex 32`. PKCS#12 uses the same password for the store and the
key. Keep `keystore.properties` LF-only so it can be sourced by bash.

**Sign a release APK**

Build the unsigned release first (`assembleRelease` above), then:

```bash
cd apps/mobile/android/app/build/outputs/apk/release
KS_DIR=/opt/mangapoisk-reborn/env/android
set -a; . "$KS_DIR/keystore.properties"; set +a

# AGP already aligns release APKs; confirm, and align explicitly if it fails.
zipalign -c -P 16 -v 4 app-release-unsigned.apk

apksigner sign \
  --ks "$KS_DIR/mangapoisk-release.jks" \
  --ks-type PKCS12 \
  --ks-key-alias "$keyAlias" \
  --ks-pass env:storePassword \
  --key-pass env:keyPassword \
  --v1-signing-enabled true \
  --v2-signing-enabled true \
  --v3-signing-enabled true \
  --out mangapoisk-reborn-1.1.0-release.apk \
  app-release-unsigned.apk

unset storePassword keyPassword
```

If `zipalign -c` fails, run
`zipalign -P 16 -f 4 app-release-unsigned.apk app-release-aligned.apk` and sign
the aligned file. `apksigner` and `zipalign` are in
`$ANDROID_HOME/build-tools/35.0.0/` (or `C:\Android\Sdk\build-tools\35.0.0\` on
Windows).

On Windows PowerShell the same steps are:

```powershell
$KS_DIR = "C:\path\to\android-signing"   # temporary local copy only
$props = @{}
Get-Content "$KS_DIR\keystore.properties" | Where-Object { $_ -match '^[A-Za-z]+=' } |
  ForEach-Object { $k,$v = $_ -split '=',2; $props[$k]=$v }
$env:storePassword = $props['storePassword']
$env:keyPassword = $props['keyPassword']
apksigner sign --ks "$KS_DIR\mangapoisk-release.jks" --ks-type PKCS12 `
  --ks-key-alias mangapoisk --ks-pass env:storePassword --key-pass env:keyPassword `
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true `
  --out mangapoisk-reborn-1.1.0-release.apk app-release-unsigned.apk
Remove-Item Env:storePassword, Env:keyPassword
```

**Verify the signature**

```bash
apksigner verify --verbose --print-certs mangapoisk-reborn-1.1.0-release.apk
sha256sum mangapoisk-reborn-1.1.0-release.apk
```

Expected for 1.1.0:

- `Verifies`
- `Verified using v1 scheme (JAR signing): true`
- `Verified using v2 scheme (APK Signature Scheme v2): true`
- `Verified using v3 scheme (APK Signature Scheme v3): true`
- `v3.1` / `v4` may be `false`; they are not required for this build.
- certificate SHA-256
  `e8b8c812ef402e3e54ed2932b7006e96e98b30aee5fd27e44b7bb2a459e2be74`
  and `RSA 4096`.
- APK SHA-256
  `b2d8e760ff779369dbfd6e5fb4ca1730c23976afb966c30f4361b469a5e33ff8`
  (7 355 329 bytes).

`apksigner` may warn that `META-INF/*.version` entries are not protected by the
v1 JAR signature. This is expected for AndroidX metadata; v2/v3 protect the
whole APK.

Upload the signed file to the **draft** GitHub release as
`mangapoisk-reborn.apk`. Do not publish the release until the on-device
checklist below passes.

**Recover the key from restic**

The backup script stages `env/` at `/var/tmp/mangapoisk-backup/config/env`, so
snapshot paths look like
`/var/tmp/mangapoisk-backup/config/env/android/mangapoisk-release.jks`.

```bash
RESTIC="restic -r sftp:mpbackup-jump:/srv/mangapoisk-backups/restic --password-file /root/.restic-password"

$RESTIC snapshots --tag mangapoisk --latest 5
$RESTIC ls latest | grep 'config/env/android'

mkdir -p /var/tmp/android-key-restore
$RESTIC restore latest --target /var/tmp/android-key-restore \
  --include '/var/tmp/mangapoisk-backup/config/env/android'

install -d -m 700 -o root -g root /opt/mangapoisk-reborn/env/android
install -m 600 -o root -g root \
  /var/tmp/android-key-restore/var/tmp/mangapoisk-backup/config/env/android/* \
  /opt/mangapoisk-reborn/env/android/
```

For a single file, use
`$RESTIC dump latest /var/tmp/mangapoisk-backup/config/env/android/mangapoisk-release.jks > mangapoisk-release.jks`.
After restoring, compare the certificate SHA-256 with the value above before
signing. If the keystore is lost and no snapshot exists, existing installs
cannot be updated in place; the package name must change or users must
uninstall.

#### Static verification (no device required)

Run these checks against the signed release APK (the unsigned build has the same
assets):

```bash
APK=mangapoisk-reborn-1.1.0-release.apk
sha256sum "$APK"
apksigner verify --verbose --print-certs "$APK"

rm -rf /tmp/apk-check && mkdir -p /tmp/apk-check
unzip -q "$APK" 'assets/public/*' 'assets/capacitor.config.json' -d /tmp/apk-check
grep -R -l 'http://85.192.37.58:8088' /tmp/apk-check || echo 'HTTP_8088_HITS: none'
grep -R -l 'https://85.192.37.58.nip.io:8443' /tmp/apk-check
cat /tmp/apk-check/assets/capacitor.config.json

aapt2 dump xmltree --file AndroidManifest.xml "$APK" |
  grep -E 'usesCleartextTraffic|versionName|versionCode|package='
```

Expected: the only API base is
`https://85.192.37.58.nip.io:8443/api/v1`; `http://85.192.37.58:8088` is absent;
the packaged config has `"androidScheme": "https"`, `"cleartext": false` and
`"allowMixedContent": false`; the manifest has
`usesCleartextTraffic=false`, `versionName="1.1.0"`, `versionCode=2` and
`package="ru.mangapoisk.reborn"`. On Windows, use `tar -xf` instead of `unzip`.

#### On-device QA checklist (TECNO KL6, Android 14)

Do not publish the draft release until every item passes. Record results in
issue #35.

1. **Preconditions.** Phone unlocked, USB debugging enabled, `adb devices`
   shows the device as `device` (not `unauthorized`). The 1.0 build on the QA
   phone is debug-signed, so the production-signed APK cannot install over it.
   Uninstall once (this wipes app data on the QA phone):

   ```bash
   adb uninstall ru.mangapoisk.reborn
   ```

2. **Install the signed release.**

   ```bash
   adb install -r mangapoisk-reborn-1.1.0-release.apk
   ```

   Expected `Success`. `INSTALL_FAILED_UPDATE_INCOMPATIBLE` means an old
   differently-signed build is still installed; uninstall and retry.

3. **Package metadata.**

   ```bash
   adb shell dumpsys package ru.mangapoisk.reborn |
     grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime|flags='
   ```

   Expected `versionName=1.1.0`, `versionCode=2`, and **no** `DEBUGGABLE` in
   `flags=`.

4. **Installed binary signature.** Pull the installed base APK and verify it,
   not just the file you uploaded:

   ```bash
   APK_PATH=$(adb shell pm path ru.mangapoisk.reborn | sed 's/package://' | tr -d '\r')
   adb pull "$APK_PATH" /tmp/installed-base.apk
   apksigner verify --print-certs /tmp/installed-base.apk
   sha256sum /tmp/installed-base.apk
   ```

   Expected certificate SHA-256
   `e8b8c812ef402e3e54ed2932b7006e96e98b30aee5fd27e44b7bb2a459e2be74`;
   record the installed APK SHA-256 (it should equal
   `b2d8e760ff779369dbfd6e5fb4ca1730c23976afb966c30f4361b469a5e33ff8`).

5. **Launch with logcat and check the API host.**

   ```bash
   adb logcat -c
   adb shell am start -n ru.mangapoisk.reborn/.MainActivity
   sleep 8
   adb logcat -d > /tmp/mangapoisk-qa.log
   grep -E '85\.192\.37\.58|CapacitorHttp|chromium' /tmp/mangapoisk-qa.log
   ```

   Expected: requests go to `https://85.192.37.58.nip.io:8443/api/v1`; no
   request contains `85.192.37.58:8088`; no `CleartextNotPermitted` or
   `ERR_CLEARTEXT_NOT_PERMITTED` lines.

6. **WebView origin.** The Capacitor WebView origin must be
   `https://localhost`, not `http://localhost`. Check the Chromium lines in the
   same logcat, or open `chrome://inspect` on the workstation and inspect the
   `ru.mangapoisk.reborn` WebView.

7. **Smoke matrix.** Mark each item pass/fail in #35:
   - cold start: home renders (hero, continue reading, popular, sources strip);
   - catalogue: pagination, source filter, sort;
   - search: query returns results, open a manga from results;
   - manga detail: chapter list, bookmark toggle;
   - reader: open a chapter, next/previous chapter, vertical and horizontal
     modes, page progress persists after back/reopen;
   - library: bookmark appears, continue reading and history work;
   - auth: login, kill and reopen the app, refresh succeeds; a stale session may
     return one 401 on `/auth/refresh`, but the app must recover or ask to log
     in, not crash;
   - downloads: download one chapter, progress reaches `done`, chapter opens
     from the library.

8. **Offline behavior.**

   ```bash
   adb shell cmd connectivity airplane-mode enable
   ```

   Open a downloaded chapter, the library and settings; kill and reopen the
   app. No crash, local bookmarks/history/progress remain. Then disable airplane
   mode:

   ```bash
   adb shell cmd connectivity airplane-mode disable
   ```

9. **TLS sanity.** No certificate warning or API failure on the HTTPS host;
   device date/time is correct. If TLS fails, check the certificate chain and
   device clock before filing an API bug. `85.192.37.58.nip.io` must resolve to
   `85.192.37.58`.

10. **Sign-off.** Attach the installed APK SHA-256, certificate fingerprint,
    logcat excerpt and the pass/fail matrix to #35. Only then publish the draft
    release and verify
    `https://github.com/geekAmis/mangapoiskAPI/releases/latest/download/mangapoisk-reborn.apk`
    downloads the same SHA-256. On any failure, keep the release in draft and
    attach the exact failing logcat lines.

### Verification performed

| Check | Result |
|---|---|
| `assembleDebug` | **SUCCESS** — `app/build/outputs/apk/debug/app-debug.apk` |
| `assembleRelease` (R8/resources shrink) | **SUCCESS** — `app/build/outputs/apk/release/app-release-unsigned.apk` |
| Capacitor `assembleDebug` / `assembleRelease` | **SUCCESS** — `ru.mangapoisk.reborn` 1.1.0 (versionCode 2); bundle/API config verified HTTPS-only; release APK built unsigned, then signed with the production key |
| `apksigner verify` (signed 1.1.0) | **SUCCESS** — v1, v2 and v3 schemes all `true`; RSA 4096; certificate SHA-256 `e8b8c812ef402e3e54ed2932b7006e96e98b30aee5fd27e44b7bb2a459e2be74`; APK SHA-256 `b2d8e760ff779369dbfd6e5fb4ca1730c23976afb966c30f4361b469a5e33ff8` |
| Draft release asset | **UPLOADED** — `mangapoisk-reborn.apk` on draft `MangaPoisk Reborn 1.1.0`; not published pending on-device QA |
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
10. **Release APK signing is manual.** The 1.1.0 APK is signed with the
    production key outside Gradle and uploaded to the draft release, but
    publication is blocked on the on-device QA checklist above.
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
