# Comments service

`comments` stores title discussions for MangaPoisk Reborn: top-level comments,
one level of replies, spoiler flags, likes, reports, moderation actions and
in-app notifications.

The service is internal-only. Every route below `/internal` requires the shared
`X-Internal-Token`; user identity is forwarded by the gateway in headers. The
comments service never accepts a browser connection directly and never verifies
JWTs itself.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMMENTS_DATABASE_URL` | `sqlite+aiosqlite:///./data/comments.db` | SQLAlchemy async URL. SQLite is the intended deployment; the parent directory is created automatically. |
| `INTERNAL_TOKEN` | inherited development value | Required on every `/internal` request. |
| `COMMENTS_EDIT_WINDOW_MINUTES` | `15` | How long the author may edit a comment. `0` disables editing. |
| `COMMENTS_CREATE_COOLDOWN_SECONDS` | `10` | Minimum delay between two comments by one user. |
| `COMMENTS_CREATE_DAILY_LIMIT` | `30` | Rolling 24-hour creation limit per user. |
| `COMMENTS_DUPLICATE_WINDOW_SECONDS` | `60` | Identical body in the same title by the same user is rejected inside this window. |
| `COMMENTS_MAX_BODY_LENGTH` | `2000` | Maximum stored body length in characters after normalisation. |
| `COMMENTS_REPORT_REASON_MAX_LENGTH` | `500` | Maximum report reason length. |
| `COMMENTS_REPLY_PREVIEW_LIMIT` | `3` | Replies embedded in a top-level comment. Use `0` to return only counts. |
| `PORT` | `8109` | HTTP port. |
| `ENVIRONMENT` | `development` | In `production`, placeholder internal tokens are rejected at startup. |

Other standard settings (`LOG_LEVEL`, `LOG_JSON`, `DEBUG`, `CORS_ORIGINS`) are
inherited from `manga_common`.

## Data model

All IDs are UUIDs. `manga_id` is intentionally not a foreign key: comments are
kept even if the catalogue temporarily loses a title. The service trusts the
gateway to supply a valid title UUID.

### `comments`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key. |
| `manga_id` | UUID | Opaque catalogue title id, indexed. |
| `user_id` | UUID | Author identity from `X-User-Id`. |
| `user_name` | varchar(64) | Snapshot of `X-User-Name` at creation time. |
| `body` | text | Plain text, max `COMMENTS_MAX_BODY_LENGTH`. |
| `spoiler` | boolean | Client must hide the body until the reader opts in. |
| `parent_id` | UUID/null | `NULL` for a top-level comment; one reply level only. |
| `likes_count` | integer | Denormalised count, recomputed on every toggle. |
| `replies_count` | integer | Visible replies only. |
| `created_at`, `updated_at` | timestamps | UTC. |
| `edited_at` | timestamp/null | Set on an accepted edit. |
| `deleted_at` | timestamp/null | Set on a soft delete. |
| `status` | `visible` / `hidden` / `deleted` | Public reads only see `visible`. |

Indexes: `(manga_id, status, created_at)`, `(user_id, created_at)`, `parent_id`,
`status`.

### `comment_likes`

`id`, `comment_id`, `user_id`, `created_at`; unique `(comment_id, user_id)`.

### `comment_reports`

`id`, `comment_id`, `reporter_id`, `reason`, `status`
(`open` / `resolved` / `dismissed`), `created_at`. A user may have only one
`open` report per comment; after resolution they may report again.

### `comment_notifications`

`id`, `user_id`, `comment_id`, `type` (`reply` / `like` / `moderation`),
`read_at` (null means unread), `created_at`. Unread `like` and `moderation`
notifications for the same comment are de-duplicated. Self-likes and
self-replies never notify.

## Internal API

All routes require `X-Internal-Token`. Writes additionally require
`X-User-Id`; `X-User-Name` is snapshotted; `X-User-Role` is trusted only because
only the gateway can reach this service. Roles `banned`, `blocked` and `deleted`
are rejected on writes. `admin`, `owner` and `moderator` may use moderation
routes.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/internal/manga/{manga_id}/comments?page&limit&sort=new\|top` | Paginated visible top-level comments, each with up to `COMMENTS_REPLY_PREVIEW_LIMIT` replies and `liked_by_me` for the optional viewer. |
| `GET` | `/internal/comments/{id}/replies?page&limit` | Paginated visible replies in chronological order. |
| `POST` | `/internal/manga/{manga_id}/comments` | `{"body": "...", "spoiler": false, "parent_id": null}`. Reply parent must belong to the same title and be top-level. |
| `PATCH` | `/internal/comments/{id}` | `{"body"?: "...", "spoiler"?: true}`. Author only, inside the edit window. |
| `DELETE` | `/internal/comments/{id}` | Author or moderator. Soft-deletes; replies of a top-level comment become hidden. |
| `POST` | `/internal/comments/{id}/like` | Toggle like. Returns `{"liked": bool, "likes_count": n}`. |
| `POST` | `/internal/comments/{id}/report` | `{"reason": "..."}`. 409 if the reporter already has an open report. |
| `GET` | `/internal/notifications?unread_only&page&limit` | Current user's notifications with comment summary and unread count. |
| `POST` | `/internal/notifications/read` | `{"ids": ["..."]}`. Only the current user's unread rows are changed; returns `{"updated": n}`. |
| `GET` | `/internal/admin/comments?status&reported&page&limit` | Flat moderation list including hidden/deleted comments and open report counts. |
| `POST` | `/internal/admin/comments/{id}/hide` | `visible` -> `hidden`; author receives a moderation notification. |
| `POST` | `/internal/admin/comments/{id}/restore` | `hidden`/`deleted` -> `visible`. A reply can only be restored when its parent is visible. |
| `GET` | `/internal/admin/reports?status&page&limit` | Reports with a nested comment snapshot. |
| `POST` | `/internal/admin/reports/{id}/resolve` | Optional body `{"status": "resolved"\|"dismissed"}`, default `resolved`. Idempotent for an already closed report. |

### Response shape

Public comment objects contain `id`, `manga_id`, `user_id`, `user_name`, `body`,
`spoiler`, `parent_id`, `likes_count`, `replies_count`, `liked_by_me`, `is_own`,
`can_edit`, `can_delete`, `edited_at`, `created_at`, `updated_at`. Top-level
items additionally contain `replies`. Admin objects add `status`, `deleted_at`
and `report_count`.

Listing responses use the shared `manga_common.schemas.Paginated` envelope:
`items`, `total`, `page`, `limit`, `has_next`. Notifications use the same
envelope plus `unread_count`.

## Content and moderation rules

* Bodies are plain text. Control characters (except newlines and tabs) are
  removed, line endings are normalised, trailing whitespace is trimmed, empty
  bodies are rejected, and the configured length limit is enforced after
  normalisation. HTML tags are **not** stripped or escaped in storage; the web
  client must render bodies as text (React does this by default).
* Only one reply level exists. Replying to a reply, to a missing comment, or to
  a comment in another title returns `404`/`422`.
* Edits are author-only and limited by `COMMENTS_EDIT_WINDOW_MINUTES`; an edit
  stamps `edited_at`. Moderators cannot rewrite bodies.
* Deletes are soft. Public lists, replies endpoints, likes and new reports hide
  deleted/hidden comments.
* Creation limits are checked in this order: per-user cooldown (`429`,
  `Retry-After`), rolling daily limit (`429`), duplicate body (`409`). Reads are
  not limited here; the gateway applies its own per-IP limit.
* Open reports are de-duplicated per reporter/comment. Resolving one report does
  not resolve other users' reports.

## Gateway integration

The main gateway is expected to add a `CommentsClient` following the existing
`InternalClient` pattern and to expose public routes that forward verified
identity. Suggested mapping:

| Public gateway route | Internal call |
| --- | --- |
| `GET /api/v1/manga/{manga_id}/comments` | `GET /internal/manga/{manga_id}/comments`, forwarding `X-User-Id/Name/Role` when an optional JWT is present. |
| `POST /api/v1/manga/{manga_id}/comments` | `POST /internal/manga/{manga_id}/comments`, requires `require_user`. |
| `GET /api/v1/comments/{id}/replies` | `GET /internal/comments/{id}/replies`. |
| `PATCH /api/v1/comments/{id}` | `PATCH /internal/comments/{id}`, requires `require_user`. |
| `DELETE /api/v1/comments/{id}` | `DELETE /internal/comments/{id}`, requires `require_user`. |
| `POST /api/v1/comments/{id}/like` | `POST /internal/comments/{id}/like`. |
| `POST /api/v1/comments/{id}/report` | `POST /internal/comments/{id}/report`. |
| `GET /api/v1/notifications` | `GET /internal/notifications`. |
| `POST /api/v1/notifications/read` | `POST /internal/notifications/read`. |
| `/api/v1/admin/comments*`, `/api/v1/admin/reports*` | Matching `/internal/admin/*` routes with `require_admin`. |

`CommentsClient` should send `X-Internal-Token` automatically (as the existing
clients do) and add `X-User-Id` from the JWT `sub`, `X-User-Role` from the JWT
`role`, and `X-User-Name` from the library profile (the access token currently
does not carry a display name; gateway may use `/internal/auth/me` or add a
`name` claim). Public routes must never pass through a client-provided
`X-User-*` header.

Deployment checklist for the main integration:

1. Add the service to `docker-compose.yml` on port `8109` with a persistent
   volume mounted at `/data` and `COMMENTS_DATABASE_URL` pointing at
   `sqlite+aiosqlite:////data/comments.db`.
2. Add `COMMENTS_URL=http://comments:8109` to the gateway environment and
   `COMMENTS_URL` to the shared settings (default
   `http://localhost:8109`).
3. Register the service in the control registry as `comments` if the endpoint
   pool should route to replicas.
4. Rebuild the gateway and web client. Do not publish port `8109` publicly.

## Local development

```bash
# from repository root
python -m venv .venv
.venv/Scripts/pip install -e packages/manga_common      # Windows
# .venv/bin/pip install -e packages/manga_common        # Linux/macOS
.venv/Scripts/pip install -r services/comments/requirements.txt

set COMMENTS_DATABASE_URL=sqlite+aiosqlite:///./data/comments.db
set INTERNAL_TOKEN=dev-internal-token-change-me
set PYTHONPATH=%CD%
cd services/comments
uvicorn app.main:app --port 8109
```

Docker:

```bash
docker build -f services/comments/Dockerfile -t mangapoisk-comments .
docker run --rm -p 8109:8109 -v comments-data:/data \
  -e INTERNAL_TOKEN=change-me mangapoisk-comments
```

Tests use a temporary SQLite file and do not need a running server:

```bash
python -m pytest tests/comments -q
python -m ruff check services/comments tests/comments
```

## Assumptions

* Title IDs are UUIDs produced by the catalogue; the comments service does not
  validate title existence.
* The gateway is the only caller. If the service is ever exposed directly, the
  `X-User-*` headers become spoofable; keep the port on the internal network.
* Display names are snapshots. Renaming a profile does not rewrite old comments.
* SQLite is the deployment target. The SQLAlchemy models are portable, but
  migrations are not included: tables are created on startup, matching the
  current project pattern.
* Notifications are in-app only. Telegram/email delivery is deliberately out of
  scope; a future worker can consume the notification table.
