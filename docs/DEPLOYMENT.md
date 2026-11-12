# Deployment

## Option A — systemd on Ubuntu (no Docker)

The production server for this project does not run Docker.  The control
service can install the backend on any SSH-accessible Ubuntu host (directly or
through a jump host) with the admin panel, or you can do it manually:

1. Create `/opt/mangapoisk-reborn` and a system user `mangapoisk`.
2. Copy the repo to `/opt/mangapoisk-reborn/src`.
3. Create a venv and install `packages/manga_common`, then the requirements of
   the services you want.
4. Put a `.env` at `/opt/mangapoisk-reborn/.env` with SQLite URLs:
   `sqlite+aiosqlite:////opt/mangapoisk-reborn/data/catalog.db` and the same for
   `library.db`/`control.db`.
5. Add systemd units (`mangapoisk-parser`, `-catalog`, `-library`, `-media`,
   `-control`, `-gateway`, `-notifier`, `-scheduler`) with
   `EnvironmentFile=/opt/mangapoisk-reborn/.env`. Production ports:

   | Service | Port |
   |---|---:|
   | gateway | 8100 |
   | parser | 8101 |
   | catalog | 8102 |
   | library | 8103 |
   | media | 8104 |
   | control | 8005 |
   | notifier | 8106 |
   | scheduler | 8107 (no HTTP) |

   The HTTP services run
   `venv/bin/uvicorn app.main:app --host 127.0.0.1 --port <port>`.
6. Run a private nginx instance on `:8088` with root
   `/opt/mangapoisk-reborn/web` and `/api` proxied to the gateway on 8100.
7. Upload the built `apps/web/dist` to `/opt/mangapoisk-reborn/web`.

Do not touch existing nginx/systemd units; use a separate config and ports.
The admin panel can do the same steps automatically for new servers.

## Option B — Docker Compose (single VPS)

1. Install Docker Engine + Compose plugin.
2. Clone the repository.
3. Create the environment file and generate secrets:

```bash
cp .env.example .env
python - <<'PY'
import secrets
print("JWT_SECRET=" + secrets.token_urlsafe(48))
print("INTERNAL_TOKEN=" + secrets.token_urlsafe(48))
PY
```

Paste the values into `.env`, then:

```bash
docker compose up -d --build
docker compose ps
```

The web app listens on `:8080`; internal Compose services use `8000–8006`.
This is not the production systemd layout described in Option A.  Put a TLS
reverse proxy (Caddy, Traefik or nginx) in front of the web app:

```caddy
manga.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Caddy obtains and renews certificates automatically.  If you use nginx, proxy
`/` to `127.0.0.1:8080`; the bundled nginx already proxies `/api` to the
gateway inside the compose network.

## Environment

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | access-token signing key (32+ random bytes) |
| `INTERNAL_TOKEN` | service-to-service auth |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | admin panel login; the default password is refused in production |
| `CONTROL_SECRET_KEY` | encrypts SSH credentials in `control` |
| `CATALOG_DATABASE_URL` | `postgresql+asyncpg://.../catalog` |
| `LIBRARY_DATABASE_URL` | `postgresql+asyncpg://.../library` |
| `REDIS_URL` | cache (`redis://redis:6379/0`) |
| `PARSER_URL`, `CATALOG_URL`, `LIBRARY_URL`, `MEDIA_URL`, `CONTROL_URL`, `NOTIFIER_URL` | service map |
| `CORS_ORIGINS` | comma-separated public origins |
| `MANGAPOISK_COOKIE` | optional; never commit |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional notifications |
| `MEDIA_ALLOWED_HOSTS` | optional comma-separated image CDN allowlist |
| `PUBLIC_WEB_URL`, `PUBLIC_API_URL` | links in notifications/docs; production refuses `http://` |

Production validation refuses `dev-*` values for `JWT_SECRET`/`INTERNAL_TOKEN`
and the default `ADMIN_PASSWORD`.  It also refuses non-HTTPS `PUBLIC_WEB_URL`
and `PUBLIC_API_URL` values so a deploy cannot silently publish HTTP canonical
or sitemap URLs.  It does **not** catch every placeholder:
replace all `change-me-*` values from `.env.example`, including
`CONTROL_SECRET_KEY`.  Rotating the admin credentials also invalidates existing
admin sessions.

## Data and backups

- PostgreSQL data: `postgres-data` volume.
- Redis: `redis-data` (cache, can be lost).
- Media/exports: `media-data` volume.

Backup Postgres:

```bash
docker compose exec -T postgres pg_dump -U manga catalog > catalog.sql
docker compose exec -T postgres pg_dump -U manga library > library.sql
```

Restore into an empty database:

```bash
cat catalog.sql | docker compose exec -T postgres psql -U manga catalog
```

Back up `.env` separately (it contains secrets).  Media cache can be rebuilt;
exports expire automatically (`EXPORT_TTL_HOURS`).

## Upgrades

```bash
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
```

Database schema is created idempotently on startup (`create_all`).  For
destructive migrations in future versions, add Alembic revisions before
changing a live database.

## Scaling notes

- `gateway` is stateless; scale it horizontally behind the proxy.
- `catalog` and `library` share Postgres; use a managed Postgres for larger
  deployments.
- `media` needs a shared volume or S3-compatible storage if scaled to multiple
  replicas.
- `scheduler` must run as a single replica.
- The in-process gateway rate limiter is per replica.  For strict global
  limits, move it to Redis.

## Health and observability

- `GET /health` on every service.
- `GET /ready` includes DB/storage checks.
- `GET /api/v1/health` aggregates all services.
- Logs are JSON on stdout (`LOG_JSON=true`); ship them with your platform.
- Each request has `X-Request-ID`.

## Source/legal checklist

Read `docs/LEGAL.md` before exposing the instance publicly.  Keep the parser
rate limits conservative and honour any source's request to stop indexing.
