# Legacy → Reborn

The original `mangapoiskAPI` was a single-process FastAPI/Flask hybrid that
scraped MangaPoisk through Inertia.js JSON, injected templates with a custom
`.mlx` language and shipped a large copied frontend.  It is preserved in git
history (branch `master`, tag/commit before 1.0.0) but removed from `main`.

## What we kept

| Legacy | Reborn |
|---|---|
| Manga search | `GET /api/v1/manga/search` + parser adapters |
| Manga page / chapters | `GET /api/v1/manga/{id}`, chapter list |
| Chapter reader | React reader + `GET /api/v1/chapters/{id}` |
| Page images | `media` cache + `GET /api/v1/chapters/{id}/images/{n}` |
| Offline PDF/HTML (planned) | `media` exports: CBZ, PDF, HTML-ZIP |
| Telegram posts (planned) | `notifier` + scheduler |
| Custom templates / mlx | React + CSS design system (no custom template language) |
| MySQL cookies/IP (planned) | PostgreSQL users + JWT, no IP/cookie tracking |
| `microservice.json` | `.env` + service URLs in `Settings` |

## What we deliberately dropped

- Hard-coded XSRF token and session cookies.
- `os.system("clear && echo ...")` debug side effects.
- Global wildcard imports (`from __init__.file import *`).
- `print()` debugging.
- A custom template language that only one person understood.
- Copied third-party CSS/JS bundles with unknown licenses.
- Direct browser-facing scraped HTML.  The new API returns typed JSON and
  proxies only images it resolves from its own catalogue.

## Migration notes

- Old URLs (`/manga/{name}`, `/manga/{name}/chapter/{chapter}`) are not kept;
  the SPA uses `/manga/:id` and `/read/:chapterId`.  A redirect table could be
  added later if old links matter.
- Old `method=load_pages` / `next_page` endpoints are replaced by the REST
  reader endpoints.
- The old `app.py` ran on port 80 with host `vaka-bit.online`; the new stack
  runs behind nginx on `:8080` (web) and `:8000` (API in dev).
- The old data.txt/credentials file is intentionally outside the repo and
  ignored by git.
