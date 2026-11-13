# MangaPoisk Reborn — Node.js mobile shell

This is the Node.js/Capacitor build of the same React app. It is an alternative
to the native Kotlin client in `apps/android`.

Current release: **1.3.2 / versionCode 5**, packaged `www` (no remote
`server.url`), origin `https://localhost`, API 443. It is installed on the QA
device; Android QA is paused (#84) and no GitHub APK asset is published yet.

## Build

```bash
cd apps/mobile
npm install
npm run sync          # builds apps/web with the production HTTPS API URL, then cap sync
npm run apk           # android/app/build/outputs/apk/debug/app-debug.apk
```

Release build (unsigned intermediate; sign it with the production keystore):

```bash
cd apps/mobile
npm run sync
cd android
./gradlew assembleRelease
# android/app/build/outputs/apk/release/app-release-unsigned.apk
```

The API base is baked into the web build. Production defaults to:

```text
https://85.192.37.58.nip.io/api/v1
```

Override it with `CAPACITOR_API_BASE`. The build script refuses arbitrary
plain-HTTP URLs; only `https://` and local development hosts
(`localhost`, `127.0.0.1`, `10.0.2.2`) are accepted:

```powershell
# Web-only local API for browser development.
# The packaged Android shell still enforces HTTPS and will block cleartext.
$env:CAPACITOR_API_BASE = "http://127.0.0.1:8000/api/v1"
npm run build:www
```

For a physical device on the same network, use the server IP. For the emulator,
`10.0.2.2` points at the host. Release builds must use HTTPS.

> Release 1.3.2 was built from `release/android-1.3.2`, where the default API
> base is 443 and the build rejects `:8088`/`:8443`. If you build from `main`
> before that branch is merged, set
> `CAPACITOR_API_BASE=https://85.192.37.58.nip.io/api/v1` explicitly.

## HTTPS / WebView configuration

Release builds use the secure Capacitor settings in
`capacitor.config.json`:

- no `server.url` (packaged `www`, origin `https://localhost`)
- `server.androidScheme: "https"`
- `server.cleartext: false`
- `android.allowMixedContent: false`

The Android manifest also sets `android:usesCleartextTraffic="false"` and points
to `app/src/main/res/xml/network_security_config.xml`, which denies cleartext
traffic at the platform level.

The 1.3.1 build used a remote `server.url`; that changed the WebView origin and
broke layout/taps and the saved 1.3.0 session. Do not reintroduce `server.url`
for release builds (#84).

## Notifications

Android System WebView (used by Capacitor) does not expose the Web Push API:
`PushManager` is missing, and real background delivery requires a native FCM
integration (`@capacitor/push-notifications`, `POST_NOTIFICATIONS` permission on
Android 13+, a notification channel, and a server-side FCM sender). This build
does **not** fake native push. New chapters are shown in the in-app bell while
the app is running; the profile screen detects the native platform and disables
the Web Push switch with an explanation. See
[`docs/NOTIFICATIONS.md`](../../docs/NOTIFICATIONS.md) for the full limitation
and the future native-push task.
