# Deployment

## Docker Compose (single VPS)

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

The web app listens on `:8080`.  Put a TLS reverse proxy (Caddy, Traefik or
nginx) in front of it:

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
| `CATALOG_DATABASE_URL` | `postgresql+asyncpg://.../catalog` |
| `LIBRARY_DATABASE_URL` | `postgresql+asyncpg://.../library` |
| `REDIS_URL` | cache (`redis://redis:6379/0`) |
| `PARSER_URL`, `CATALOG_URL`, `LIBRARY_URL`, `MEDIA_URL`, `NOTIFIER_URL` | service map |
| `CORS_ORIGINS` | comma-separated public origins |
| `MANGAPOISK_COOKIE` | optional; never commit |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional notifications |
| `MEDIA_ALLOWED_HOSTS` | optional comma-separated image CDN allowlist |
| `PUBLIC_WEB_URL`, `PUBLIC_API_URL` | links in notifications/docs |

Production validation refuses to start with the default `JWT_SECRET` or
`INTERNAL_TOKEN`.

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
