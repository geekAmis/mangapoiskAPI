# Deployment

Production state: **v1.3.2 (2026-11-13)**, `main` @ `affe7d0`.
Public site: <https://85.192.37.58.nip.io> on **80/443**.

The production server does not run Docker. Backend services run as systemd
units under `/opt/mangapoisk-reborn`, and a standalone nginx unit
(`mangapoisk-web.service`) is the only public entry point. The system nginx
unit is failed because of an unrelated site; do not touch it.

## Production topology (standard ports)

| Port | Exposure | Purpose |
|---:|---|---|
| 80 | public | ACME HTTP challenge + 301 to `https://85.192.37.58.nip.io`; exact `/ads.txt` is served directly |
| 443 | public | apex site, `/api/`, sitemap, assets; `www` → 301 apex HTTPS |
| 8088 | legacy public | 301 to 443 for every path except exact `/ads.txt` (direct `200 text/plain`) |
| 8443 | legacy public | **API only** for APK 1.3.0 (`/api/` → gateway); web pages 301 to 443 |
| 8089 | loopback | internal static web root used by gateway prerender (`WEB_INTERNAL_URL`) |
| 8005 | loopback | control |
| 8100–8104, 8106, 8108–8109 | loopback | gateway, parser, catalog, library, media, notifier, replica, comments |
| 8107 | no HTTP | scheduler |

nginx is the public entry point for the site and API. `:8443` exists so the old
APK 1.3.0 keeps working; it is not the current public URL. Remove it only after
the old APK is retired. `:8088` exists only for old links and ads.txt
compatibility.

### TLS certificate

- Let's Encrypt certificate for `85.192.37.58.nip.io` **and**
  `www.85.192.37.58.nip.io`.
- Expiry: **2027-02-11 01:21:39 UTC**.
- Renewal: `authenticator = webroot`, `webroot_path = /var/www/certbot`,
  `renew_hook = systemctl reload mangapoisk-web.service`.
- Targeted check:
  `certbot renew --cert-name 85.192.37.58.nip.io --dry-run` — success.
- Global `certbot renew --dry-run` may report an unrelated `fan-kontur.ru`
  certificate failure on the failed system nginx. Do not modify that site.

### Redirect and direct-path matrix

```text
http://85.192.37.58.nip.io/              -> 301 https://85.192.37.58.nip.io/
http://www.85.192.37.58.nip.io/          -> 301 https://85.192.37.58.nip.io/
https://www.85.192.37.58.nip.io/         -> 301 https://85.192.37.58.nip.io/
https://85.192.37.58.nip.io/             -> 200
https://85.192.37.58.nip.io/api/v1/health-> 200
https://85.192.37.58.nip.io:8443/api/v1/health -> 200 (APK 1.3.0 only)
https://85.192.37.58.nip.io:8443/        -> 301 https://85.192.37.58.nip.io/
http://85.192.37.58.nip.io:8088/         -> 301 https://85.192.37.58.nip.io/
http://.../ads.txt, https://.../ads.txt, http://...:8088/ads.txt
                                          -> 200 text/plain, 9 lines
```

## Option A — systemd on Ubuntu (production)

1. Create `/opt/mangapoisk-reborn` and a system user `mangapoisk`.
2. Copy the repo to `/opt/mangapoisk-reborn/src`.
3. Create a venv and install `packages/manga_common`, then the requirements of
   the services you want.
4. Put a `.env` at `/opt/mangapoisk-reborn/.env` with SQLite URLs:
   `sqlite+aiosqlite:////opt/mangapoisk-reborn/data/catalog.db` and the same for
   `library.db`/`control.db`/`comments.db`/`notifier.db`.
5. Add systemd units (`mangapoisk-parser`, `-catalog`, `-library`, `-media`,
   `-control`, `-gateway`, `-notifier`, `-scheduler`, `-comments`, `-replica`)
   with `EnvironmentFile=/opt/mangapoisk-reborn/.env`.
6. Serve the built SPA from `/opt/mangapoisk-reborn/web`:
   - standalone nginx on **80/443** for the public site, API and static files;
   - a loopback-only static server on **8089** for the gateway prerender
     (`WEB_INTERNAL_URL=http://127.0.0.1:8089`);
   - exact `/ads.txt` locations on 80, 443 and 8088;
   - 301 redirects from `http`, `www`, `:8088` and `:8443` web pages;
   - `:8443` keeps only the `/api/` proxy for APK 1.3.0.
7. Upload `apps/web/dist` (built with the production env below) to
   `/opt/mangapoisk-reborn/web`.

Backend HTTP services run as:

```bash
venv/bin/uvicorn app.main:app --host 127.0.0.1 --port <port>
```

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
| replica | 8108 |
| comments | 8109 |

Use a separate nginx config/unit; do not reuse or restart the failed system
nginx. The admin panel can perform the same steps for new servers.

## Environment

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | access-token signing key (32+ random bytes) |
| `INTERNAL_TOKEN` | service-to-service auth |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | admin panel login; the default password is refused in production |
| `CONTROL_SECRET_KEY` | encrypts SSH, ad and Yandex integration secrets in `control` |
| `CATALOG_DATABASE_URL`, `LIBRARY_DATABASE_URL`, `CONTROL_DATABASE_URL`, `COMMENTS_DATABASE_URL`, `NOTIFIER_DATABASE_URL` | SQLite URLs in production |
| `PARSER_URL`, `CATALOG_URL`, `LIBRARY_URL`, `MEDIA_URL`, `CONTROL_URL`, `NOTIFIER_URL`, `COMMENTS_URL` | service map |
| `CORS_ORIGINS` | comma-separated public origins, including `https://85.192.37.58.nip.io` and `https://localhost` for the Capacitor shell |
| `PUBLIC_WEB_URL` | `https://85.192.37.58.nip.io` (no port) |
| `PUBLIC_API_URL` | `https://85.192.37.58.nip.io/api/v1` (no port) |
| `VITE_SITE_URL` | `https://85.192.37.58.nip.io` at web build time (canonical/OG) |
| `WEB_INTERNAL_URL` | `http://127.0.0.1:8089` — internal SPA `index.html` for gateway prerender |
| `LEGAL_CONTACT_EMAIL`, `LEGAL_OWNER_NAME`, `LEGAL_JURISDICTION` | build-time legal values; production uses `xgemxsite@gmail.com`, `Roman`, `Russia` |
| `GOOGLE_SITE_VERIFICATION`, `YANDEX_VERIFICATION` | meta verification tokens; empty omits the tag |
| `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI` | bootstrap only; production values live encrypted in the control DB and win over env |
| `URL_SLUG_BACKFILL_ENABLED`, `URL_SLUG_BACKFILL_BATCH_SIZE`, `URL_SLUG_BACKFILL_YIELD_SECONDS` | batched background slug backfill for existing catalogues |
| `DEPLOY_HEALTH_TIMEOUT_SECONDS` | per-service health wait after restart (default `600`, allowed 30–7200) |
| `DEPLOY_HEALTH_POLL_SECONDS` | health poll interval (default `2`) |
| `DEPLOY_READ_TIMEOUT_SECONDS` | maximum silent SSH output before the job is failed (default `900`) |
| `DEPLOY_STALE_JOB_SECONDS` | fail/cancel a running job with no heartbeat after this (default `1800`) |
| `DEPLOY_PRE_START_COMMAND`, `DEPLOY_PRE_START_TIMEOUT_SECONDS` | optional command between install and restart, with its own timeout |

Production validation refuses `dev-*` values for `JWT_SECRET`/`INTERNAL_TOKEN`
and the default `ADMIN_PASSWORD`. It also refuses non-HTTPS `PUBLIC_WEB_URL`
and `PUBLIC_API_URL` values so a deploy cannot silently publish HTTP canonical
or sitemap URLs. It does **not** catch every placeholder: replace all
`change-me-*` values from `.env.example`, including `CONTROL_SECRET_KEY`.
Rotating the admin credentials also invalidates existing admin sessions.

Yandex Metrika (`YANDEX_METRIKA_ID`) is **not** part of v1.3.2; it is tracked in
#85. Do not describe the traffic panel as live until that work is merged and
deployed.

### Yandex ID

Set the OAuth credentials in `Админка → Интеграции → Яндекс ID`, not in
`.env`. The real redirect URI is exactly:

```text
https://85.192.37.58.nip.io/api/v1/auth/yandex/callback
```

Scopes: `login:email login:info login:avatar`. `login:info` must be enabled in
Yandex Console and the app must show status **«Подключен»**. The `.env`
`YANDEX_*` keys are bootstrap fallback only; an incomplete DB configuration
disables the provider instead of mixing sources. See
[`AUTH_YANDEX.md`](AUTH_YANDEX.md).

## Deploy health, stale jobs and pre-start migrations

`control` does not use a fixed 80-second startup gate. Each HTTP service is
polled until `DEPLOY_HEALTH_TIMEOUT_SECONDS` (default **600s**, allowed
30–7200s) and the job log records `HEALTH_WAIT` progress plus the final
`HEALTH_OK`/`HEALTH_FAIL` attempt. This is intentional for catalog releases
whose search/filter backfill may take several minutes.

- `DEPLOY_READ_TIMEOUT_SECONDS` bounds silence on the SSH stream. A command
  that produces no output for that long is failed with a timeout instead of
  leaving a job `running` forever.
- `DEPLOY_STALE_JOB_SECONDS` is the heartbeat limit. `updated_at` and
  `last_output_at` are refreshed as output arrives; stale jobs are failed and
  their SSH channel is closed by the control reaper.
- `POST /api/v1/admin/jobs/{job_id}/cancel` cancels a running job explicitly.
- `GET /api/v1/admin/jobs/{job_id}` exposes `last_output_at`; clients should
  treat a running job with an old heartbeat as stale.
- `DEPLOY_PRE_START_COMMAND` runs after source/venv installation and before
  service restart, with `DEPLOY_PRE_START_TIMEOUT_SECONDS` (default 1800s).
  Use it for a release-specific migration/backfill when the release provides a
  CLI. If it does not, run the migration manually on the primary before
  deploying and keep it out of the service startup path.

## Deploy order (v1.3.x)

1. **Freeze and back up.** Stop/quiesce writes, take a restic snapshot and keep
   a local copy of all five SQLite databases. See [`OPS.md`](OPS.md).
2. **Control first.** Deploy the new `control`, restart `mangapoisk-control`,
   verify `/health`, the console/deploy endpoints and Yandex integration rows.
3. **Catalogue pre-build (one-time per major catalogue change).** On a copy or
   in a maintenance window:
   ```bash
   python scripts/reindex_catalog.py --rebuild-catalog
   ```
   Expect a few seconds for the card rebuild on production hardware; FTS
   normalization is separate and must not block health. Verify
   `catalog_groups`/`catalog_source_groups`, no representative without chapter
   rows and no empty cards.
4. **Catalog, then library, gateway.** The gateway needs the new SEO/prerender,
   Yandex auth and console proxy code. Verify `/health`, `/ready`, slug 301,
   `/api/v1/auth/providers` and `/sitemap.xml`.
5. **Parser, scheduler, media, notifier.** Media must install Pillow 13;
   control/notifier must install cryptography 50.
6. **Web + nginx.** Build with production values:
   ```bash
   cd apps/web
   VITE_SITE_URL=https://85.192.37.58.nip.io \
   LEGAL_CONTACT_EMAIL=xgemxsite@gmail.com \
   LEGAL_OWNER_NAME=Roman \
   LEGAL_JURISDICTION=Russia \
   GOOGLE_SITE_VERIFICATION=... \
   YANDEX_VERIFICATION=... \
   npm run build
   ```
   Publish `dist` to `/opt/mangapoisk-reborn/web`, restart the 8089 static
   server, apply the nginx config, `nginx -t`, reload `mangapoisk-web.service`.
7. **Verify.** Redirect matrix, `/ads.txt` on 80/443/8088, canonical/OG without
   port, sitemap ~25k URLs, Yandex ID start/callback, admin tabs/console,
   backup age, RTB config.
8. **Rollback.** Restore the previous `dist`, gateway/control code and DB
   copies; additive columns/tables are safe to leave in place.

Rollout checklist for a slow catalog release:

1. Take an encrypted backup and record the restic snapshot ID.
2. Run the catalog migration/backfill as a pre-start command or a manual
   one-off; confirm it finished and the DB is healthy.
3. Deploy catalog alone; watch `HEALTH_WAIT`/`HEALTH_OK` and the job heartbeat.
4. If the job is stale, use the cancel endpoint; do not start another deploy
   until the old job is failed.
5. Deploy the remaining services in order, then verify `/api/v1/health`,
   sitemap/robots and the admin panels.
6. If catalog startup or DB locks persist, stop and roll back to the last known
   good release.

## Option B — Docker Compose (single VPS, development)

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
This is not the production systemd layout described above. Put a TLS reverse
proxy (Caddy, Traefik or nginx) in front of the web app:

```caddy
manga.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Caddy obtains and renews certificates automatically. If you use nginx, proxy
`/` to `127.0.0.1:8080`; the bundled nginx already proxies `/api` to the
gateway inside the compose network.

## Data and backups

- PostgreSQL data (Compose dev): `postgres-data` volume.
- Redis: `redis-data` (cache, can be lost).
- Media/exports: `media-data` volume.

Backup Postgres (development stack):

```bash
docker compose exec -T postgres pg_dump -U manga catalog > catalog.sql
docker compose exec -T postgres pg_dump -U manga library > library.sql
```

Restore into an empty database:

```bash
cat catalog.sql | docker compose exec -T postgres psql -U manga catalog
```

Production uses SQLite and the `VACUUM INTO` backup script described in
[`OPS.md`](OPS.md), not `pg_dump`. Back up `.env` and `env/*.env` separately;
media cache can be rebuilt and exports expire automatically
(`EXPORT_TTL_HOURS`).

## Upgrades

```bash
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
```

Database schema is created idempotently on startup (`create_all`). For
destructive migrations in future versions, add Alembic revisions before
changing a live database.

## Scaling notes

- `gateway` is stateless; scale it horizontally behind the proxy.
- `catalog` and `library` share SQLite in production; multi-node replication is
  in progress and not enabled. Compose uses Postgres for local development.
- `media` needs a shared volume or S3-compatible storage if scaled to multiple
  replicas.
- `scheduler` must run as a single replica.
- The in-process gateway rate limiter is per replica. For strict global
  limits, move it to Redis.

## Production operations

The production runbooks are in [`OPS.md`](OPS.md): UFW rules and rollback,
encrypted off-host restic backups and the restore drill, swap, TLS renewal and
the `mangapoisk-control` memory guardrail. Read them before changing production
networking, storage or memory limits.

## Health and observability

- `GET /health` on every service.
- `GET /ready` includes DB/storage checks.
- `GET /api/v1/health` aggregates all services.
- Logs are JSON on stdout (`LOG_JSON=true`); ship them with your platform.
- Each request has `X-Request-ID`.
- The admin overview exposes p95/5xx/SQLite lock/backup age and a watchdog;
  see [`OBSERVABILITY.md`](OBSERVABILITY.md).

## Source/legal checklist

Read `docs/LEGAL.md` before exposing the instance publicly. Keep the parser
rate limits conservative and honour any source's request to stop indexing.
The production legal values are already set, but re-check `/contacts`,
`/privacy` and `/dmca` after every web rebuild.
