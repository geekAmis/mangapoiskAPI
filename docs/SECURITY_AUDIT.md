# Security audit — MangaPoisk Reborn

**Audit date:** 2026-11-11  
**Targets:** repository working tree at `repo/` and the public deployment `https://85.192.37.58.nip.io:8443`  
**Method:** static review first, followed by minimal non-destructive runtime probes (HTTP GET/POST against public endpoints, authorized admin login, JWT/secret validation tests, local unit-level checks). No brute force, no destructive writes, no denial-of-service tests.  
**Scope:** gateway, parser, catalog, library, media, control, scheduler, notifier, shared `manga_common`; production nginx/TLS, exposed ports, admin panel, deployment/SSH, secrets, dependencies and CI.

> **Status update 13.11.2026:** this document is the original audit of
> 11.11.2026. TLS/admin transport, admin rate limiting, rate-limit trust, secret
> separation and media SSRF findings were remediated after the audit; see
> [Remediation status (post-audit)](#remediation-status-post-audit) at the end.
> HTTP `:8088` is now a compatibility fallback behind the HTTPS deployment.
> Keep the historical findings for context, but do not treat the original
> "Critical" summary as the current state without reading the remediation
> section.

> The working tree was not clean during the audit: it contained uncommitted control/gateway/replica work. Findings reflect the working tree as reviewed. No source files were modified and nothing was committed. The only file created is this report.

---

## Executive summary

The application has a solid baseline for password hashing, JWT signing, refresh-token rotation, internal-route authentication and SQL safety. However, **production transport security and secret distribution are not acceptable for an admin panel that can deploy code as root over SSH**.

Two issues drive the overall rating:

1. **The admin panel and admin API are published over plain HTTP.** A network observer on the path can capture the admin password and/or the 8-hour admin bearer token. That token is enough to add a “server” controlled by the attacker, run the deployment script there, and receive all deployment secrets, or to run arbitrary deployments against managed nodes.
2. **Internal service traffic can cross the public internet in plaintext.** The gateway sends `X-Internal-Token` and user `Authorization` headers to whatever endpoint the registry selects. The production registry includes a second node addressed by public HTTP, and the node exposes backend ports directly. That token is effectively control-plane access: internal catalog/media/control endpoints accept arbitrary URLs, server records and deployment actions.

Additional important issues: the per-IP rate limit is trivially bypassable with `X-Forwarded-For`, admin login has no account lockout, every service/container receives every secret, the media SSRF guard only blocks loopback (not RFC1918/link-local/metadata), SSH host keys are accepted blindly while deployment scripts contain all secrets, and a secondary production node exposes backend ports 8904–8909 and gateway 8875 to the internet.

**Overall risk: Critical** until TLS, admin isolation, rate-limit trust and secret separation are fixed. The application code is otherwise reasonably disciplined; most findings are configuration/architecture or defense-in-depth, not remote code execution in the public request path.

### Verified-good baseline (short version)

- Argon2id password hashing; 48-byte opaque refresh tokens stored only as SHA-256 hashes; refresh rotation.
- JWT signature, issuer, expiry and token-type checks. Default development JWT secret and `alg=none` were **rejected** by production (401).
- All internal routers require `X-Internal-Token`; default development token was **rejected** on tested production services (401).
- Admin JWT carries an HMAC fingerprint of the current admin credentials; rotating the password/username invalidates old admin tokens.
- SQL is built through SQLAlchemy ORM/parameter binding; no user-controlled raw SQL found.
- React escapes manga titles/descriptions; no `dangerouslySetInnerHTML`/`innerHTML` in application source.
- `safeNextPath()` blocks protocol-relative, backslash and cross-origin `next=` redirects; no server-side redirect endpoint.
- Direct SSRF through `/api/v1/manga/import` with `127.0.0.1` / `169.254.169.254` was **blocked** by the parser host allowlist (`url_host_not_allowed`).
- No `.env`, `data.txt`, private keys or obvious token patterns are tracked in git or present in git history; `.dockerignore` excludes `.env`.
- SSH passwords are encrypted at rest, not returned by the API, and local logs contained only paramiko “Authentication (password) successful!” lines — no password values.

---

## Findings

Severity order: Critical → High → Medium → Low. “Confirmed” means observed at runtime or reproduced locally; “Code review” means the issue is clear from the code but was not exploited against production.

---

### Critical

#### C-01 — Admin panel and admin API are served over plain HTTP

**Files / evidence**
- `README.md:21-22` explicitly notes the demo runs over HTTP without TLS.
- Runtime: `https://85.192.37.58.nip.io:8443/admin` returns `200` with no `Strict-Transport-Security`, no CSP and no TLS listener; `https://85.192.37.58:8088` and `https://85.192.37.58` do not connect.
- `services/gateway/app/api.py:810-826` — admin login returns a bearer token in the JSON response body.
- `apps/web/src/api/admin.ts:181-192` — the admin token is kept in `sessionStorage` for 8 hours (`ADMIN_TOKEN_MINUTES=480`, `packages/manga_common/manga_common/config.py:77`).
- `services/control/app/deployer.py:274-279` — an admin-authenticated deployment can obtain/receive `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY`, `ADMIN_PASSWORD` on a target the admin controls.

**Impact**
Any attacker with a position on the network path (public Wi-Fi, ISP, BGP/route hijack, malicious proxy) can capture the admin password or token and then:
- add an attacker-controlled “server” and run a deploy, receiving the deployment secrets in the target’s `.env`;
- deploy/restart services on the real nodes;
- read the server inventory and audit log, and use failover/registry controls.

This is a control-plane compromise, not just a website defacement.

**Reproduction (authorized test only)**
```bash
# No TLS/HSTS; admin page is served over HTTP
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/admin"

# One authorized login was performed with the supplied credentials.
# The body and token are redacted here.
curl -sS -X POST "https://85.192.37.58.nip.io:8443/api/v1/admin/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"<redacted>","password":"<redacted>"}'
```

Observed: `200`, `token_type=bearer`, `expires_in=28800`; no TLS/HSTS anywhere. The login succeeded, so this was not a false positive caused by a disabled account.

**Fix (code/config level)**
1. Terminate TLS in front of both the SPA and `/api/`; redirect all HTTP to HTTPS; add HSTS after TLS works.
2. Restrict `/admin` and `/api/v1/admin/*` to a VPN/management IP allowlist or a separate admin hostname with mTLS; do not expose the admin panel to the whole internet.
3. Shorten `ADMIN_TOKEN_MINUTES` (e.g. 30–60) and add a server-side token version/`jti` denylist (see M-04).
4. Rotate the current admin password, `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY` and all SSH credentials after enabling TLS. Assume the old values were exposed.
5. Set cookies `Secure`/`HttpOnly` where applicable; do not put bearer tokens in URLs or logs.

**Status:** Confirmed (runtime + code).

---

#### C-02 — Internal token and user bearer tokens can travel over public plaintext HTTP

**Files / evidence**
- `services/gateway/app/clients.py:49` sets `X-Internal-Token` on the shared client; `:105-116` sends requests to an endpoint URL chosen from the runtime registry.
- `services/gateway/app/clients.py:272-276` forwards the user’s `Authorization` header to library endpoints.
- `services/gateway/app/routing.py:117-130` — stateful requests (`library`, `control`) use the first three available endpoints; stateless GETs use rendezvous hashing over all healthy endpoints, including non-local ones.
- `services/control/app/deployer.py:287-288` writes `REGISTRY_URL` and `REPLICA_SELF_URL` as `http://<public-host>:8088` / `http://<public-host>:8108` into every deployed server’s `.env`.
- `services/replica/app/config.py:48` defaults `registry_url` to `https://85.192.37.58.nip.io:8443/api/v1/registry`; `services/replica/app/sync.py:151-155` sends the internal token there.
- Runtime admin registry listed a secondary node with public HTTP endpoints such as `http://<secondary-node>:8907` (library), `:8904` (catalog), `:8909` (media), while those ports were reachable from the internet.

**Impact**
An on-path observer can capture:
- `X-Internal-Token`, which unlocks every `/internal/*` route: arbitrary media URL fetching, catalog mutation, SSH server inventory/deploy, replica bootstrap/promote;
- user `Authorization` bearer tokens, enabling account takeover;
- admin bearer tokens if an admin request is routed to a remote control endpoint.

Even without an on-path attacker, a compromised secondary node or a hijacked registry entry exposes all of these.

**Reproduction**
```bash
# Registry was read with the authorized admin session (values redacted).
# It contained public http:// endpoints for the secondary node.

# Backend ports are reachable directly, not only through nginx.
curl -sS -o /dev/null -w "%{http_code}\n" "http://<secondary-node>:8907/health"   # 200
curl -sS -o /dev/null -w "%{http_code}\n" "http://<secondary-node>:8909/docs"    # 200

# No token swaps plaintext for ciphertext: the service is HTTP-only.
curl -sS -o /dev/null -w "%{http_code}\n" "http://<secondary-node>:8907/internal/me/bookmarks"  # 401
```

This was not a traffic-capture test; it is a code-path/architecture finding confirmed by the registry contents and exposed HTTP services.

**Fix**
1. Put service-to-service traffic on WireGuard/TLS/mTLS, or keep every backend port on `127.0.0.1` and never route internal calls over the public interface.
2. Treat `X-Internal-Token` as a root-equivalent secret: rotate it, store it per service, and never send it to a public HTTP URL.
3. Do not let the gateway choose arbitrary public registry URLs unless they are on a trusted, encrypted network.
4. Bind all `/internal/*` services to loopback; expose only nginx on 443.
5. Rotate user/admin tokens after the transport fix if there is any chance of past interception.

**Status:** Confirmed by code + runtime registry/exposed ports. Traffic capture was not performed.

---

### High

#### H-01 — Rate limiting is bypassable via `X-Forwarded-For`; admin login has no lockout

**Files**
- `services/gateway/app/middleware.py:45-56` — limiter key is derived from the first `X-Forwarded-For` value.
- `services/gateway/app/api.py:66-70` — same trust for client IP metadata.
- `services/gateway/app/main.py:97-102` — same value used for routing identity.
- `infra/nginx/default.conf:20` — nginx uses `$proxy_add_x_forwarded_for`, which appends the real peer address but leaves the client-supplied first value in place.
- `services/gateway/app/api.py:810-826` — admin login is a normal route under the default 240/min bucket; there is no per-account lockout/backoff.

**Impact**
- Unlimited admin password guessing (subject only to network throughput) if an attacker rotates `X-Forwarded-For`.
- Bypass of the 10/min import limit, 60/min search limit and general 240/min limit: scraping/live-search abuse, catalog/DB growth, export/archive resource abuse.
- The admin credential observed in testing is weak by modern standards; combined with no lockout this is a realistic takeover path.

**Reproduction**
```bash
# Two different client-supplied IPs produce independent buckets; the same IP decrements.
for ip in 203.0.113.10 203.0.113.11 203.0.113.10; do
  curl -sS -o /dev/null -D - \
    -H "X-Forwarded-For: $ip" \
    "https://85.192.37.58.nip.io:8443/api/v1/chapters/00000000-0000-0000-0000-000000000000" \
    | grep -i x-ratelimit-remaining
done
```

Observed: `237`, `238`, `236` — changing the header resets the bucket. With the real client IP, the import endpoint hit `limit: 10`; changing `X-Forwarded-For` immediately allowed new requests. The admin login route uses the same default bucket (240/min) and has no lockout.

**Fix**
1. Do not trust a client-supplied `X-Forwarded-For` first value. Use nginx’s `X-Real-IP`/`$remote_addr` on the trusted proxy, or parse `X-Forwarded-For` from the rightmost trusted hop.
2. Add a separate admin-login limiter, e.g. 5 attempts/min per `username + real IP`, with exponential backoff and a temporary lock after repeated failures.
3. Use Redis for a global limiter if more than one gateway replica is possible.
4. Add login alerting and optionally TOTP for the admin account.

**Status:** Confirmed (runtime).

---

#### H-02 — Every service/container/server receives every secret

**Files**
- `docker-compose.yml:39,59,83,103,123,139,161,195` — every service uses `env_file: .env`; the same file contains JWT, internal token, control key and admin password.
- `services/control/app/deployer.py:274-279` — the generated `.env` includes `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`.
- `services/control/app/deployer.py:304-306` — every deployed service uses the same `EnvironmentFile`.
- `services/control/app/deployer.py:387-390` — `.env` is `0640 root:<service-user>`; all services run as the same user.

**Impact**
- A parser SSRF/RCE, a media image-decoder bug, or a compromised secondary node yields the JWT signing key, the internal token, the control key and the admin password.
- The parser is the most exposed component (it fetches third-party content) yet it has the same secrets as the control plane.
- The `ADMIN_PASSWORD` is present on every app node even though only the gateway needs it.

**Reproduction**
Static only; verify with:
```bash
docker compose config | grep -n "JWT_SECRET\|INTERNAL_TOKEN\|ADMIN_PASSWORD"
# or inspect /opt/mangapoisk-reborn/.env on a deployed node (values redacted)
```

**Fix**
1. Split env files: `gateway.env` gets `ADMIN_PASSWORD`/admin settings; `parser.env` gets only parser settings; `media.env` only media settings; `control.env` only control/SSH settings.
2. Do not put `ADMIN_PASSWORD` on app nodes at all. Store only an Argon2id admin password hash or a separate admin identity in the gateway/control plane.
3. Use a secret manager (Vault, systemd `LoadCredential`, Docker secrets) instead of a single file.
4. Rotate all secrets after splitting, because they must be considered exposed to every service today.

**Status:** Confirmed (code).

---

#### H-03 — Media/parser SSRF guard only blocks loopback; private/link-local/metadata and redirects are allowed

**Files**
- `services/media/app/cache.py:50-62` — rejects only `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `.local`; it does not check RFC1918, link-local, CGNAT, metadata IPs, decimal/IPv4-mapped forms, or resolved DNS addresses.
- `packages/manga_common/manga_common/http.py:55` — `follow_redirects=True`; redirects are not revalidated by the media cache.
- `services/parser/app/adapters/base.py:304-318` — initial URL is host-checked, but redirects are followed by httpx; `ensure_robots_allowed`/`assert_allowed_url` are not applied to each redirect hop.
- `services/parser/app/adapters/mangalib.py:283-300` — `_page_url()` returns an arbitrary absolute `http(s)` URL when its host is not one of the three known CDN hosts. A user-generated/upstream chapter can therefore point a page URL at an internal address.
- `services/media/app/api.py:30-45` — `/internal/image?url=` accepts any URL after the incomplete check; this is reachable with the internal token, which is itself exposed over HTTP (C-02).

**Impact**
- Server-side requests to `169.254.169.254` (cloud metadata), `10/8`, `172.16/12`, `192.168/16`, `127.0.0.1` aliases and IPv4-mapped IPv6.
- Blind SSRF/port scanning of the internal network; interaction with internal services that perform state changes on GET (or with the leaked internal token, any method).
- A redirect from an allowed CDN host bypasses the allowlist entirely.
- Production sets `MEDIA_ALLOWED_HOSTS` to three CDN hosts, which mitigates the direct arbitrary-URL case; it does **not** mitigate redirects from those hosts or deployments where the allowlist is empty.

**Reproduction (local, no external requests)**
```bash
PYTHONPATH="packages/manga_common;services/media" .venv/Scripts/python.exe - <<'PY'
from manga_common.config import Settings
from app.cache import MediaCache
c = MediaCache(Settings(media_cache_dir="<temp>"))
for u in [
    "http://10.0.0.1/a.jpg",
    "http://192.168.1.1/a.jpg",
    "http://169.254.169.254/latest/meta-data/",
    "http://127.1/a.jpg",
    "http://[::ffff:127.0.0.1]/a.jpg",
]:
    try:
        c._validate_url(u)
        print("ALLOWED", u)
    except Exception:
        print("blocked", u)
PY
```

Observed: all five addresses above were **ALLOWED**; only the exact loopback names (`localhost`, `127.0.0.1`, `0.0.0.0`, `::1`) and `.local` suffixes are blocked by the current code.

**False-positive check:** direct SSRF via the public import endpoint was tested with `url=http://127.0.0.1:8005/...` and `url=http://169.254.169.254/...`; both were rejected by the parser host allowlist (`url_host_not_allowed`). The vulnerability is in the media proxy and in redirect handling, not in the import URL host check itself.

**Fix**
1. Resolve the hostname and reject every non-global address with `ipaddress.ip_address(...).is_private`, `.is_loopback`, `.is_link_local`, `.is_reserved`, `.is_multicast`, and reject IPv4-mapped IPv6 private addresses.
2. Disable redirects for image fetches or re-run the host/IP check on every `Location` hop (max 3 hops).
3. Restrict schemes to `http/https` and ports to 80/443; reject userinfo.
4. Keep `MEDIA_ALLOWED_HOSTS` mandatory in production and fail closed if unset.
5. Consider a dedicated egress proxy with DNS pinning and an internal-IP denylist.

**Status:** Confirmed locally; production allowlist partially mitigates.

---

#### H-04 — SSH host-key verification is disabled while deployment payloads contain all secrets

**Files**
- `services/control/app/ssh.py:35-36` — jump host uses `paramiko.AutoAddPolicy()`.
- `services/control/app/ssh.py:58-59` — target host uses `AutoAddPolicy()`.
- `services/control/app/deployer.py:360-388` — the deployment script is written over the SSH channel; the script includes the generated `.env` with `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY`, `ADMIN_PASSWORD` (lines 274-279) and is executed with `bash -s` (ssh.py:96).

**Impact**
An attacker who can MITM the control→target SSH connection (or DNS/host route) can present a new host key, receive the root SSH password and the full deployment script, and then execute commands as the SSH user on the target. Because the default SSH username is `root`, this is full infrastructure compromise. The documentation acknowledges “accept at first connect” (`docs/SERVER_MANAGER.md:86-88`) but not the secret-bearing payload consequence.

**Reproduction (lab only)**
Do not test against production. On a lab control instance, point a server record at a fake SSH server with a self-signed host key; `SSHRunner.connect()` will accept it and `run_script()` will send the script. The code path is deterministic.

**Fix**
1. Pin host keys in a managed `known_hosts` file and use `RejectPolicy` for unknown/changed keys.
2. Prefer SSH key authentication; disable password auth on target hosts.
3. Verify host-key fingerprints out of band when adding a server.
4. Never send long-lived admin secrets in a deployment script; fetch them from a secret manager on the target using a short-lived credential.

**Status:** Confirmed by code; not exploited.

---

#### H-05 — Secondary production node exposes backend service ports publicly

**Runtime evidence**
- `<secondary-node>:8904` (catalog), `:8905` (notifier), `:8907` (library), `:8908` (parser), `:8909` (media) and `:8875` (gateway) returned `200` on `/health` from the audit host.
- `:8904/docs`, `:8905/docs`, `:8907/docs`, `:8909/docs`, `:8875/docs` and `/openapi.json` were publicly readable; parser docs were disabled (`404`).
- The admin inventory showed this node with `bind_host=0.0.0.0`; the systemd unit generation uses that value directly (`services/control/app/deployer.py:315`).
- `docs/SERVER_MANAGER.md:68` says all backend ports should listen on `127.0.0.1`; the secondary node violates that.

**Impact**
- Bypasses nginx security headers and any future IP allowlist/WAF.
- Adds direct attack surface for FastAPI/uvicorn and every internal endpoint; only the static internal token stands between the internet and control/media/catalog mutation.
- Exposes OpenAPI schemas and service inventory to unauthenticated users.

**Reproduction**
```bash
for p in 8904 8905 8907 8908 8909 8875; do
  printf "%s " "$p"
  curl -sS -m 4 -o /dev/null -w "%{http_code}\n" "http://<secondary-node>:$p/health"
done
```

Observed: `200` for all except the non-HTTP scheduler/control ports. Default `<default-dev-internal-token>` was rejected (401) on catalog/parser/media, so this is not a default-token finding, but the ports should not be public.

**Fix**
1. Set `bind_host=127.0.0.1` for all services, or firewall the 8900/8875 range to the primary node/VPN only.
2. Expose only nginx on 443 publicly.
3. Disable `/docs`/`/openapi.json` on every service in production (see M-07).

**Status:** Confirmed (runtime).

---

#### H-06 — Production root SSH credentials and a GitHub PAT are stored in plaintext outside the repository

**Files / evidence**
- Workspace-level `../data.txt` (outside the git repo) contains reusable root SSH credentials for the production hosts and a GitHub personal access token. Values are **redacted** here and must not be copied into tickets, screenshots or commits.
- `repo/.env` is untracked/ignored but contains live-looking JWT/internal/control secrets and admin credentials. It is not in git history (verified), but it is plaintext on disk.

**Impact**
Anyone with access to the workstation, a backup, a synced folder, or a screenshot can obtain root SSH access to both production nodes and write access to the GitHub repository. This bypasses all application controls.

**Reproduction**
Do not print values. Verify presence with a redacted listing:
```bash
# Values deliberately replaced; do not run a command that prints them.
Get-Content ..\data.txt | ForEach-Object { $_ -replace '(?i)(ssh|token|password).*','<redacted>' }
```

**Fix**
1. Rotate the root SSH passwords and revoke/reissue the GitHub PAT immediately (least-privilege, expiring token).
2. Remove the plaintext file; store credentials in a password manager/secret manager.
3. Use per-host SSH keys and disable root password login.
4. Ensure backups/synced folders containing the workspace are encrypted and access-controlled.

**Status:** Confirmed presence (redacted); not committed to git.

---

### Medium

#### M-01 — Missing security headers/CSP/frame protection on the production web app and admin panel

**Files / evidence**
- Runtime `/admin` returned only `HTTP/1.1 200 OK` with no `Content-Security-Policy`, `X-Frame-Options`, `frame-ancestors`, `Permissions-Policy` or HSTS.
- API responses add `X-Content-Type-Options` and `Referrer-Policy` (`packages/manga_common/manga_common/service.py:74-78`) but no CSP.
- `infra/nginx/default.conf:11-13` has only `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`; it lacks CSP/HSTS/Permissions-Policy. The production nginx is not applying even these (runtime shows none).
- `apps/web/src/pages/AdminPage.tsx:105-111` adds a client-side `noindex` meta tag; this is not a substitute for headers.

**Impact**
- The admin UI can be framed; an attacker can lure an authenticated admin into clicking deploy/delete/failover controls (clickjacking). SessionStorage is per-tab, so exploitation requires the admin to navigate the same tab, but it is still a realistic UI-redress path.
- No CSP means any XSS (e.g. M-03) runs with full access to localStorage/sessionStorage.
- Version disclosure via `Server: nginx/1.28.3`.

**Reproduction**
```bash
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/admin"
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/api/v1/health"
```

**Fix**
Add at the nginx server block (and mirror in any CDN):
```nginx
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;
add_header X-Frame-Options "DENY" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
server_tokens off;
```
Adjust CSP for the boot loader/inline theme styles, ideally by removing inline script and using a nonce/hash.

**Status:** Confirmed (runtime).

---

#### M-02 — Anonymous export/archive jobs enable disk/memory exhaustion

**Files**
- `services/gateway/app/api.py:512-518` — `POST /chapters/{id}/exports` has no `require_user`; any anonymous caller can create an export for a known chapter.
- `services/media/app/exporter.py:98-116` — jobs are queued in-process; `max_pages` is 300 (`packages/manga_common/manga_common/config.py:56`), but there is no total-byte/disk quota.
- `services/media/app/exporter.py:176-181` — WebP/AVIF/GIF pages are decoded by Pillow and re-encoded; a 40 MB compressed image can expand to a very large pixel buffer.
- `services/media/app/archive.py:408-431` — chapter archiving fetches every page and can store large ZIPs; `ArchiveRequest.pages` has a minimum but no maximum (`services/media/app/archive.py:83`).
- `services/gateway/app/api.py:362-392` — `/manga/{id}/warm` requires auth but has no per-user quota/dedup window; a user can repeatedly request whole-title archiving.

**Impact**
An anonymous attacker can fill the media volume and consume CPU/RAM, causing reader/export/archive failure. The spoofable rate limiter (H-01) makes this practical. Pillow decompression-bomb behavior adds a memory-exhaustion path.

**Reproduction**
```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST "https://85.192.37.58.nip.io:8443/api/v1/chapters/<valid-chapter-uuid>/exports?format=cbz"
```

The route is reached without authentication (a random UUID produced `404`, not `401`); a valid chapter would create a job. No production job was created for this audit to avoid state changes.

**Fix**
1. Require an authenticated user for export creation and warm/archive operations; add per-user daily quotas.
2. Cap total decoded bytes and pages, not just page count; check free disk before starting.
3. Set `Image.MAX_IMAGE_PIXELS` to a conservative value and reject images above a pixel/dimension limit.
4. Run image conversion in a subprocess with memory/CPU limits and a timeout.
5. Add a global media-volume quota and alerting.

**Status:** Confirmed (code + route behavior); no destructive test.

---

#### M-03 — Media proxy can serve `image/svg+xml` inline (stored XSS precondition)

**Files**
- `services/media/app/cache.py:119-131` — accepts any `Content-Type` starting with `image/`; `_EXTENSIONS` (`:15-22`) does not include SVG, but `mimetypes.guess_extension("image/svg+xml")` returns `.svg`, and the file is served as `image/svg+xml`.
- `services/media/app/api.py:30-45` — `FileResponse` with the upstream content type; no `Content-Disposition: attachment`.
- `services/gateway/app/api.py:469-495` — the public image route forwards upstream `content-type` and serves it from the same origin as the SPA.
- `services/parser/app/adapters/mangalib.py:283-300` — arbitrary absolute image URL can be accepted from a user-generated chapter (precondition; production allowlist narrows it).

**Impact**
If an attacker can get a malicious SVG into the archive/cache (via an allowed CDN, an upstream chapter with an attacker-controlled page URL, or a compromised source), the public image URL renders attacker JavaScript on the site origin. That can read localStorage (user access/refresh tokens) and, if an admin opens the image URL, sessionStorage (admin token). This is a high-impact chain but requires an upstream/allowlist precondition, hence Medium.

**Reproduction (code-level)**
```bash
PYTHONPATH="packages/manga_common;services/media" .venv/Scripts/python.exe -c \
  "from app.archive import _extension_for; from pathlib import Path; print(_extension_for('image/svg+xml', Path('x')))"
# -> .svg
```

**Fix**
1. Allow only `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/avif`; reject `image/svg+xml` and all other types.
2. Re-encode every fetched image with Pillow to a raster format and strip metadata.
3. Serve media from a separate origin/subdomain with `Content-Security-Policy: default-src 'none'; sandbox` and `Content-Disposition: attachment` for non-raster types.
4. Add `X-Content-Type-Options: nosniff` (already present) and a CSP on the main origin.

**Status:** Code confirmed; production allowlist mitigates; no production PoC.

---

#### M-04 — Access tokens cannot be revoked; admin logout is client-side only

**Files**
- `packages/manga_common/manga_common/auth.py:38-59` — access tokens are stateless and carry no `jti`/session version.
- `packages/manga_common/manga_common/security.py:43-49` — `require_user` only verifies signature/expiry; it does not check the user’s `is_active` on every request.
- `services/library/app/service.py:248-251` — `revoke_all()` only revokes refresh tokens.
- `services/library/app/service.py:142-159` — refresh rotation revokes the old refresh token, but access tokens remain valid.
- `apps/web/src/pages/AdminPage.tsx:250-256` — admin logout only removes the token from sessionStorage.
- `packages/manga_common/manga_common/config.py:77` — admin tokens last 480 minutes.

**Impact**
A stolen access token remains usable for up to 30 minutes after logout/password reset/account disable; a stolen admin token remains usable for up to 8 hours and logout does not invalidate it. Credential rotation does invalidate admin tokens (good), but ordinary logout does not.

**Reproduction**
Code-level. A token issued before `POST /internal/me/logout-all` continues to authenticate until `exp`; no denylist/version is consulted.

**Fix**
1. Add a `token_version`/`session_version` claim per user and admin, checked on every request; increment it on logout-all, password change, account disable and admin logout.
2. Or maintain a Redis denylist of `jti` values until expiry.
3. Shorten admin access tokens to 30–60 minutes; use a refresh/session mechanism for the panel.
4. Check `User.is_active` on user endpoints (library already does for `/me`, but gateway-local auth does not).

**Status:** Confirmed (code).

---

#### M-05 — Control secret is not validated in production; SSH password encryption uses a single SHA-256

**Files**
- `packages/manga_common/manga_common/config.py:116-127` — production validation checks JWT, internal token and admin password but **not** `control_secret_key`.
- `packages/manga_common/manga_common/config.py:78` — default `control_secret_key = "dev-control-secret-change-me"`.
- `services/control/app/crypto.py:13-15` — `Fernet(base64(SHA256(secret)))`, no salt/KDF/work factor.
- `services/control/app/deployer.py:276` — the same control secret is copied to every deployed server.

**Impact**
If `CONTROL_SECRET_KEY` is left default/weak and the control SQLite DB is obtained (backup, path traversal, node compromise), all stored SSH passwords can be decrypted offline. Because the key is also on every app node, a parser/media compromise may expose it even if the control DB is on another host.

**Reproduction**
```bash
# Check the production validation code path: it never mentions control_secret_key.
grep -n "control_secret_key" packages/manga_common/manga_common/config.py
# -> only the default definition; no validation entry.
```

**Fix**
1. Add `control_secret_key` to `validate_production_secrets()`; require at least 32 random bytes and reject `dev-*`.
2. Derive the Fernet key with HKDF/scrypt/PBKDF2 and a per-record salt; store the salt with the ciphertext.
3. Use a dedicated key management service or OS keyring; do not distribute it to app nodes.
4. Rotate all encrypted SSH passwords after changing the key.

**Status:** Confirmed (code).

---

#### M-06 — Admin server fields are interpolated into shell/systemd units without validation

**Files**
- `services/control/app/schemas.py:22-28` — `host`, `public_host` and `bind_host` are only length-limited; `bind_host` accepts arbitrary text.
- `services/control/app/deployer.py:293-295` — `public_host` is inserted into `PUBLIC_WEB_URL`/`PUBLIC_API_URL`/`CORS_ORIGINS`.
- `services/control/app/deployer.py:315` — `bind_host` is inserted into `ExecStart=... --host {bind_host} ...` inside a systemd unit.
- `services/control/app/deployer.py:309-341` — `User={user}`, `Group={user}`, `WorkingDirectory={paths}` are also template-interpolated.

**Impact**
An authenticated admin can inject newlines into a systemd unit (for example an extra `ExecStartPre=` directive) or malformed values into generated URLs. The heredocs are quoted, so this is not direct shell interpolation; the risk is unit-directive injection and broken service configuration. This is post-auth, and a full admin can already deploy/SSH, so it is not a privilege boundary by itself; however, it turns a stolen/clickjacked admin session into service-user code execution on managed nodes and can cause accidental outages.

**Reproduction**
Do not test on production. On a lab control instance, create/update a server with `bind_host` containing a newline plus an `ExecStartPre=` directive, then deploy; the generated unit contains the extra directive. Static inspection is sufficient.

**Fix**
1. Validate `bind_host` with `ipaddress.ip_address` or a strict hostname regex; allow only `127.0.0.1`, `0.0.0.0` or explicit interface IPs.
2. Validate `public_host`/`host` as DNS names/IPs, not arbitrary text.
3. Generate unit files through a template with explicit escaping, or use systemd drop-ins written with checked values; never concatenate raw fields into `ExecStart`.
4. Reject control characters/newlines in all admin string fields.

**Status:** Code confirmed; admin-only.

---

#### M-07 — Public API docs and internal service docs are exposed

**Files / evidence**
- `packages/manga_common/manga_common/service.py:39-42` — `docs_url`/`openapi_url` are enabled by default and only parser disables them in production (`services/parser/app/main.py:64`).
- Runtime: `https://85.192.37.58.nip.io:8443/docs` and `/openapi.json` returned `200`; `<secondary-node>:8904/docs`, `:8905/docs`, `:8907/docs`, `:8909/docs` returned `200`.
- `docs/API.md` documents admin/internal endpoints publicly in the repo as well.

**Impact**
Information disclosure: internal route names, schemas, admin endpoints and error models are visible to unauthenticated users, reducing the effort for targeted attacks. No secrets are exposed directly.

**Fix**
Disable docs/OpenAPI for every service in production (`docs=False` when `environment == "production"`), or protect them behind the internal token/admin network. Keep the public API contract in a separately published, curated document.

**Status:** Confirmed (runtime).

---

#### M-08 — User authentication hardening gaps

**Files**
- `services/library/app/service.py:102-104` — registration returns `409 email_taken`, enabling account enumeration.
- `packages/manga_common/manga_common/schemas.py:163-171` — password policy is only 8–128 characters; no breached-password/complexity check.
- `services/library/app/api.py` — no password-reset/forgot-password/email-verification routes exist.
- `services/gateway/app/api.py:810-826` — admin login has no MFA/lockout; user login has no per-account throttle (`services/library/app/service.py:122-140`).
- `services/gateway/app/api.py` — registration is open to the internet.

**Impact**
Account enumeration, spam account creation, credential stuffing and inability to recover a compromised/lost account. Severity varies with exposure; the rate-limit bypass (H-01) makes brute force easier.

**Fix**
1. Return a generic “check your email” response for registration and implement email verification.
2. Add a password reset flow with single-use, short-lived tokens.
3. Add per-account login throttling and optional TOTP.
4. Check passwords against a breached-password list; require 12+ characters.
5. Add CAPTCHA/registration abuse controls if the instance is public.

**Status:** Code confirmed; no password reset is present.

---

### Low

#### L-01 — `mp_client` routing cookie is client-controlled and lacks `Secure`/`HttpOnly`

`services/gateway/app/main.py:88-116` reads `mp_client` or `X-Client-ID`, truncates to 128 chars, and uses it as the rendezvous-hash key. The cookie is set with `httponly=False`, `samesite="lax"` and no `secure`. It is not an authentication cookie, but an attacker can pin a victim or themselves to a specific backend node (including a less-monitored secondary), and the value is not signed.  
**Fix:** sign the value, ignore client-supplied routing IDs for security decisions, set `Secure`/`HttpOnly` if it must be a cookie, and cap/validate the format. **Status:** Code confirmed; Low.

#### L-02 — Frontend URL helper allows `javascript:`/`data:` and chapter external links are not scheme-checked

`apps/web/src/api/client.ts:216-228` returns any URL with a scheme unchanged. `apps/web/src/pages/ReaderPage.tsx:728` and `apps/web/src/components/ChapterRow.tsx:67` use `href={chapter.url}`. Chapter URLs are normally constructed from validated adapter URLs, but a bad upstream/DB value could become `javascript:` and execute on click. No production instance was found with such a value.  
**Fix:** allow only `https:`/`http:` and expected hosts in `resolveApiUrl`; validate `ChapterOut.url` on the server and reject non-HTTP(S). **Status:** Code confirmed; latent.

#### L-03 — Dependencies and CI are not pinned/limited

- Python requirements use ranges (`fastapi>=0.115,<1`, `Pillow>=10.4,<13`, etc.) with no lock file or hashes; Docker images use mutable tags (`python:3.12-slim`, `postgres:16-alpine`, `nginx:1.27-alpine`).
- `.github/workflows/ci.yml` has no `permissions:` block (default token permissions), and actions are referenced by tag (`actions/checkout@v4`) rather than commit SHA.
- No `pip-audit`/`npm audit`/Dependabot/SBOM step.
- No obvious known-vulnerable version was found in the installed dev environment (FastAPI 0.162, PyJWT 2.15, Pillow 12.3, cryptography 50, paramiko 5.1 at audit time); the issue is reproducibility and supply-chain exposure, not a specific CVE.

**Fix:** add `permissions: contents: read`, pin actions by SHA, lock Python deps (uv/pip-tools) and Docker digests, enable Dependabot, run `pip-audit`/`npm audit` in CI. **Status:** Code review.

**Partial remediation (2026-11-13, #77):** Pillow 13.0.0 and cryptography 50.0.2 floors are pinned in the affected service requirements and the updated environment passes `pip-audit` with 0 known vulnerabilities; see `DEPENDENCIES.md`. Lock files, action SHA pinning, Dependabot and a CI audit gate remain open.

#### L-04 — Compose defaults use weak internal credentials and no resource limits

`docker-compose.yml:9` uses `POSTGRES_PASSWORD: manga`; Redis has no password (`:21-24`); no `read_only`, `cap_drop`, `security_opt` or resource limits. These services are on an internal network with no published ports, so this is Low for the compose deployment, but it becomes relevant if the network is shared or a port is accidentally published.  
**Fix:** generate DB/Redis passwords from `.env`, add `cap_drop: [ALL]`, `read_only: true`, `tmpfs`, memory/CPU limits. **Status:** Code review.

#### L-05 — Export download path is taken from `job.json` without containment check

`services/media/app/exporter.py:256-263` joins `_job_dir(job_id)` with `state.filename` loaded from `job.json`; no `.resolve()`/parent check. The filename is normally generated by `slugify`, so this requires local tampering with the job directory or a future import path.  
**Fix:** `path = (dir / filename).resolve(); if path.parent != dir.resolve(): raise`. **Status:** Code review; Low.

#### L-06 — Replica downloads are unbounded and bootstrap accepts arbitrary peer URLs

`services/replica/app/sync.py:590-635` streams downloads to disk with no maximum size; expected size/checksum are checked only after the download. `services/replica/app/api.py:92-101` accepts an arbitrary `source` URL for bootstrap (internal token required). A malicious/compromised peer can fill the disk before verification. The service is new/uncommitted and was not deployed on the audited nodes.  
**Fix:** enforce `Content-Length`/max bytes during streaming, verify checksum incrementally, restrict bootstrap sources to the registry/VPN. **Status:** Code review; Low/Medium if replica is enabled.

#### L-07 — Demo/smoke scripts create known-password accounts

`scripts/seed_demo.py:17-18` defaults to `demo@example.com` / `<documented-demo-password>`; `scripts/smoke_test.py:63-70` creates `smoke-*` users with a fixed password. These are intended for local testing, but running them against production leaves known credentials. The demo credentials were tested against production and **did not** work (`401`), so no such account was found.  
**Fix:** refuse to run when `ENVIRONMENT=production`, require an explicit password, delete test users, document “never run in prod.” **Status:** Code confirmed; production check negative.

#### L-08 — Validation errors may echo submitted passwords/tokens in 422 responses

FastAPI’s default `RequestValidationError` response includes an `input` field. For `/auth/login`, `/auth/register`, `/auth/refresh` and `/admin/login`, a validation failure (e.g. password >128 chars) can echo the submitted secret back in the response and into any body-logging proxy. The client already knows the value, but logs/APM may capture it.  
**Fix:** add a custom validation handler that redacts keys named `password`, `refresh_token`, `access_token`, `token`, `secret`; keep the parser’s existing handler pattern. **Status:** Code review; Low.

#### L-09 — Admin username check short-circuits before password comparison

`services/gateway/app/api.py:812-815` uses `constant_time_compare(username) and constant_time_compare(password)`. A wrong username skips the password comparison, so response timing can reveal whether the username is valid. Combined with H-01, this assists targeted guessing.  
**Fix:** compute both comparisons and combine without short-circuit, or use a dummy hash/verify path. **Status:** Code review; Low.

#### L-10 — Production CORS list includes localhost/Capacitor origins

`services/control/app/deployer.py:295` writes `http://localhost:5173`, `http://localhost:8080`, `capacitor://localhost` and `https://localhost` in addition to the public origin. Bearer auth means a random website cannot automatically send credentials, and evil origins are not reflected, but the list is broader than necessary for production.  
**Fix:** restrict production CORS to the real public origin(s); keep dev origins only in development. **Status:** Code review; Low.

---

## What was verified safe / false-positive checks

| Area | Result |
|---|---|
| JWT default secret | Forged HS256 token signed with `<default-dev-jwt-secret>` against production `/api/v1/auth/me` → **401**. Not using the development default. |
| JWT `alg=none` | Unsigned token against production `/api/v1/library/bookmarks` → **401**. |
| Internal auth | All `/internal/*` routers declare `require_internal_token`; production catalog/parser/media rejected the default `<default-dev-internal-token>` → **401**. |
| Admin auth bypass | `/api/v1/admin/me`, `/servers`, `/registry`, `/audit` without token → **401**. |
| Admin token rotation | `admin_auth_version()` HMAC includes username+password; code/tests show old `av` fails after rotation. |
| SSRF via import URL | `POST /manga/import` with `http://127.0.0.1:8005/...` and `http://169.254.169.254/...` → parser `url_host_not_allowed`. Direct import SSRF is blocked; the media proxy remains the gap (H-03). |
| SQL injection | Repository code uses SQLAlchemy expressions/bound parameters; no raw user SQL. `ilike` wildcards are not injection. |
| CSRF | Auth is `Authorization: Bearer`, not cookies. State-changing requests with `Content-Type: application/json` trigger CORS preflight; evil origin received no `Access-Control-Allow-Origin`. No cookie-based session to forge. |
| Open redirect | `safeNextPath()` rejects `//`, `/\`, and cross-origin URLs via `new URL()`; tested by code review. No server redirect endpoint. |
| DOM XSS | No `dangerouslySetInnerHTML`/`innerHTML` in application source; manga titles/descriptions/genres are React text nodes. Telegram HTML and export HTML escape their strings. |
| Path traversal | Export names pass through `slugify`; replica archive names use a strict `^[A-Za-z0-9][A-Za-z0-9._-]{0,191}\.zip$`; media cache keys are SHA-256; chapter IDs are UUIDs. No user-controlled filesystem path found in the normal flow. |
| SSH password exposure | `ServerOut` has no password; `SSHTarget.__repr__` redacts it; audit filters keys containing `password`; local logs contained only “Authentication (password) successful!”, no password values. |
| Git secrets | `.env` and `data.txt` are not tracked; `git log -G 'ghp_|github_pat_|AKIA|PRIVATE KEY'` found no commits; `.dockerignore` excludes `.env` and `data/`. |
| CORS wildcard | No `*` with credentials; allowed origin is reflected only for configured origins. |
| Primary node exposure | `85.192.37.58` exposed only 8088; 8000–8006/8100–8108 were closed/filtered. (The secondary node is the exception — H-05.) |
| Default demo account | `demo@example.com` / the documented demo password → **401**; not present in production. |
| Password hashing | Argon2id with `time_cost=3, memory_cost=65536, parallelism=4`; refresh tokens are 48-byte URL-safe random values stored as SHA-256. |
| SQL/ORM migrations | Runtime migrations use fixed DDL strings, no user input. |

**Known false positives / non-issues to avoid re-reporting**

- The public import URL route is not an SSRF primitive by itself; the adapter host allowlist blocks private hosts (tested).
- `/api/v1/chapters/{id}/images/{n}` does not accept an arbitrary URL from the client; it only accepts chapter UUID + page number.
- The `admin` JWT cannot be obtained from a normal user token: `require_admin` additionally requires the `av` fingerprint derived from the admin password and JWT secret.
- `constant_time_compare` correctly uses `secrets.compare_digest`; timing leakage is limited to the username short-circuit (L-09).
- `X-Frame-Options` exists in `infra/nginx/default.conf`, but not in the observed production response; this is a deployment/config gap, not proof the header is never configured.

---

## Prioritized remediation checklist

### P0 — today

- [ ] Put the admin panel and `/api/v1/admin/*` behind HTTPS and a VPN/IP allowlist; enable HSTS and HTTP→HTTPS redirect.
- [ ] Rotate the admin password, `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY`, all SSH credentials and the GitHub PAT. Assume they are compromised (C-01, C-02, H-06).
- [ ] Fix rate-limit IP trust: use nginx `X-Real-IP`/`$remote_addr` or trusted-proxy parsing; add a dedicated admin-login lockout/backoff (H-01).
- [ ] Bind every backend service to `127.0.0.1` or firewall the 8900/8875 range; expose only nginx 443 (H-05, C-02).
- [ ] Split secrets per service; remove `ADMIN_PASSWORD` from parser/media/catalog nodes; use Docker/systemd secrets (H-02).
- [ ] Enable SSH host-key pinning and key-only auth; stop sending all secrets in the deploy script (H-04).

### P1 — this week

- [ ] Implement private/link-local/reserved IP rejection and per-redirect revalidation in media/parser fetch paths; keep `MEDIA_ALLOWED_HOSTS` mandatory (H-03).
- [ ] Require auth and quotas for export/warm jobs; cap total bytes/pixels and add disk checks (M-02).
- [ ] Restrict media to raster MIME types and re-encode; serve media from a separate origin (M-03).
- [ ] Add CSP, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, Permissions-Policy, HSTS and `server_tokens off` (M-01).
- [ ] Add token version/`jti` invalidation; shorten admin tokens; server-side admin logout (M-04).
- [ ] Validate `control_secret_key` in production and replace SHA-256 with a salted KDF (M-05).
- [ ] Validate `host`/`public_host`/`bind_host` and escape systemd/shell templates (M-06).

### P2 — next sprint

- [ ] Disable `/docs`/`/openapi.json` in production for all services (M-07).
- [ ] Add email verification, generic registration responses, password reset, breached-password checks, per-account throttling and optional MFA (M-08).
- [ ] Move user refresh tokens out of localStorage where feasible (HttpOnly secure cookie + CSRF protection), or add a strict CSP and XSS testing if localStorage is retained.
- [ ] Pin Python/Node/Docker dependencies and actions; add `permissions: contents: read`, Dependabot, `pip-audit`, `npm audit` (L-03).
- [ ] Harden compose: generated DB/Redis passwords, `cap_drop`, `read_only`, resource limits (L-04).
- [ ] Add path containment in export download; bound replica downloads and restrict bootstrap peers (L-05, L-06).
- [ ] Remove/rotate demo scripts from production workflows; add a production guard (L-07).
- [ ] Add a custom 422 handler that redacts password/token fields (L-08).

### P3 — hardening / monitoring

- [ ] Sign or ignore the `mp_client` routing cookie; set `Secure`/`HttpOnly` if retained (L-01).
- [ ] Restrict `resolveApiUrl`/chapter links to `http(s)` and expected hosts (L-02).
- [ ] Add login alerting, audit alerts for new servers/deploys/failovers, and a WAF/IDS in front of nginx.
- [ ] Add a `security.txt` and a vulnerability disclosure policy.
- [ ] Re-run this audit after remediation; add regression tests for SSRF/scheme validation and rate-limit trust.

---

## Commands and tests used (redacted)

All commands target the authorized audit deployment. Passwords, tokens, cookies and `.env` values are replaced with `<redacted>`. No brute force or destructive writes were performed.

### Static review

```bash
# Repository inventory and working-tree state
git status --short
git ls-files | grep -E '(^|/)\.env$|data\.txt|\.pem$|\.key$|id_rsa'
git log --all --oneline -G 'ghp_[A-Za-z0-9]{20,}|github_pat_|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY'

# Secret/config hot spots
grep -RIn "X-Forwarded-For\|admin_password\|internal_token\|control_secret_key" \
  services packages | head -100
grep -RIn "AutoAddPolicy\|follow_redirects\|MEDIA_ALLOWED_HOSTS" services packages
grep -RIn "dangerouslySetInnerHTML\|innerHTML\|localStorage\|sessionStorage" apps/web/src
grep -RIn "create_export\|archive_chapter\|warm_manga\|export_download" services
```

### Production HTTP probes

```bash
# Basic reachability / headers
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/"
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/admin"
curl -sS -D - -o /dev/null "https://85.192.37.58.nip.io:8443/api/v1/health"
curl -sS -o /dev/null -w "%{http_code}\n" "https://85.192.37.58.nip.io:8443/docs"
curl -sS -o /dev/null -w "%{http_code}\n" "https://85.192.37.58.nip.io:8443/openapi.json"

# Unauthenticated admin endpoints must be 401
for p in /api/v1/admin/me /api/v1/admin/servers /api/v1/admin/registry /api/v1/admin/audit; do
  curl -sS -o /dev/null -w "$p %{http_code}\n" "https://85.192.37.58.nip.io:8443$p"
done

# Authorized admin login (values redacted); output only shape
curl -sS -X POST "https://85.192.37.58.nip.io:8443/api/v1/admin/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"<redacted>","password":"<redacted>"}' \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['token_type'], d['expires_in'], d['username'])"
```

Observed: admin page `200` over HTTP with no CSP/HSTS; `/docs` and `/openapi.json` `200`; admin endpoints `401` without a token; authorized login returned `bearer 28800` (token redacted).

### Rate-limit trust test

```bash
for ip in 203.0.113.10 203.0.113.11 203.0.113.10; do
  curl -sS -o /dev/null -D - \
    -H "X-Forwarded-For: $ip" \
    "https://85.192.37.58.nip.io:8443/api/v1/chapters/00000000-0000-0000-0000-000000000000" \
    | grep -i 'x-ratelimit-remaining'
done
```

Observed: `237`, `238`, `236` — different header values reset the bucket; the same value decrements. The import endpoint separately returned `limit: 10`, and changing the header allowed a new request.

### Port exposure test

```bash
for p in 8000 8001 8002 8003 8004 8005 8006 8100 8101 8102 8103 8104 8105 8106 8107 8108; do
  # TCP connect only; no service exploitation
  Test-NetConnection 85.192.37.58 -Port $p -InformationLevel Quiet
done

for p in 8904 8905 8907 8908 8909 8875; do
  curl -sS -m 4 -o /dev/null -w "$p %{http_code}\n" "http://<secondary-node>:$p/health"
done
```

Observed: primary node only 8088 open; secondary node 8904/8905/8907/8908/8909/8875 open.

### SSRF checks

```bash
# Direct import URL is blocked by the parser host allowlist (expected safe)
curl -sS -X POST "https://85.192.37.58.nip.io:8443/api/v1/manga/import" \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-For: 198.51.100.44" \
  -d '{"source":"mangalib","url":"http://127.0.0.1:8005/internal/servers"}'
# -> {"error":{"code":"upstream_error", ... "url_host_not_allowed" ...}}

# Local media-cache validator reproduction (no external requests)
PYTHONPATH="packages/manga_common;services/media" .venv/Scripts/python.exe - <<'PY'
from manga_common.config import Settings
from app.cache import MediaCache
c = MediaCache(Settings(media_cache_dir="<temp>"))
tests = [
    "http://10.0.0.1/a.jpg",
    "http://192.168.1.1/a.jpg",
    "http://169.254.169.254/latest/meta-data/",
    "http://127.1/a.jpg",
    "http://[::ffff:127.0.0.1]/a.jpg",
]
for url in tests:
    try:
        c._validate_url(url)
        print("ALLOWED", url)
    except Exception:
        print("blocked", url)
PY
```

Observed: all five were `ALLOWED`; only exact `127.0.0.1`/`::1` are rejected by the current code.

### JWT/secret validation checks

```bash
# Forged with the development default secret; token not printed
.venv/Scripts/python.exe - <<'PY'
import time, uuid, httpx, jwt
now = int(time.time())
payload = {"sub": str(uuid.uuid4()), "role": "user", "type": "access",
           "iss": "mangapoisk-reborn", "iat": now, "exp": now + 300}
token = jwt.encode(payload, "<default-dev-jwt-secret>", algorithm="HS256")
r = httpx.get("https://85.192.37.58.nip.io:8443/api/v1/auth/me",
              headers={"Authorization": "Bearer " + token}, timeout=15)
print("default-secret", r.status_code)
PY
# -> default-secret 401

# alg=none token (unsigned); token not printed
.venv/Scripts/python.exe - <<'PY'
import time, uuid, httpx, jwt
now = int(time.time())
payload = {"sub": str(uuid.uuid4()), "role": "user", "type": "access",
           "iss": "mangapoisk-reborn", "iat": now, "exp": now + 300}
token = jwt.encode(payload, None, algorithm="none")
r = httpx.get("https://85.192.37.58.nip.io:8443/api/v1/library/bookmarks",
              headers={"Authorization": "Bearer " + token}, timeout=15)
print("alg-none", r.status_code)
PY
# -> alg-none 401
```

### Other checks

```bash
# CORS: allowed origin reflects, evil origin does not
curl -sS -D - -o /dev/null -H "Origin: https://85.192.37.58.nip.io:8443" \
  "https://85.192.37.58.nip.io:8443/api/v1/health" | grep -i access-control
curl -sS -D - -o /dev/null -H "Origin: http://evil.example" \
  "https://85.192.37.58.nip.io:8443/api/v1/health" | grep -i access-control

# Default demo account is absent
curl -sS -X POST "https://85.192.37.58.nip.io:8443/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"<documented-demo-password>"}'
# -> 401

# Export creation route is reached without authentication (random UUID -> 404, not 401)
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST "https://85.192.37.58.nip.io:8443/api/v1/chapters/00000000-0000-0000-0000-000000000001/exports?format=cbz"
# -> 404

# Warm endpoint requires auth (401)
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST "https://85.192.37.58.nip.io:8443/api/v1/manga/00000000-0000-0000-0000-000000000001/warm"
# -> 401
```

### Reliability note

The primary deployment was intermittently unreachable during the audit (`Connection reset` / timeout), then recovered. This is consistent with a concurrent deployment/restart by the development session; no DoS test was performed. Findings that depend on runtime evidence were captured while the service was healthy and were re-checked after recovery where possible.

---

## Top 5 issues for the main agent

1. **TLS and admin isolation (C-01).** Put `/admin` and `/api/v1/admin/*` behind HTTPS + VPN/IP allowlist; rotate the admin password and tokens now. This is the fastest path to full infrastructure compromise.
2. **Rate-limit trust + admin lockout (H-01).** Stop trusting client `X-Forwarded-For`; use `X-Real-IP`/trusted-proxy parsing; add a 5/min admin-login limiter with backoff. The current limiter is bypassable with one header.
3. **Secret separation (H-02).** Remove `ADMIN_PASSWORD`, `CONTROL_SECRET_KEY`, `INTERNAL_TOKEN` and `JWT_SECRET` from parser/media/catalog/notifier environments; use per-service secrets and a secret manager. Rotate everything afterward.
4. **Encrypt/isolate internal traffic (C-02, H-05).** Bind backend ports to `127.0.0.1`, firewall the secondary node, and use WireGuard/mTLS for service-to-service calls. The internal token must never cross public HTTP.
5. **SSRF and SSH trust (H-03, H-04).** Add private/link-local/metadata IP checks and redirect revalidation to media/parser fetches; pin SSH host keys and use key-only auth. Both are currently one misconfiguration away from internal-network or deployment compromise.

### Quick fixes I recommend

- Add `add_header Strict-Transport-Security`, CSP with `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Permissions-Policy`, and `server_tokens off` to the production nginx server block.
- Set `MEDIA_ALLOWED_HOSTS` in production (already set by the deployer) and make it **mandatory**; fail startup if empty.
- Replace the direct `X-Forwarded-For` read with `request.headers["X-Real-IP"]` from nginx, or a helper that only trusts the rightmost proxy hop.
- Add `control_secret_key` and length/entropy checks to `validate_production_secrets()` and call it from control/media/parser/notifier/replica.
- Change the control `ServerCreate.bind_host` default from `0.0.0.0` to `127.0.0.1`; require an explicit opt-in to expose.
- Add a `token_version` claim and check it in `require_user`/`require_admin`; increment on logout-all/password change.
- Add a 422 exception handler that redacts `password`, `token`, `secret` and `refresh_token` keys.
- Add `permissions: contents: read` to CI and pin actions by SHA; add `pip-audit`/`npm audit`.

---

*No production data, secrets, tokens, passwords or cookies are reproduced in this document. Values were redacted at the source.*

---

## Remediation status (post-audit)

- **TLS / admin transport:** HTTPS is live at `https://85.192.37.58.nip.io:8443` with a Let's Encrypt certificate, HSTS, CSP, frame protection and TLS 1.2/1.3. HTTP `:8088` is kept only for compatibility and will be deprecated.
- **Admin login limiter:** fixed to persist failures; 5 failures per IP per 5 minutes returns 429; admin tokens were reduced to 60 minutes and are invalidated on credential rotation.
- **Rate-limit spoofing:** gateway and middleware now trust only nginx `X-Real-IP`/the socket peer, not client-supplied `X-Forwarded-For`.
- **Secret separation:** parser/catalog/library/media/replica no longer receive `ADMIN_PASSWORD` or `CONTROL_SECRET_KEY`; systemd loads a service-scoped env file. Gateway/control receive admin credentials; only control receives the Fernet key and deploy source.
- **SSRF:** media validates every DNS answer and every redirect hop, rejects private/loopback/link-local/reserved/metadata addresses and non-raster image types; `MEDIA_ALLOWED_HOSTS` remains mandatory in production.
- **Production secret validation:** placeholder `dev-*`/`change-me-*`, legacy admin and default control keys are rejected; admin/control checks are scoped to the services that use them.
- **Server-field injection:** names, hosts, bind hosts and SSH usernames reject newlines and shell metacharacters before they reach unit files.
- **Export exposure:** user-facing CBZ/PDF/HTML export UI was removed; the remaining public export routes are being removed/deprecated next.
- **Still recommended:** SSH host-key pinning/key-only auth, per-service JWT/INTERNAL secret split, access-token revocation versioning, VPN/IP allow-list for `/admin`, and backend mTLS/WireGuard for cross-node internal traffic.


