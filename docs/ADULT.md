# Adult-only source (HentaiLib) and age gate

Status: implementation branch `feat/hentailib-age-gate`. The source is **disabled by
default** and must not be enabled in production until the owner completes the
enable sequence below.

## 1. Source domains and API (probe 2026-11-12/13 UTC)

The local development PC is in the RF and cannot reach HentaiLib. Probes were
run from all three production egress nodes with a browser-like User-Agent and a
5–10 s timeout, one request per domain:

| Node | Public address | `hentailib.me` | `hentailib.org` | `hentailib.com` | `hentailib.ru` | `hapi.hentaicdn.org` |
| --- | --- | --- | --- | --- | --- | --- |
| `primary-85` | `85.192.37.58` | 200 HTML | DNS fail | 200 parked lander (114 B) | connection reset | 403 root; API 200 JSON |
| `jump-83` | `83.141.92.137` | 200 HTML | DNS fail | 200 parked lander | connection reset | 403 root; API 200 JSON |
| `aeza-2` | `85.192.30.224` | 200 HTML | DNS fail | 200 parked lander | connection reset | 403 root; API 200 JSON |

`api.hentailib.me`, `api.hentailib.org` and `api.hentailib.ru` do not resolve.
The working JSON API is **`https://hapi.hentaicdn.org/api`** (discovered from
the site bundle; the site itself is `hentailib.me`). `auth.hentaicdn.org` also
responds (200 HTML) and is used by the upstream site for login; we do not use
it to bypass anything.

Verified JSON endpoints (Site-Id `4`):

| Endpoint | Result |
| --- | --- |
| `GET /api/manga?q=&site_id[]=4&page=1&limit=20` | 200, catalogue JSON |
| `GET /api/manga?q=test&site_id[]=4&page=1&limit=20` | 200, search JSON |
| `GET /api/manga/{slug_url}?site_id[]=4` | 200, detail JSON (`ageRestriction: 18+ (RX)`) |
| `GET /api/manga/{slug_url}/chapters` | 200, chapter list (volume, number, branches) |
| `GET /api/manga/{slug_url}/chapter?volume=1&number=1[&branch_id=…]` | 404 JSON for anonymous probes |
| `GET /api/constants?fields[]=imageServers` | 200, image hosts for sites 1/3; site 4 pages are expected absolute |

The reader endpoint returns a deliberate `404`/silent toast for anonymous
requests. The site's reader HTML also disallows crawlers in `robots.txt`
(`/ru/*/read/v*/c*`, `/ru/manga/*/chapter`). The adapter therefore never
scrapes reader HTML: it uses only the JSON API and needs an operator-provided
authorised HentaiLib session (`HENTAILIB_COOKIE` or the admin cookie store) for
pages. Metadata/catalogue/chapter lists work anonymously.

Cover images use `cover.hentaicdn.org`. The adapter normalises protocol-relative
page URLs and keeps absolute upstream URLs.

### Fallback configuration

```env
HENTAILIB_BASE_URLS=https://hentailib.me
HENTAILIB_API_BASE_URLS=https://hapi.hentaicdn.org/api
```

Both accept a comma-separated list. The adapter tries the remembered host
first, then the remaining hosts, and only raises a typed `UpstreamError` when
all are unreachable. Add other live mirrors to `HENTAILIB_BASE_URLS` without a
code change.

## 2. Age model

- 18+ is **self-confirmation** in the account. No documents, no ID upload.
- `users.age_confirmed_at` stores the confirmation timestamp; `NULL` means
  not confirmed or revoked.
- Endpoints:
  - `GET /api/v1/profile/age-status` → `{age_confirmed, age_confirmed_at}`
  - `POST /api/v1/profile/age-confirm` → confirms; optional body `{"confirm": true}`
  - `DELETE /api/v1/profile/age-confirm` → revokes immediately
- The gateway resolves confirmation from the library service for every
  adult-sensitive request, so revoking hides content even with an unexpired
  access token. The JWT also carries `age_confirmed`/`age_confirmed_at` as a
  degraded-mode hint only.

## 3. Visibility enforcement

The catalogue and gateway enforce the gate at every public surface:

- catalogue list, search, instant suggestions, genres, home updates;
- recommendations and related shelves (adult titles are never recommended);
- title variants, bookmarks/history enrichment, imports;
- direct title, chapter, pages, reader image and export routes (403
  `age_confirmation_required` with no content);
- sitemap (always excluded);
- public sources list (adult source hidden for guests/unconfirmed).

Internal catalogue endpoints accept `adult_allowed=true` only from the gateway,
which derives it from the live library status. Guests never receive adult
titles in API responses.

## 4. SEO

- Adult title and reader pages render `<meta name="robots" content="noindex,nofollow">`.
- `X-Robots-Tag: noindex, nofollow` and `Cache-Control: private, no-store` are
  added to adult title/chapter API responses.
- Adult-only titles are excluded from `sitemap.xml` in both the dedicated
  catalogue query and the paginated fallback.
- Canonical URL stays the title's own `/manga/{id}` URL.

## 5. Ads

No ad slot is rendered on an adult-only title or its reader. The gateway also
returns an empty ad configuration when `adult=true`, so a client bug cannot
serve an ad on 18+ content.

## 6. Rate limit, caching and robots

- Uses the shared parser token bucket (`SCRAPER_REQUESTS_PER_MINUTE`) and
  concurrency 1, like other sources.
- Metadata cache TTL follows `SCRAPER_CACHE_TTL_SECONDS`; catalogue cache 300 s.
- The adapter does not fetch reader HTML; `robots.txt` disallows those paths.
- No login bypass, CAPTCHA solving, paywall or DRM circumvention. If the
  upstream returns 403/404 the adapter raises a typed error.

## 7. Enable sequence (lead/owner only)

1. Merge `feat/hentailib-age-gate` into `main` and deploy parser, catalog,
   library, gateway and web. Do **not** enable the source in the same step.
2. Verify additive migrations ran:
   - `sources.adult_only`, `sources.requires_age_confirmation`
   - `manga.adult_only`, `manga.requires_age_confirmation`
   - `users.age_confirmed_at`
3. (Optional, for reader pages) put an authorised HentaiLib session into the
   parser cookie store or `HENTAILIB_COOKIE`. Never commit it.
4. Set `HENTAILIB_BASE_URLS`/`HENTAILIB_API_BASE_URLS` to the verified hosts.
   If `MEDIA_ALLOWED_HOSTS` is configured, add `cover.hentaicdn.org`,
   `img.hentaicdn.org`, `img2.imglib.info` and `img3.cdnlibs.org`.
5. Add `hentailib` to `PARSER_ENABLED_SOURCES` (comma-separated) and restart the
   parser. Then restart/sync the catalogue so `/api/v1/sources` reflects the
   flags.
6. Smoke-test:
   - guest: `/api/v1/manga?source=hentailib` has no adult titles; direct title
     returns 403 `age_confirmation_required`;
   - authenticated unconfirmed: same 403;
   - confirmed: title/chapters/reader 200;
   - revoke: the same token immediately gets 403 again;
   - `/sitemap.xml` contains no HentaiLib titles;
   - `/api/v1/ads/config?adult=true` returns `[]`.
7. Only then run a bounded catalogue crawl for `hentailib` (low page limit) and
   monitor upstream 403/429.

## 8. Legal disclaimer (draft; owner must review)

MangaPoisk Reborn is a catalogue/reader interface and does not claim ownership
of HentaiLib titles. All rights belong to their respective authors and
publishers. The source is available only to authenticated users who have
self-confirmed they are 18+, is excluded from search-engine indexing and the
public sitemap, and is not shown in public recommendations. No identity
documents are collected. Users can revoke confirmation at any time. The owner
must publish a jurisdiction-specific legal page, a complaints contact and a
takedown procedure before enabling the source in production.

## 9. Browser QA evidence

The age gate was exercised against a local mock API with the production web
build (no real HentaiLib content):

- `docs/screenshots/adult-guest-390.png` — guest, 390×844, no content leak;
- `docs/screenshots/adult-unconfirmed-390.png` — signed-in unconfirmed, 390×844;
- `docs/screenshots/adult-confirmed-390.png` — confirmed, 390×844, 18+ notice;
- `docs/screenshots/adult-guest-1440.png` — guest, 1440×900;
- `docs/screenshots/adult-unconfirmed-1440.png` — signed-in unconfirmed, 1440×900;
- `docs/screenshots/adult-confirmed-1440.png` — confirmed, 1440×900;
- `docs/screenshots/adult-reader-guest-390.png` — reader guest gate;
- `docs/screenshots/adult-reader-confirmed-390.png` — reader confirmed with 18+ notice.

The mock returned 403 `age_confirmation_required` for guest/unconfirmed requests
and only metadata for confirmed requests; no adult title text was present in the
403 responses.

## 10. Risks

- **Legal**: adult content and source licensing vary by jurisdiction. The
  owner must review the disclaimer and local law before enabling.
- **Upstream blocking**: HentaiLib may block datacenter egress, rotate domains,
  or require a session. The fallback list and typed errors make failures
  visible without hammering the source.
- **Cookie requirement**: metadata works anonymously; reader pages currently
  require an authorised session. Without it the adapter returns
  `chapter_unavailable`/`pages_unavailable` rather than leaking anything.
- **Domain drift**: `hentailib.org` and `api.hentailib.*` did not resolve at
  probe time; `hentailib.com` is a parked lander. Do not treat them as content
  mirrors until re-probed.
