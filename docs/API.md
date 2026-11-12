# Public API v1

Base URL: `/api/v1`.

| Environment | Public base URL | Notes |
|---|---|---|
| Docker Compose | `http://localhost:8080/api/v1` | through the web nginx |
| Docker Compose, direct API | `http://localhost:8000/api/v1` | after `docker compose --profile dev up -d gateway-public` |
| Production | `https://85.192.37.58.nip.io:8443/api/v1` | nginx on `:8088`; gateway `:8100` is private |

The gateway listens on `8000` in Compose and `8100` in the systemd deployment.
Only the nginx port is public; do not expose the internal service ports.

All responses are JSON unless noted.  Errors always use:

```json
{"error": {"code": "not_found", "message": "Manga not found", "details": null}}
```

Pagination: `?page=1&limit=24` (limit max 100).  List responses:

```json
{"items": [], "total": 0, "page": 1, "limit": 24, "has_next": false}
```

## System

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | aggregated health |
| GET | `/api/v1/sources` | available sources + capabilities |

`GET /api/v1/sources` → `[{"code":"mangapoisk","name":"MangaPoisk","base_url":"https://mangapoisk.me","language":"ru","enabled":true,"requires_cookies":false,"capabilities":{"search":true,"catalog":true,"manga":true,"chapters":true,"pages":true,"latest":true}}]`

## Catalogue and search

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/manga` | local catalogue list/search |
| GET | `/api/v1/manga/search` | search; `live=true` also asks parser |
| GET | `/api/v1/manga/suggest` | instant local suggestions; never asks parser |
| GET | `/api/v1/manga/{id}` | manga detail + chapters |
| GET | `/api/v1/manga/{id}/chapters` | paginated chapter list |
| GET | `/api/v1/manga/{id}/variants` | same title across sources + translator counts |
| POST | `/api/v1/manga/{id}/prepare` | start/idempotent server prepare for device download |
| GET | `/api/v1/manga/{id}/prepare` | persistent prepare progress (`prepared/pending/failed`, batch) |
| POST | `/api/v1/manga/{id}/warm` | queue server archive for every chapter (auth) |
| POST | `/api/v1/manga/import` | import/refresh a manga by source URL or id |

### `GET /api/v1/manga`

Query: `query`, `source`, `genre`, `year`, `status`, `sort` (`popular`, `rating`,
`updated`, `title`, `new`), `page`, `limit`.

`MangaOut` fields: `id, source, source_id, slug, title, title_en, title_alt,
description, year, status, content_type, rating, rating_count, poster_url,
adult, genres[], chapters_count, last_chapter_at, last_synced_at, created_at,
updated_at`.

### `GET /api/v1/manga/search`

Query: `q` (required, min 1), `source` (optional), `live` (default `false`),
`page`, `limit`.  Response extends pagination with `"live": true|false`.
Search is accent/`ё`-insensitive, tolerant to one- or two-character typos,
understands Russian/Latin transliteration and genre/media synonyms, and ranks
exact titles above alternative titles, genres and descriptions.  The live
fallback is an explicit submit path; keystrokes must use `/manga/suggest`.

### `GET /api/v1/manga/suggest`

Query: `q` (required, min 1), `limit` (default 6, max 12).  Uses only the local
index and therefore makes zero parser requests.  Response:

```json
{
  "query": "чензо мен",
  "items": [
    {
      "id": "…",
      "title": "Человек-бензопила",
      "title_en": "Chainsaw Man",
      "poster_url": "…",
      "year": 2018,
      "source": "mangapoisk",
      "reason": "alternative"
    }
  ],
  "total": 1
}
```

`reason` is one of `title`, `alternative`, `genre`, `description`.

### `GET /api/v1/manga/{id}`

Returns `MangaDetailOut`: all `MangaOut` fields plus `chapters: ChapterOut[]`
(sorted newest first, capped at 500).

`ChapterOut`: `id, manga_id, source, source_id, volume, number, title,
translator, published_at, page_count, url, is_external, created_at, updated_at`.

`GET /api/v1/manga/{id}/variants`:

```json
{
  "primary_id": "uuid",
  "items": [
    {
      "id": "uuid", "title": "…", "source": "mangalib", "source_id": "…",
      "poster_url": "…", "rating": 9.2, "chapters_count": 166,
      "translators": [{"name": "Komger", "count": 81}]
    }
  ]
}
```

The mobile/web reader uses this to pick the source with the most chapters and
to filter the chapter list by `<source>/<translator>/<count>`.  `translator`
is `null` when the source does not expose a team; the UI calls it
«Без перевода».

### `POST /api/v1/manga/import`

Body:

```json
{"source": "mangapoisk", "url": "https://mangapoisk.me/manga/overgeared-abs3nSd", "refresh": true}
```

or `{"source":"mangapoisk","source_id":"overgeared-abs3nSd"}`.  Requires no
auth (public import is rate-limited).  Returns `ImportMangaResponse` with
`manga`, `imported_chapters`, `imported_pages`, `source`.

## Reader

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/chapters/{id}` | chapter metadata + pages |
| GET | `/api/v1/chapters/{id}/pages` | page list only |
| GET | `/api/v1/chapters/{id}/images/{number}` | proxied/cached image bytes |
| POST | `/api/v1/chapters/{id}/exports` | start export job |
| GET | `/api/v1/exports/{job_id}` | job status |
| GET | `/api/v1/exports/{job_id}/download` | download file |
| DELETE | `/api/v1/exports/{job_id}` | remove a finished/failed export |

`GET /api/v1/chapters/{id}` → `ChapterDetailOut`:

```json
{
  "id": "uuid", "manga_id": "uuid", "source": "mangapoisk",
  "source_id": "...", "volume": "1", "number": "312", "title": "312 Том 1",
  "page_count": 42, "pages": [{"number":1,"url":"/api/v1/chapters/.../images/1","width":690,"height":1730}],
  "prev_chapter_id": null, "next_chapter_id": null, "is_horizontal": false
}
```

The `url` in pages is always a gateway URL, never a third-party URL.

`POST /api/v1/chapters/{id}/exports?format=cbz|pdf|html` → `ExportJobOut` with
`status` (`queued|running|done|failed`), `progress`, `total`, `download_url`.

### Server-side chapter archive (internal)

Clients do not call these routes directly.  When a chapter is opened, the
gateway asks `media` to archive its pages in the background.  Internal routes
require `X-Internal-Token`.

| Method | Path | Description |
|---|---|---|
| POST | `/internal/archives/chapters` | queue an archive (idempotent) |
| GET | `/internal/archives/chapters/{chapter_id}` | archive metadata/status |
| GET | `/internal/archives/chapters/{chapter_id}/pages/{number}` | archived image bytes |
| DELETE | `/internal/archives/chapters/{chapter_id}` | remove an archive |

POST body:

```json
{
  "chapter_id": "uuid", "source": "mangapoisk", "translator": null,
  "pages": [{"number": 1, "url": "https://...", "width": 690, "height": 1730}]
}
```

The response contains `status` (`queued|running|done|failed`), `mode`
(`db|zip|null`), `page_count`, `total_bytes`, `sha256`, `error` and timestamps.
A new job returns `202`; a repeat call returns the existing state (`200`).
Small chapters are stored as SQLite page blobs; larger chapters become a ZIP
of `{number:04d}.{ext}` files plus `manifest.json`.  `GET
/api/v1/chapters/{id}/images/{n}` serves from the archive first and falls back
to the source URL only when the page is not archived.  The archive is an LRU
disk cache (about 25 GiB by default, `last_accessed_at`, pruned at startup and
after archiving); metadata and covers are not evicted.

## Auth

| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/auth/register` | `{email,password,display_name}` |
| POST | `/api/v1/auth/login` | `{email,password}` |
| POST | `/api/v1/auth/refresh` | `{refresh_token}` |
| POST | `/api/v1/auth/logout` | `{refresh_token}` |
| GET | `/api/v1/auth/me` | Bearer token |
| GET | `/api/v1/auth/providers` | public `{yandex: bool}` |
| GET | `/api/v1/auth/yandex/start?next=/library` | 302 to Yandex; 503 when disabled |
| GET | `/api/v1/auth/yandex/callback` | Yandex redirect target (302 to SPA) |
| POST | `/api/v1/auth/yandex/exchange` | `{code}` one-time handoff → `TokenPair` |

`TokenPair`: `{access_token, refresh_token, token_type:"bearer", expires_in,
user:{id,email,display_name,role,created_at}}`.

Yandex OAuth details, scopes and the production redirect URI are documented in
[`AUTH_YANDEX.md`](AUTH_YANDEX.md).

Access token lifetime: 30 minutes.  Refresh token: 30 days, rotated on use.
Send `Authorization: Bearer <access_token>`.

## Library (auth required)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/library/bookmarks` | list bookmarks with embedded manga |
| POST | `/api/v1/library/bookmarks` | body `{manga_id}` |
| DELETE | `/api/v1/library/bookmarks/{manga_id}` | remove |
| GET | `/api/v1/library/progress` | continue-reading list |
| PUT | `/api/v1/library/progress` | `{manga_id,chapter_id,page,total_pages}` |
| GET | `/api/v1/library/history?limit=50` | history |
| DELETE | `/api/v1/library/progress/{manga_id}` | reset one title |
| GET | `/api/v1/library/settings` | reader settings |
| PUT | `/api/v1/library/settings` | reader settings |

Reader settings object:

```json
{"theme":"midnight","reader_mode":"vertical","page_fit":"width","auto_scroll":false,"auto_scroll_speed":30,"show_page_numbers":true,"blur_adult_posters":true}
```

## Comments

Comments are attached to titles only (not chapters).  Reads are public; writes
require a reader `Authorization: Bearer <access_token>` header.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/manga/{id}/comments` | paginated threads (top-level + previews) |
| POST | `/api/v1/manga/{id}/comments` | create a comment/reply |
| GET | `/api/v1/comments/{id}/replies` | paginated replies |
| PATCH | `/api/v1/comments/{id}` | edit own comment (15 min window) |
| DELETE | `/api/v1/comments/{id}` | delete own comment |
| POST | `/api/v1/comments/{id}/like` | like/unlike |
| POST | `/api/v1/comments/{id}/report` | report with a reason |
| GET | `/api/v1/notifications` | reply/like notifications for the current user |
| POST | `/api/v1/notifications/read` | mark notification ids as read |
| GET | `/api/v1/admin/comments` | moderation queue (admin) |
| POST | `/api/v1/admin/comments/{id}/{action}` | `hide` or `restore` (admin) |
| GET | `/api/v1/admin/comment-reports` | report queue (admin) |
| POST | `/api/v1/admin/comment-reports/{id}/resolve` | `resolved` or `dismissed` (admin) |

The service stores a `manga_id` as an opaque UUID and keeps discussions after a
title leaves the catalogue.  Create/duplicate cooldowns, daily limits and body
length are configured by `COMMENTS_*` environment variables.

## Admin / server manager

The web admin panel is at `/admin` (direct URL, no nav link).  Login uses
`ADMIN_USERNAME` / `ADMIN_PASSWORD` from the environment and returns an admin
JWT.  Keep this token in `sessionStorage`; it is not the reader account token.

Admin tokens contain an `av` claim — an HMAC fingerprint of the current admin
credentials.  Changing `ADMIN_USERNAME` or `ADMIN_PASSWORD` invalidates every
previously issued admin token; protected calls then return
`401 admin_session_expired` and the UI asks for a new login.  Production
startup refuses the default `ADMIN_PASSWORD`.  Admin tokens live for 60 minutes
by default (`ADMIN_TOKEN_MINUTES`), and five failed logins from one IP within
five minutes return `429 admin_rate_limited`.  Reader access/refresh tokens are
unaffected.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/admin/login` | `{username,password}` → admin token |
| GET | `/api/v1/admin/me` | current admin |
| GET/POST | `/api/v1/admin/servers` | list / add server |
| PATCH/DELETE | `/api/v1/admin/servers/{id}` | update / remove |
| POST | `/api/v1/admin/servers/{id}/deploy` | install selected services over SSH |
| GET | `/api/v1/admin/servers/{id}/health` | check one server |
| GET | `/api/v1/admin/jobs/{id}` | deployment job + log |
| GET | `/api/v1/admin/registry` | service → endpoints + health |
| POST | `/api/v1/admin/registry/sync` | refresh health and switch gateway routes |
| POST | `/api/v1/admin/failover` | same, explicit manual failover |
| GET | `/api/v1/admin/audit` | recent admin actions |
| GET/PUT/DELETE | `/api/v1/admin/integrations/yandex` | masked Yandex OAuth settings / set / delete |
| POST | `/api/v1/admin/integrations/yandex/test` | presence/shape check, no secret echo |
| GET | `/api/v1/admin/sources/{code}/cookie` | cookie status only (never the value) |
| PUT | `/api/v1/admin/sources/{code}/cookie` | set/replace a cookie; `{cookie:""}` clears it |
| POST | `/api/v1/admin/sources/{code}/cookie/har` | extract and store a cookie from an uploaded `.har` |

`POST /admin/servers` body:

```json
{
  "name": "primary-85",
  "host": "85.192.37.58",
  "public_host": "85.192.37.58",
  "ssh_port": 22,
  "username": "root",
  "password": "…",
  "jump_server_id": "uuid-or-null",
  "bind_host": "127.0.0.1",
  "is_fallback": false,
  "is_jump": false,
  "services": [
    {"code": "parser", "port": 8101},
    {"code": "catalog", "port": 8102}
  ]
}
```

Service codes: `parser, catalog, library, media, control, gateway, notifier,
scheduler, replica, comments`.  `scheduler` has no HTTP health check.  Passwords
are encrypted at rest and never returned by the API.  Source cookies are stored
persistently (`PARSER_COOKIE_STORE_PATH`, mode `0600`) and are never returned in
API responses or written to the audit log.

## Internal API (not public)

All internal paths require `X-Internal-Token`.  Services listen on an internal
network in production and should not be exposed publicly.

### Parser

- `GET /internal/sources`
- `GET /internal/search?source=&q=&page=`
- `GET /internal/manga?source=&source_id=&url=`
- `GET /internal/chapter?source=&source_id=&url=`
- `GET /internal/home?source=`
- `GET /health`, `GET /ready`

### Catalog

- `GET /internal/manga?...`, `GET /internal/manga/{id}`
- `GET /internal/manga/by-source/{source}/{source_id}`
- `GET /internal/manga/{id}/chapters`
- `GET /internal/sitemap?limit=50000` (canonical title ids + lastmod for the gateway sitemap)
- `POST /internal/manga/import`
- `PATCH /internal/manga/{id}/chapters/{chapter_id}/pages`
- `POST /internal/maintenance/refresh?limit=5`
- `GET /internal/stats`

### Library

- `POST /internal/auth/register|login|refresh|logout`
- `GET /internal/auth/me`
- `GET|POST /internal/auth/yandex/{status,start,callback,deny,exchange}`
- `GET/POST/DELETE /internal/users/{user_id}/bookmarks...`
- `GET/PUT /internal/users/{user_id}/progress...`
- `GET/PUT /internal/users/{user_id}/settings`

### Media

- `GET /internal/image?url=...` (only called by gateway)
- `POST /internal/exports` body `{chapter_id, manga_title, chapter_label, format, pages:[{number,url}]}`
- `GET /internal/exports/{job_id}`
- `GET /internal/exports/{job_id}/download`
- `DELETE /internal/exports/{job_id}`

## Client guidance

- Web: React Query for server state, local Zustand store for theme/reader UI.
- Android: Retrofit/Ktor + kotlinx.serialization; store tokens in
  EncryptedSharedPreferences; use `page` URLs exactly as returned.
- Always debounce progress writes (500–1000 ms) and send page numbers 1-based.
- Image URLs are same-origin gateway URLs; do not rewrite them to upstream.
