# MangaPoisk Reborn — Node.js mobile shell

This is the Node.js/Capacitor build of the same React app. It is an alternative
to the native Kotlin client in `apps/android`.

## Build

```bash
cd apps/mobile
npm install
npm run sync          # builds apps/web with the production HTTPS API URL, then cap sync
npm run apk           # android/app/build/outputs/apk/debug/app-debug.apk
```

Release build (unsigned unless a signing config is added):

```bash
cd apps/mobile
npm run sync
cd android
./gradlew assembleRelease
# android/app/build/outputs/apk/release/app-release-unsigned.apk
```

The API base is baked into the web build. Production defaults to:

```text
https://85.192.37.58.nip.io:8443/api/v1
```

Override it with `CAPACITOR_API_BASE`. The build script refuses arbitrary
plain-HTTP URLs; only `https://` and local development hosts
(`localhost`, `127.0.0.1`, `10.0.2.2`) are accepted:

```powershell
# Physical device with adb reverse
$env:CAPACITOR_API_BASE = "http://127.0.0.1:8000/api/v1"
npm run sync
```

For a physical device on the same network, use the server IP. For the emulator,
`10.0.2.2` points at the host. Release builds must use HTTPS.

## HTTPS / WebView configuration

Release builds use the secure Capacitor settings in
`capacitor.config.json`:

- `server.androidScheme: "https"`
- `server.cleartext: false`
- `android.allowMixedContent: false`

The Android manifest also sets `android:usesCleartextTraffic="false"` and points
to `app/src/main/res/xml/network_security_config.xml`, which denies cleartext
traffic at the platform level.
