# MangaPoisk Reborn — Node.js mobile shell

This is the Node.js/Capacitor build of the same React app.  It is an alternative
to the native Kotlin client in `apps/android`.

```bash
cd apps/mobile
npm install
npm run sync          # builds apps/web with the production API URL, then cap sync
npx cap add android   # once
npm run apk           # android/app/build/outputs/apk/debug/app-debug.apk
```

The API base is baked into the web build:

- production default: `http://85.192.37.58:8088/api/v1`
- override: `set CAPACITOR_API_BASE=http://10.0.2.2:8000/api/v1` (PowerShell)
  or `CAPACITOR_API_BASE=... npm run sync`.

For a physical device on the same network, use the server IP.  For the emulator,
`10.0.2.2` points at the host.  Release builds should use HTTPS.

The WebView allows cleartext only for local/development servers; see
`android/app/src/main/res/xml/network_security_config.xml` after `cap add
android`.
