# Public API v1

Base URL: `/api/v1` (development: `http://localhost:8000/api/v1`).

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
| GET | `/api/v1/manga/{id}` | manga detail + chapters |
| GET | `/api/v1/manga/{id}/chapters` | paginated chapter list |
| POST | `/api/v1/manga/import` | import/refresh a manga by source URL or id |

### `GET /api/v1/manga`

Query: `query`, `source`, `genre`, `year`, `status`, `sort` (`popular`, `rating`,
`updated`, `title`), `page`, `limit`.

`MangaOut` fields: `id, source, source_id, slug, title, title_en, title_alt,
description, year, status, content_type, rating, rating_count, poster_url,
adult, genres[], chapters_count, last_chapter_at, last_synced_at, created_at,
updated_at`.

### `GET /api/v1/manga/search`

Query: `q` (required, min 1), `source` (optional), `live` (default `false`),
`page`, `limit`.  Response extends pagination with `"live": true|false`.

### `GET /api/v1/manga/{id}`

Returns `MangaDetailOut`: all `MangaOut` fields plus `chapters: ChapterOut[]`
(sorted newest first, capped at 500).

`ChapterOut`: `id, manga_id, source, source_id, volume, number, title,
published_at, page_count, url, is_external, created_at, updated_at`.

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
to the source URL only when the page is not archived.

## Auth

| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/auth/register` | `{email,password,display_name}` |
| POST | `/api/v1/auth/login` | `{email,password}` |
| POST | `/api/v1/auth/refresh` | `{refresh_token}` |
| POST | `/api/v1/auth/logout` | `{refresh_token}` |
| GET | `/api/v1/auth/me` | Bearer token |

`TokenPair`: `{access_token, refresh_token, token_type:"bearer", expires_in,
user:{id,email,display_name,role,created_at}}`.

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

## Admin / server manager

The web admin panel is at `/admin` (direct URL, no nav link).  Login uses
`ADMIN_USERNAME` / `ADMIN_PASSWORD` from the environment and returns an admin
JWT.  Keep this token in `sessionStorage`; it is not the reader account token.

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
scheduler`.  `scheduler` has no HTTP health check.  Passwords are encrypted at
rest and never returned by the API.

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
- `POST /internal/manga/import`
- `PATCH /internal/manga/{id}/chapters/{chapter_id}/pages`
- `POST /internal/maintenance/refresh?limit=5`
- `GET /internal/stats`

### Library

- `POST /internal/auth/register|login|refresh|logout`
- `GET /internal/auth/me`
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
