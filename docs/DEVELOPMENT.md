# Development

## Prerequisites

- Python 3.12+ (3.13 works)
- Node.js 20+ (22 tested)
- Git
- Optional: Docker Desktop / Docker Engine + Compose v2
- Optional for Android: JDK 17 + Android SDK (compileSdk 34)

## Quick start with Docker (recommended)

```bash
cp .env.example .env
# edit .env: set JWT_SECRET and INTERNAL_TOKEN
docker compose up --build
```

Open:

- web: <http://localhost:8080>
- API docs: <http://localhost:8000/docs> after starting the `gateway-public`
  profile: `docker compose --profile dev up -d gateway-public`
- API: <http://localhost:8000/api/v1>

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
uvicorn app.main:app --app-dir services/gateway --port 8000 --reload
python -m services.scheduler.app.main
```

Or use the helper:

```powershell
.\scripts\dev.ps1
```

It starts all Python services in background jobs and writes logs to
`data/logs/`.

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

## Conventions

- Async everywhere in services; never block the event loop with `requests`.
- Typed Pydantic models at the boundary; no raw dicts in public responses.
- `snake_case` in JSON (clients adapt to their language style).
- Errors use `{"error": {"code", "message", "details"}}`.
- Never log secrets, cookies, tokens or full HTML bodies.
- Add a test for every bug fix.
- Keep the parser's politeness defaults; use the cache instead of hammering a
  source.
