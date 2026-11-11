# MangaPoisk Reborn — Android

Native Android client for the MangaPoisk Reborn public API. Kotlin 2.0,
Jetpack Compose Material 3, MVVM, Retrofit + kotlinx.serialization, Room,
DataStore, and WorkManager.

The app is a dark-first Russian manga catalogue and reader: home, search,
manga details, continuous/paged reader, library, downloads, account and
settings, with six visual themes shared with the web design.

<p align="center">
  <img src="../../apps/web/public/themes/midnight.webp" alt="Midnight theme" width="720" />
</p>

## Requirements

- Android Studio Ladybug (2024.2) or newer, or a command-line environment.
- JDK 17.
- Android SDK Platform 34 and Build-Tools 34.0.0 (this project is compiled
  against API 34 — see below).
- Internet access for the first Gradle sync.

## Open in Android Studio

1. **File → Open** and select the `apps/android` directory (the directory that
   contains `settings.gradle.kts`), not the repository root.
2. Let Gradle sync. Android Studio creates a machine-specific
   `local.properties` with `sdk.dir=...` if it is missing.
3. Choose an emulator or device with Android 8.0+ (API 26+).
4. Run the `app` configuration.

## Command line

```powershell
cd apps/android
$env:JAVA_HOME = "D:\tools\jdk-17\jdk-17.0.20.1+1"
$env:ANDROID_HOME = "D:\Android\sdk"
.\gradlew.bat assembleDebug
```

On macOS/Linux use `./gradlew assembleDebug`.

Outputs:

- debug APK: `app/build/outputs/apk/debug/app-debug.apk`
- unsigned release APK: `app/build/outputs/apk/release/app-release-unsigned.apk`

`assembleRelease` runs R8 with `proguard-rules.pro`; it produces an unsigned
APK. Add a signing config in `app/build.gradle.kts` for distribution.

## API configuration

The **debug** build defaults to:

```text
http://127.0.0.1:8000/api/v1/
```

This is designed for physical-device testing with:

```bash
adb reverse tcp:8000 tcp:8000
```

The same command also works for an emulator. Alternatively, set the URL at
runtime in **Профиль → Сервер API**:

- physical device + `adb reverse`: `http://127.0.0.1:8000/api/v1/`
- emulator without adb reverse: `http://10.0.2.2:8000/api/v1/`
- physical device on the same LAN: `http://<host-lan-ip>:8000/api/v1/`
- production release build: `https://<host>/api/v1/`

HTTP is allowed **only in debug builds** through
`app/src/debug/res/xml/network_security_config.xml`. Release builds enforce
HTTPS. Changing the API URL while signed in signs the user out so a token is
never sent to a different server.

## Screens

| Screen | What it does |
|---|---|
| Главная | Themed hero, popular, latest updates, continue reading, source shortcuts |
| Каталог | Debounced search, source/sort filters, adaptive grid, infinite scroll |
| Манга | Poster, metadata, genres, description, bookmark, chapters, download, resume |
| Читалка | Vertical continuous (default) or horizontal paged, 30/40/30 tap zones, resume banner, page counter, chapter navigation, progress sync, auto-scroll, gap, theme, keep-screen-on, immersive mode, zoom/pan in paged mode |
| Библиотека | Continue reading, bookmarks, history, downloaded chapters |
| Источники | Source cards with language, availability and capabilities, plus legal note |
| Профиль | Login/register, six theme thumbnails, API URL, reader defaults, cache/download/history cleanup, legal/about |

## Project layout

```text
app/src/main/java/ru/mangapoisk/reborn/
├── MangaApp.kt / MainActivity.kt
├── di/AppContainer.kt             manual DI container
├── data/
│   ├── local/                     Room entities/DAOs, DataStore, encrypted tokens
│   ├── model/                     domain models and enums
│   ├── remote/                    Retrofit API, DTOs, auth, URL resolution
│   └── repo/                      catalogue, auth, library, downloads
├── download/DownloadWorker.kt     WorkManager chapter downloader
└── ui/                            Compose theme, components, screens, navigation
```

See [`../../docs/ANDROID.md`](../../docs/ANDROID.md) for architecture, API
mapping, reader details, and known limitations.

## Notes

- Russian UI strings live in `app/src/main/res/values/strings.xml`.
- No external fonts are downloaded. `noir` and `paper` use the built-in
  serif family for display headings; card titles stay sans.
- The six palettes are taken verbatim from `docs/DESIGN_SYSTEM.md`; Material
  You dynamic colour is intentionally disabled.
- Theme artwork appears only as the separate home-hero panel, the wide auth
  visual panel, and small theme thumbnails in the switcher. It is never behind
  body copy, forms, lists or reader chrome.
- Coil sends a browser-like User-Agent and MangaLib Referer so
  `cover.imglib.info` posters are not rejected by DDoS-Guard (403).
- Do not commit `local.properties`, `.gradle/`, `build/` or APKs; they are
  ignored by `apps/android/.gitignore`.
- This project intentionally uses `compileSdk = 34` because the validation
  environment only has the Android 34 platform installed. To move to API 35,
  install `platforms;android-35`, bump `compileSdk`/`targetSdk`, and use a
  dependency set built for 35.
