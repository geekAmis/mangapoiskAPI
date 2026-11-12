# MangaPoisk Reborn

<p align="center">
  <a href="https://github.com/geekAmis/mangapoiskAPI/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/geekAmis/mangapoiskAPI/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/geekAmis/mangapoiskAPI/releases"><img alt="Release" src="https://img.shields.io/github/v/release/geekAmis/mangapoiskAPI?display_name=tag&sort=semver"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/geekAmis/mangapoiskAPI"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="Node 20.19+" src="https://img.shields.io/badge/node-20.19%2B-339933?logo=node.js&logoColor=white">
  <img alt="Android 8.0+" src="https://img.shields.io/badge/android-8.0%2B-3DDC84?logo=android&logoColor=white">
  <a href="https://85.192.37.58.nip.io:8443"><img alt="Demo" src="https://img.shields.io/badge/demo-85.192.37.58%3A8088-blue"></a>
</p>

Р СѓСЃСЃРєРѕСЏР·С‹С‡РЅС‹Р№ РєР°С‚Р°Р»РѕРі Рё С‡РёС‚Р°Р»РєР° РјР°РЅРіРё: FastAPI-РјРёРєСЂРѕСЃРµСЂРІРёСЃС‹, React SPA,
РЅР°С‚РёРІРЅС‹Р№ Kotlin-РєР»РёРµРЅС‚, Node.js/Capacitor-СЃР±РѕСЂРєР°, РѕС„Р»Р°Р№РЅ-Р±РёР±Р»РёРѕС‚РµРєР° Рё
Р°РґРјРёРЅРєР° РґР»СЏ СѓРїСЂР°РІР»РµРЅРёСЏ СЃРµСЂРІРµСЂР°РјРё.

**Р”РµРјРѕ:** <https://85.192.37.58.nip.io:8443><br>
**РђРґРјРёРЅРєР°:** <https://85.192.37.58.nip.io:8443/admin> (РїСЂСЏРјР°СЏ СЃСЃС‹Р»РєР°, РІ РјРµРЅСЋ РµС‘ РЅРµС‚)<br>
**API:** <https://85.192.37.58.nip.io:8443/api/v1/health>

> Р”РµРјРѕ СЂР°Р±РѕС‚Р°РµС‚ РїРѕ HTTP, Р±РµР· РґРѕРјРµРЅР° Рё TLS. Р”Р»СЏ РїСѓР±Р»РёС‡РЅРѕРіРѕ РґРµРїР»РѕСЏ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕ
> РїРѕСЃС‚Р°РІСЊС‚Рµ HTTPS-РїСЂРѕРєСЃРё. РџРѕРґСЂРѕР±РЅРѕСЃС‚Рё вЂ” РІ [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

![Р“Р»Р°РІРЅР°СЏ MangaPoisk Reborn](docs/screenshots/prod-home-desktop.png)

## РЎС‚Р°С‚СѓСЃ

- `v1.0.0` вЂ” РѕРїСѓР±Р»РёРєРѕРІР°РЅРЅС‹Р№ СЂРµР»РёР· РѕС‚ 11.11.2026.
- `main` вЂ” РїРѕРґРіРѕС‚РѕРІРєР° `v1.1.0`: РѕС„Р»Р°Р№РЅ-Р±РёР±Р»РёРѕС‚РµРєР°, dancing-СЃРїРёРЅРЅРµСЂС‹, СѓСЃРёР»РµРЅРёРµ
  Р°РґРјРёРЅРєРё Рё РЅР°РґС‘Р¶РЅРѕСЃС‚Рё server manager. Р§РµСЂРЅРѕРІРёРє РѕРїРёСЃР°РЅРёСЏ СЂРµР»РёР·Р°:
  [docs/RELEASE_NOTES_v1.1.0.md](docs/RELEASE_NOTES_v1.1.0.md).
- CI: [GitHub Actions](https://github.com/geekAmis/mangapoiskAPI/actions/workflows/ci.yml).
- Р Р°Р·СЂР°Р±РѕС‚РєР° РёРґС‘С‚ РїРѕ С€Р°РіР°Рј РІ [issues](https://github.com/geekAmis/mangapoiskAPI/issues);
  СЌРїРёРє вЂ” [#3](https://github.com/geekAmis/mangapoiskAPI/issues/3).

## Р§С‚Рѕ СѓРјРµРµС‚

- **РљР°С‚Р°Р»РѕРі Рё РїРѕРёСЃРє** РїРѕ Р»РѕРєР°Р»СЊРЅРѕРјСѓ РёРЅРґРµРєСЃСѓ Рё РёСЃС‚РѕС‡РЅРёРєР°Рј: Р¶Р°РЅСЂС‹, РіРѕРґС‹,
  СЃС‚Р°С‚СѓСЃ, СЃРѕСЂС‚РёСЂРѕРІРєРё, РёРјРїРѕСЂС‚ РїРѕ СЃСЃС‹Р»РєРµ.
- **РљР°СЂС‚РѕС‡РєР° С‚Р°Р№С‚Р»Р°** СЃ РІР°СЂРёР°РЅС‚Р°РјРё РёСЃС‚РѕС‡РЅРёРєР° Рё РїРµСЂРµРІРѕРґР°. РљРЅРѕРїРєР° В«Р§РёС‚Р°С‚СЊВ»
  РІС‹Р±РёСЂР°РµС‚ РёСЃС‚РѕС‡РЅРёРє, РіРґРµ Р±РѕР»СЊС€Рµ РіР»Р°РІ; С„РёР»СЊС‚СЂ вЂ” `source/translator/count`.
- **Р§РёС‚Р°Р»РєР°**: РІРµСЂС‚РёРєР°Р»СЊРЅР°СЏ, webtoon Рё РїРѕСЃС‚СЂР°РЅРёС‡РЅР°СЏ; Р°РІС‚Рѕ-СЃРєСЂРѕР»Р», РїРёРЅС‡-Р·СѓРј,
  РіРѕСЂСЏС‡РёРµ РєР»Р°РІРёС€Рё, СЃРѕС…СЂР°РЅРµРЅРёРµ РїСЂРѕРіСЂРµСЃСЃР°.
- **РћС„Р»Р°Р№РЅ-Р±РёР±Р»РёРѕС‚РµРєР°**: СЃРєР°С‡РёРІР°РЅРёРµ РѕС‚РґРµР»СЊРЅРѕР№ РіР»Р°РІС‹ РёР»Рё РІСЃРµРіРѕ С‚Р°Р№С‚Р»Р°, РѕС‡РµСЂРµРґСЊ
  СЃ РґРѕРєР°С‡РєРѕР№, СѓРґР°Р»РµРЅРёРµ Рё С‡С‚РµРЅРёРµ Р±РµР· СЃРµС‚Рё. Р’ Р±СЂР°СѓР·РµСЂРµ вЂ” IndexedDB, РІ
  Capacitor вЂ” Filesystem/Preferences, РІ Kotlin-РєР»РёРµРЅС‚Рµ вЂ” Room/WorkManager.
- **Р­РєСЃРїРѕСЂС‚** РіР»Р°РІС‹ РІ CBZ, PDF РёР»Рё HTML-ZIP.
- **РЎРµСЂРІРµСЂРЅС‹Р№ Р°СЂС…РёРІ**: РјР°Р»РµРЅСЊРєРёРµ СЃС‚СЂР°РЅРёС†С‹ вЂ” BLOB РІ SQLite, Р±РѕР»СЊС€РёРµ вЂ” ZIP;
  С‡РёС‚Р°Р»РєР° СЃРЅР°С‡Р°Р»Р° Р±РµСЂС‘С‚ Р°СЂС…РёРІ, РїРѕС‚РѕРј РёСЃС‚РѕС‡РЅРёРє.
- **РЁРµСЃС‚СЊ С‚РµРј** (`midnight`, `noir`, `oni`, `crimson`, `sunset`, `paper`) Рё
  16 dancing-GIF РІРјРµСЃС‚Рѕ СЃРєСѓС‡РЅС‹С… СЃРїРёРЅРЅРµСЂРѕРІ.
- **Р”РІР° Android-РєР»РёРµРЅС‚Р°**: Kotlin/Jetpack Compose Рё Node.js/Capacitor.
- **РђРґРјРёРЅРєР° `/admin`**: СЃРµСЂРІРµСЂС‹, SSH-РґРµРїР»РѕР№ (РІРєР»СЋС‡Р°СЏ jump-host), health,
  registry, РїРµСЂРµРєР»СЋС‡РµРЅРёРµ РјР°СЂС€СЂСѓС‚РѕРІ, audit log.
- **РСЃС‚РѕС‡РЅРёРєРё**: MangaPoisk Рё MangaLib РІРєР»СЋС‡РµРЅС‹; Remanga, ReadManga Рё MangaDex
  СЂРµР°Р»РёР·РѕРІР°РЅС‹, РЅРѕ РІС‹РєР»СЋС‡РµРЅС‹ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ (robots/СЃРµС‚СЊ). Р§РµСЃС‚РЅС‹Р№ СЃС‚Р°С‚СѓСЃ вЂ”
  РІ [docs/SOURCES.md](docs/SOURCES.md).

## РЎРєСЂРёРЅС€РѕС‚С‹

| РљР°С‚Р°Р»РѕРі | РљР°СЂС‚РѕС‡РєР° С‚Р°Р№С‚Р»Р° |
|---|---|
| ![РљР°С‚Р°Р»РѕРі](docs/screenshots/prod-catalog-desktop.png) | ![РљР°СЂС‚РѕС‡РєР° С‚Р°Р№С‚Р»Р°](docs/screenshots/prod-manga-desktop.png) |

| Р§РёС‚Р°Р»РєР° | РћС„Р»Р°Р№РЅ-Р±РёР±Р»РёРѕС‚РµРєР° |
|---|---|
| ![Р§РёС‚Р°Р»РєР°](docs/screenshots/prod-reader-final.png) | ![РЎРєР°С‡Р°РЅРЅС‹Рµ РіР»Р°РІС‹](docs/screenshots/prod-library-downloads-mobile.png) |

| Dancing loader | Boot loader |
|---|---|
| ![Dancing loader](docs/screenshots/prod-dancing-loader.png) | ![Boot loader](docs/screenshots/prod-boot-loader.png) |

| Kotlin / Compose | Node.js / Capacitor |
|---|---|
| ![Android Kotlin](docs/screenshots/android-final-home2.png) | ![Capacitor](docs/screenshots/node-translations.png) |

## РђСЂС…РёС‚РµРєС‚СѓСЂР°

```mermaid
flowchart LR
    C["Web React В· Kotlin В· Capacitor"] --> G["gateway :8100"]
    G --> CAT["catalog :8102"]
    G --> LIB["library :8103"]
    G --> MED["media :8104"]
    G --> CTL["control :8005"]
    CAT --> P["parser :8101"]
    P --> S["MangaPoisk В· MangaLib В· Remanga В· ReadManga В· MangaDex"]
    SCH["scheduler :8107"] --> CAT
    SCH --> NOT["notifier :8106"]
    SCH --> MED
    CTL -. "SSH / jump-host deploy" .-> SRV["СЃРµСЂРІРµСЂС‹"]
    G -. "registry / failover" .-> CTL
```

| РЎРµСЂРІРёСЃ | Docker Compose (dev) | Production (systemd) | РћС‚РІРµС‚СЃС‚РІРµРЅРЅРѕСЃС‚СЊ |
|---|---:|---:|---|
| `gateway` | 8000 | 8100 | РїСѓР±Р»РёС‡РЅС‹Р№ `/api/v1`, rate limit, Р°РіСЂРµРіР°С†РёСЏ |
| `parser` | 8001 | 8101 | Р°РґР°РїС‚РµСЂС‹ РёСЃС‚РѕС‡РЅРёРєРѕРІ |
| `catalog` | 8002 | 8102 | РєР°С‚Р°Р»РѕРі, РїРѕРёСЃРє, РёРјРїРѕСЂС‚, РіР»Р°РІС‹ |
| `library` | 8003 | 8103 | Р°РєРєР°СѓРЅС‚С‹, Р·Р°РєР»Р°РґРєРё, РїСЂРѕРіСЂРµСЃСЃ, РЅР°СЃС‚СЂРѕР№РєРё |
| `media` | 8004 | 8104 | РєСЌС€ РєР°СЂС‚РёРЅРѕРє, СЌРєСЃРїРѕСЂС‚, Р°СЂС…РёРІ |
| `control` | 8005 | 8005 | СЃРµСЂРІРµСЂС‹, SSH-РґРµРїР»РѕР№, health registry |
| `notifier` | 8006 | 8106 | Telegram |
| `scheduler` | вЂ” | 8107 (Р±РµР· HTTP) | refresh РєР°С‚Р°Р»РѕРіР°, РѕС‡РёСЃС‚РєР° |
| `web` | 8080 | 8088 (nginx) | React-СЃР±РѕСЂРєР° Рё `/api` |

Р’ production РЅР°СЂСѓР¶Сѓ СЃРјРѕС‚СЂРёС‚ С‚РѕР»СЊРєРѕ nginx РЅР° `8088`; backend-РїРѕСЂС‚С‹ СЃР»СѓС€Р°СЋС‚
`127.0.0.1`. Docker Compose РёСЃРїРѕР»СЊР·СѓРµС‚ РґСЂСѓРіСѓСЋ РЅСѓРјРµСЂР°С†РёСЋ (8000вЂ“8006) вЂ” СЌС‚Рѕ
РЅРѕСЂРјР°Р»СЊРЅРѕ РґР»СЏ Р»РѕРєР°Р»СЊРЅРѕРіРѕ Р·Р°РїСѓСЃРєР°. РџРѕРґСЂРѕР±РЅРµРµ:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) Рё
[docs/SERVER_MANAGER.md](docs/SERVER_MANAGER.md).

## Р‘С‹СЃС‚СЂС‹Р№ СЃС‚Р°СЂС‚

РќСѓР¶РЅС‹ Docker Engine/Desktop СЃ Compose v2 Рё Python 3.12+ (С‚РѕР»СЊРєРѕ С‡С‚РѕР±С‹
СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ СЃРµРєСЂРµС‚С‹).

```bash
git clone https://github.com/geekAmis/mangapoiskAPI.git
cd mangapoiskAPI
cp .env.example .env

python -c "import secrets; print('JWT_SECRET='+secrets.token_urlsafe(48)); print('INTERNAL_TOKEN='+secrets.token_urlsafe(48)); print('CONTROL_SECRET_KEY='+secrets.token_urlsafe(48))"
```

Р’СЃС‚Р°РІСЊС‚Рµ Р·РЅР°С‡РµРЅРёСЏ РІ `.env`, Р·Р°РґР°Р№С‚Рµ СЃРІРѕР№ `ADMIN_PASSWORD` Рё Р·Р°РїСѓСЃС‚РёС‚Рµ:

```bash
docker compose up -d --build
```

- СЃР°Р№С‚ вЂ” <http://localhost:8080>
- РїСЂРѕРІРµСЂРєР° вЂ” <http://localhost:8080/api/v1/health>
- Swagger вЂ” <http://localhost:8000/docs> РїРѕСЃР»Рµ
  `docker compose --profile dev up -d gateway-public`

РџРµСЂРІС‹Р№ РёРјРїРѕСЂС‚:

```bash
curl -X POST http://localhost:8080/api/v1/manga/import \
  -H "Content-Type: application/json" \
  -d '{"source":"mangapoisk","url":"https://mangapoisk.me/manga/zombie-slasher"}'
```

## Р—Р°РїСѓСЃРє Р±РµР· Docker

РќСѓР¶РЅС‹ Python 3.12+, Node.js 20.19+ Рё РЅРµСЃРєРѕР»СЊРєРѕ С‚РµСЂРјРёРЅР°Р»РѕРІ.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e packages/manga_common
pip install -r services/parser/requirements.txt
pip install -r services/catalog/requirements.txt
pip install -r services/library/requirements.txt
pip install -r services/media/requirements.txt
pip install -r services/control/requirements.txt
pip install -r services/gateway/requirements.txt
pip install -r services/scheduler/requirements.txt
pip install -r services/notifier/requirements.txt
```

РЎРєРѕРїРёСЂСѓР№С‚Рµ `.env.example` РІ `.env`, РѕСЃС‚Р°РІСЊС‚Рµ SQLite-URL Рё Р·Р°РїСѓСЃС‚РёС‚Рµ
`scripts/dev.ps1` (parser, catalog, library, media, notifier, gateway) РёР»Рё
РїРѕРґРЅРёРјР°Р№С‚Рµ СЃРµСЂРІРёСЃС‹ РІСЂСѓС‡РЅСѓСЋ. Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Vite РїСЂРѕРєСЃРёСЂСѓРµС‚ `/api` РЅР° `http://localhost:8000`. РџРѕР»РЅР°СЏ РёРЅСЃС‚СЂСѓРєС†РёСЏ:
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## API

Р‘Р°Р·РѕРІС‹Р№ URL вЂ” `/api/v1`. Р’ Docker dev: `http://localhost:8000/api/v1` (С‡РµСЂРµР·
`gateway-public`) РёР»Рё `http://localhost:8080/api/v1` (С‡РµСЂРµР· nginx). Р’
production: `https://85.192.37.58.nip.io:8443/api/v1`.

```http
GET  /api/v1/manga/search?q=РјР°РіРёСЏ&live=true
GET  /api/v1/manga/{id}
GET  /api/v1/manga/{id}/variants
GET  /api/v1/chapters/{id}
GET  /api/v1/chapters/{id}/images/1
POST /api/v1/chapters/{id}/exports?format=cbz
POST /api/v1/manga/{id}/warm
```

РџРѕР»РЅС‹Р№ РєРѕРЅС‚СЂР°РєС‚, РєРѕРґС‹ РѕС€РёР±РѕРє Рё internal-РјР°СЂС€СЂСѓС‚С‹:
[docs/API.md](docs/API.md).

## Android

- **Kotlin / Jetpack Compose** вЂ” `apps/android`, РЅР°С‚РёРІРЅРѕРµ РїСЂРёР»РѕР¶РµРЅРёРµ СЃ Room,
  WorkManager Рё РѕС„Р»Р°Р№РЅ-Р·Р°РіСЂСѓР·РєР°РјРё.
- **Node.js / Capacitor** вЂ” `apps/mobile`, С‚Р° Р¶Рµ React-СЃР±РѕСЂРєР° РІ APK; РёСЃРїРѕР»СЊР·СѓРµС‚
  РѕС„Р»Р°Р№РЅ-Р±РёР±Р»РёРѕС‚РµРєСѓ web-РєР»РёРµРЅС‚Р°.

```bash
# Kotlin
cd apps/android && ./gradlew assembleDebug

# Node.js / Capacitor
cd apps/mobile && npm install && npm run sync
npx cap add android   # РѕРґРёРЅ СЂР°Р·
npm run apk
```

Debug-СЃР±РѕСЂРєР° Kotlin РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ СЃРјРѕС‚СЂРёС‚ РЅР° `http://127.0.0.1:8000/api/v1/`
(`adb reverse tcp:8000 tcp:8000`), СЌРјСѓР»СЏС‚РѕСЂ вЂ” `http://10.0.2.2:8000/api/v1/`.
Release APK РїРѕРєР° РЅРµ РїРѕРґРїРёСЃР°РЅ. РРЅСЃС‚СЂСѓРєС†РёРё:
[docs/ANDROID.md](docs/ANDROID.md) Рё [apps/mobile/README.md](apps/mobile/README.md).

## РђРґРјРёРЅРєР° Рё СЃРµСЂРІРµСЂС‹

РџР°РЅРµР»СЊ вЂ” `/admin`, Р»РѕРіРёРЅ Рё РїР°СЂРѕР»СЊ РёР· `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
Р§РµСЂРµР· РЅРµС‘ РјРѕР¶РЅРѕ РґРѕР±Р°РІРёС‚СЊ СЃРµСЂРІРµСЂ РїРѕ IP/Р»РѕРіРёРЅСѓ/РїР°СЂРѕР»СЋ, РІС‹Р±СЂР°С‚СЊ СЃРµСЂРІРёСЃС‹ Рё РїРѕСЂС‚С‹,
СЂР°Р·РІРµСЂРЅСѓС‚СЊ РёС… РїРѕ SSH (РЅР°РїСЂСЏРјСѓСЋ РёР»Рё С‡РµСЂРµР· jump-host), РїРѕСЃРјРѕС‚СЂРµС‚СЊ Р»РѕРі Рё health,
СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°С‚СЊ registry Рё РїРµСЂРµРєР»СЋС‡РёС‚СЊ С‚СЂР°С„РёРє РЅР° Р·РґРѕСЂРѕРІС‹Р№ СѓР·РµР».

РџР°СЂРѕР»Рё SSH С€РёС„СЂСѓСЋС‚СЃСЏ РєР»СЋС‡РѕРј РёР· `CONTROL_SECRET_KEY` Рё РЅР°СЂСѓР¶Сѓ РЅРµ РѕС‚РґР°СЋС‚СЃСЏ.
РЎРјРµРЅР° `ADMIN_USERNAME`/`ADMIN_PASSWORD` РёРЅРІР°Р»РёРґРёСЂСѓРµС‚ СЃС‚Р°СЂС‹Рµ Р°РґРјРёРЅ-СЃРµСЃСЃРёРё
(`401 admin_session_expired`); РІ production РїР°СЂРѕР»СЊ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ Р·Р°РїСЂРµС‰С‘РЅ.
РџРѕРґСЂРѕР±РЅРµРµ: [docs/SERVER_MANAGER.md](docs/SERVER_MANAGER.md).

![Р’С…РѕРґ РІ Р°РґРјРёРЅРєСѓ](docs/screenshots/prod-admin-login.png)

## Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ Рё РїСЂР°РІРѕ

- РЎРµРєСЂРµС‚С‹ вЂ” С‚РѕР»СЊРєРѕ РІ `.env`; `.env`, cookies Рё `data.txt` РЅРµ РєРѕРјРјРёС‚СЏС‚СЃСЏ.
- Р’ production РѕР±СЏР·Р°С‚РµР»СЊРЅС‹ СЃРІРѕРё `JWT_SECRET`, `INTERNAL_TOKEN`,
  `ADMIN_PASSWORD` Рё `CONTROL_SECRET_KEY`.
- Internal-РјР°СЂС€СЂСѓС‚С‹ С‚СЂРµР±СѓСЋС‚ `X-Internal-Token`; gateway РЅРµ РїСЂРёРЅРёРјР°РµС‚
  РїСЂРѕРёР·РІРѕР»СЊРЅС‹Рµ URL РєР°СЂС‚РёРЅРѕРє, Р° media РїРµСЂРµРїСЂРѕРІРµСЂСЏРµС‚ DNS/redirect Рё Р±Р»РѕРєРёСЂСѓРµС‚
  private-host, metadata Рё РЅРµ-СЂР°СЃС‚СЂРѕРІС‹Рµ РѕС‚РІРµС‚С‹ (SSRF).
- РђРґРјРёРЅ-РІС…РѕРґ РѕРіСЂР°РЅРёС‡РµРЅ 5 РЅРµСѓРґР°С‡РЅС‹РјРё РїРѕРїС‹С‚РєР°РјРё Р·Р° 5 РјРёРЅСѓС‚ РЅР° IP; С‚РѕРєРµРЅ РїРѕ
  СѓРјРѕР»С‡Р°РЅРёСЋ Р¶РёРІС‘С‚ 60 РјРёРЅСѓС‚ (`ADMIN_TOKEN_MINUTES`).
- РџСЂРѕРµРєС‚ РЅРµ С…СЂР°РЅРёС‚ РјР°РЅРіСѓ Сѓ СЃРµР±СЏ: РєР°С‚Р°Р»РѕРі Рё РїСЂРѕРєСЃРёСЂРѕРІР°РЅРёРµ РёР·РѕР±СЂР°Р¶РµРЅРёР№ СЃ
  РёСЃС‚РѕС‡РЅРёРєРѕРІ, Р±РµР· РѕР±С…РѕРґР° paywall/DRM/anti-bot. Р•СЃР»Рё РІС‹ РїСЂР°РІРѕРѕР±Р»Р°РґР°С‚РµР»СЊ вЂ”
  РѕС‚РєСЂРѕР№С‚Рµ issue.
- Р”Р»СЏ РїСѓР±Р»РёС‡РЅРѕРіРѕ РґРµРїР»РѕСЏ РЅСѓР¶РµРЅ HTTPS Рё РѕРіСЂР°РЅРёС‡РµРЅРёРµ `MEDIA_ALLOWED_HOSTS`.

РџСЂР°РІРёР»Р° Рё С‡РµРє-Р»РёСЃС‚ РѕРїРµСЂР°С‚РѕСЂР°: [docs/LEGAL.md](docs/LEGAL.md) Рё
[docs/SOURCES.md](docs/SOURCES.md).

## РўРµСЃС‚С‹

```bash
pytest
ruff check .

cd apps/web
npm run typecheck
npm run build
```

Android: `cd apps/android && ./gradlew assembleDebug`. РЎРµС‚РµРІС‹Рµ С‚РµСЃС‚С‹ РїР°СЂСЃРµСЂР°
РІРєР»СЋС‡РµРЅС‹ С‚РѕР»СЊРєРѕ РїРѕ `RUN_NETWORK_TESTS=1` Рё РЅРµ РІС…РѕРґСЏС‚ РІ РѕР±С‹С‡РЅС‹Р№ РїСЂРѕРіРѕРЅ.

## РћРіСЂР°РЅРёС‡РµРЅРёСЏ

- HTTPS/РґРѕРјРµРЅ РїРѕРєР° РЅРµ РЅР°СЃС‚СЂРѕРµРЅС‹; РґРµРјРѕ СЂР°Р±РѕС‚Р°РµС‚ РїРѕ HTTP.
- Production РёСЃРїРѕР»СЊР·СѓРµС‚ SQLite РЅР° РѕРґРЅРѕРј СѓР·Р»Рµ. РџСЂРёРѕСЂРёС‚РµС‚РЅС‹Р№ СЂРѕСѓС‚РёРЅРі Рё failover
  РµСЃС‚СЊ; СЂРµРїР»РёРєР°С†РёСЏ РґР°РЅРЅС‹С… РІ СЂР°Р·СЂР°Р±РѕС‚РєРµ Рё РІ production РїРѕРєР° РЅРµ РІРєР»СЋС‡РµРЅР°.
- Release APK РЅРµ РїРѕРґРїРёСЃР°РЅ, iOS-СЃР±РѕСЂРєРё РЅРµС‚.
- Remanga, ReadManga Рё MangaDex РІС‹РєР»СЋС‡РµРЅС‹ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ.
- Android-РєР»РёРµРЅС‚ РЅРµ Р·Р°РїСѓСЃРєР°РµС‚ СЌРєСЃРїРѕСЂС‚ CBZ/PDF/HTML Рё РЅРµ РёРјРµРµС‚ UI РёРјРїРѕСЂС‚Р°;
  РѕС„Р»Р°Р№РЅ-РєР°С‚Р°Р»РѕРі С†РµР»РёРєРѕРј РЅРµ РєСЌС€РёСЂСѓРµС‚СЃСЏ.

## Roadmap Рё СѓС‡Р°СЃС‚РёРµ

Р‘Р»РёР¶Р°Р№С€РёРµ РїР»Р°РЅС‹ вЂ” [docs/ROADMAP.md](docs/ROADMAP.md). РСЃС‚РѕСЂРёСЏ РёР·РјРµРЅРµРЅРёР№ вЂ”
[docs/CHANGELOG.md](docs/CHANGELOG.md). РџРµСЂРµРґ PR РїСЂРѕС‡РёС‚Р°Р№С‚Рµ
[CONTRIBUTING.md](CONTRIBUTING.md); РґР»СЏ РЅРµР±РѕР»СЊС€РёС… Р·Р°РґР°С‡ РёС‰РёС‚Рµ
[good first issue](https://github.com/geekAmis/mangapoiskAPI/labels/good%20first%20issue).

## Р›РёС†РµРЅР·РёСЏ

РљРѕРґ вЂ” MIT, СЃРј. [LICENSE](LICENSE). Р›РёС†РµРЅР·РёСЏ РЅРµ РґР°С‘С‚ РїСЂР°РІ РЅР° СЃС‚РѕСЂРѕРЅРЅСЋСЋ РјР°РЅРіСѓ,
РїРµСЂРµРІРѕРґС‹, РёР·РѕР±СЂР°Р¶РµРЅРёСЏ Рё С‚РѕСЂРіРѕРІС‹Рµ РјР°СЂРєРё.
