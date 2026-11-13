# Development

## Prerequisites

- Python 3.12+ (3.13 works)
- Node.js 20.19+ (22 tested)
- Git
- Optional: Docker Desktop / Docker Engine + Compose v2
- Optional for Android: JDK 17 + Android SDK (compileSdk 34)

## Quick start with Docker (recommended)

```bash
cp .env.example .env
# edit .env: JWT_SECRET, INTERNAL_TOKEN, ADMIN_PASSWORD, CONTROL_SECRET_KEY
docker compose up --build
```

Open:

- web: <http://localhost:8080>
- API docs: <http://localhost:8000/docs> after starting the `gateway-public`
  profile: `docker compose --profile dev up -d gateway-public`
- API: <http://localhost:8000/api/v1> (or <http://localhost:8080/api/v1> through
  the web nginx)

Compose uses ports `8000–8006` for local development.  The production systemd
deployment uses `8100–8109` (gateway `8100`, parser `8101`, catalog `8102`,
library `8103`, media `8104`, control `8005`, notifier `8106`, scheduler `8107`,
replica `8108`, comments `8109`) behind standalone nginx on **80/443**; see
[`SERVER_MANAGER.md`](SERVER_MANAGER.md#порты-на-текущем-сервере).

## Local development without Docker

The services support SQLite and an in-memory cache, so you can run the whole
stack on one machine.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
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

Create `.env` from `.env.example`.  For local files use:

```dotenv
CATALOG_DATABASE_URL=sqlite+aiosqlite:///./data/catalog.db
LIBRARY_DATABASE_URL=sqlite+aiosqlite:///./data/library.db
REDIS_URL=
```

Start each service in its own terminal, from the repository root:

```powershell
$env:PYTHONPATH="$PWD\packages"
uvicorn app.main:app --app-dir services/parser --port 8001 --reload
uvicorn app.main:app --app-dir services/catalog --port 8002 --reload
uvicorn app.main:app --app-dir services/library --port 8003 --reload
uvicorn app.main:app --app-dir services/media --port 8004 --reload
uvicorn app.main:app --app-dir services/control --port 8005 --reload
uvicorn app.main:app --app-dir services/notifier --port 8006 --reload
uvicorn app.main:app --app-dir services/gateway --port 8000 --reload
python -m services.scheduler.app.main
```

Or use the helper:

```powershell
.\scripts\dev.ps1
```

It starts parser, catalog, library, media, notifier and gateway in background
jobs and writes logs to `data/logs/`; start control and scheduler separately if
you need the admin panel or periodic refresh.  `scripts/stop-dev.ps1` stops the
jobs started by the helper.

Frontend:

```powershell
cd apps/web
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`.

## Tests

```bash
pytest
ruff check .
```

Frontend:

```bash
cd apps/web
npm run typecheck
npm run build
```

Parser live tests are opt-in:

```powershell
$env:RUN_NETWORK_TESTS="1"; pytest -m network
```

## Demo data

```bash
python scripts/seed_demo.py
```

The script imports a couple of MangaPoisk titles through the running parser
and catalog.  It is safe to re-run.

## Documentation encoding

`README.md` and everything under `docs/` is **UTF-8 without BOM**; Git stores
these files with LF line endings.  Do not round-trip Russian text through
CP1251, Windows-1251 or an editor that guesses a legacy code page — that is how
the README was once turned into unreadable CP1251 mojibake.

Run this before committing documentation changes:

```bash
python scripts/check_docs_encoding.py
```

The script fails on invalid UTF-8, a UTF-8 BOM, `U+FFFD` replacement
characters, common `UTF-8 -> CP1251` mojibake signatures and mixed CRLF/LF
endings.  It accepts explicit paths too:

```bash
python scripts/check_docs_encoding.py README.md docs/RELEASE_NOTES_v1.1.0.md
```

## Conventions

- Async everywhere in services; never block the event loop with `requests`.
- Typed Pydantic models at the boundary; no raw dicts in public responses.
- `snake_case` in JSON (clients adapt to their language style).
- Errors use `{"error": {"code", "message", "details"}}`.
- Never log secrets, cookies, tokens or full HTML bodies.
- Add a test for every bug fix.
- Keep the parser's politeness defaults; use the cache instead of hammering a
  source.
