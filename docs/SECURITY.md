# Security policy

## Supported versions

Security fixes are applied to the current `main` branch and the latest release
line. Older releases are supported on a best-effort basis; upgrade to the latest
release before reporting an issue that may already be fixed.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for an exploitable vulnerability.

Use GitHub's private vulnerability reporting:

<https://github.com/geekAmis/mangapoiskAPI/security/advisories/new>

Include:

- affected service/version and commit;
- reproduction steps or a proof of concept;
- impact assessment;
- any suggested fix or compensating control.

You should receive an acknowledgement within 3 working days. Please allow time
for a fix and coordinated disclosure before publishing details.

## Security baseline

- Passwords are hashed with Argon2id; refresh tokens are opaque and stored only
  as SHA-256 hashes.
- JWTs validate signature, issuer, expiry and token type. Admin tokens carry a
  credential fingerprint and are invalidated when admin credentials rotate.
- Internal service routes require `X-Internal-Token`; production rejects
  development defaults.
- SSH passwords and integration/ad secrets are encrypted at rest with Fernet
  (`CONTROL_SECRET_KEY`). Rotating that key makes existing ciphertext
  unreadable, so plan a re-entry/rotation procedure.
- Production is HTTPS-only on **80/443**; `http://` and `www` redirect to
  apex HTTPS. `:8443` is legacy API only (APK 1.3.0), `:8088` redirects except
  `/ads.txt`. Admin endpoints should be restricted to a management network or
  allowlist.
- Rate limits use the trusted proxy address, and admin login has a dedicated
  lockout/backoff.

See [`SECURITY_AUDIT.md`](SECURITY_AUDIT.md) for the full audit and remediation
status.

## Dependency security

Dependency pins, audit cadence and the upgrade process are documented in
[`DEPENDENCIES.md`](DEPENDENCIES.md).

Current status (2026-11-13, issue #77):

- `Pillow` 12.3.0 -> 13.0.0 in `services/media`.
- `cryptography` 47.0.0 -> 50.0.2 in `services/control` and
  `services/notifier`.
- `pip-audit` on the updated environment: **0 known vulnerabilities**.
- `npm audit --omit=dev` in `apps/web`: **0 vulnerabilities**.
- The Python base image remains `python:3.12-slim`; Pillow 13 and
  cryptography 50 both publish compatible manylinux wheels, so no base image
  update or production `apt` change is required.

## Secrets

- Never commit `.env`, tokens, private keys or production credentials.
- Generate independent random values for `JWT_SECRET`, `INTERNAL_TOKEN` and
  `CONTROL_SECRET_KEY`.
- Rotate credentials after any suspected exposure, and rotate the admin
  password if an admin token may have leaked.
- Do not paste production secrets into issues, pull requests or chat.

## Deployment

Only the lead/release owner deploys. Dependency upgrades are merged after the
full test suite and `pip-audit` pass, then deployed in a controlled window with
a rollback path. See [`DEPENDENCIES.md`](DEPENDENCIES.md) and
[`DEPLOYMENT.md`](DEPLOYMENT.md).

---

# Security hardening — MangaPoisk Reborn

**Status:** 2026-11-13 (v1.3.2, `main` @ `affe7d0`)

**Scope:** production nodes `jump-83` (`83.141.92.137`) and `aeza`
(`85.192.37.58`), plus the repository configuration that must keep the
hardening in place.

**Related:** #71 (this work), #46 (launch audit), #60 (public internal/fallback
ports), `docs/SECURITY_AUDIT.md` (full 2026-11-11 audit).

This document describes the operational controls that are now in place, the
evidence collected, rollback procedures, and the risks that remain. It does not
contain passwords, tokens, private keys, cookies, or `.env` values.

---

## 1. Threat model

### Assets

- User accounts, refresh tokens, comments, bookmarks, reading history and
  downloads.
- Admin control plane: deployment, server inventory, failover, moderation.
- Secrets: JWT signing key, internal service token, control/Fernet key, admin
  credentials, SSH credentials, GitHub token, VAPID private key, Yandex client
  secret.
- Data at rest: SQLite databases (`catalog`, `library`, `comments`, `control`,
  `notifier`, `archives`), media cache, encrypted backups.
- Availability of the public catalogue, reader, media proxy and admin panel.

### Trust boundaries

1. **Internet → edge**: nginx TLS termination on 80/443; the only other
   public ports are legacy `:8443` (API for APK 1.3.0) and `:8088` (redirect,
   except `/ads.txt`).
2. **Edge → application services**: gateway and internal HTTP services. Several
   services are bound to loopback on the primary node; cross-node traffic and
   the remaining legacy ports are still a hardening item (#82/#79).
3. **Application → host**: systemd services run as `mangapoisk`; the control
   service can deploy as root over SSH. This is the highest-value boundary.
4. **Operator → production**: SSH with root password authentication today;
   GitHub push access from the workstation.
5. **Build/supply chain → production**: Python and npm dependencies, container
   images and GitHub Actions.

### Primary threats considered

- Credential stuffing / password guessing against SSH, admin login and user
  login.
- Theft of database files or backups from disk, a misconfigured service, or a
  world-readable path.
- Secret leakage through logs, error responses, process arguments or committed
  files.
- Compromise of an internet-facing parser/media component leading to internal
  network access or secret disclosure.
- Supply-chain compromise or a known-vulnerable dependency in the public request
  path.
- Loss of operator access during SSH/firewall hardening (lockout).

### Out of scope for this change

- Application code deployment, database schema/content changes, nginx changes,
  and merging feature branches.
- A full penetration test or traffic capture. The 2026-11-11 audit remains the
  reference for application-level findings.

---

## 2. Controls in place

### 2.1 Database and file permissions

- All SQLite databases and their `-wal`/`-shm` files are mode `640`, owner
  `mangapoisk:mangapoisk`. The data directory is `750`.
- Release/rollback database copies (`catalog.db.release-*`) were also `644` on
  the primary node and are now `640`.
- A systemd drop-in was added to every `mangapoisk-*.service` unit:

  ```ini
  [Service]
  UMask=0027
  ```

  This makes new files created by the services `640` (and new directories
  `750`) instead of inheriting a permissive shell/umask default. The drop-ins
  are in `/etc/systemd/system/<unit>.d/umask.conf`.
- The `mangapoisk` service user remains the owner; root can still read the
  files for backups and restore drills.

**Verification:** after restarting `mangapoisk-notifier` on the primary node,
`/proc/<pid>/status` showed `Umask: 0027`, and the recreated
`notifier.db-wal`/`notifier.db-shm` were `640`. On the edge node the library
service restarted with `Umask: 0027`; its database is `640`.

### 2.2 HTTP security headers

The public HTTPS endpoint returns:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Content-Security-Policy` with `frame-ancestors 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `default-src 'self'`.

The CSP is still broad (`script-src 'self' 'unsafe-inline'`, `connect-src http:
https:`, `img-src http: https:`). In v1.3.2 `script-src`/`frame-src` also allow
`https://yandex.ru`, `https://an.yandex.ru` and `https://yastatic.net` for the
RTB loader. It is functional but should be tightened after the boot
loader/inline theme code is moved to nonces or hashes. This is tracked as a
follow-up (#79); the RTB deploy only added the Yandex allowances.

### 2.3 SSH

Effective settings on both nodes after the change:

```text
MaxAuthTries 3
LoginGraceTime 20
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 3
PermitRootLogin yes
PasswordAuthentication yes
```

`PasswordAuthentication` and `PermitRootLogin` were intentionally **not**
disabled: the current operator workflow still uses root password login. The new
drop-in is `/etc/ssh/sshd_config.d/99-mangapoisk-hardening.conf`; it is validated
with `sshd -t` before `systemctl reload ssh`.

**Lockout protection used during the change:**

- A second SSH session was kept open.
- A transient systemd timer (`ssh-rollback-<timestamp>`) was scheduled before
  the reload. It would remove the drop-in, run `sshd -t`, and reload `sshd` if
  the operator did not cancel it after verification.
- A fresh SSH login was tested immediately after the reload; it succeeded.
- The timer was cancelled only after the new session and `sshd -T` were
  verified.

### 2.4 fail2ban

`fail2ban` 1.1.0 is installed, enabled at boot, and running on both nodes with a
single `sshd` jail:

```ini
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 <trusted peers> <operator egress IP>
bantime = 1h
findtime = 10m
maxretry = 5
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = %(sshd_log)s
```

The trusted-peer set includes `83.141.92.137`, `85.192.37.58`,
`85.192.30.224`, Tailscale `100.64.0.0/10` and the IPv6 Tailscale prefix.
The operator egress IP is added at install time and must be updated if it
changes; it is not committed to the repository.

**Verification:** `fail2ban-client -t` passed, `fail2ban-client status` shows
one jail (`sshd`), and `fail2ban-client status sshd` shows the journal backend
and banned attackers. A `TEST-NET-3` address (`203.0.113.250`) was banned and
unbanned to prove the action works; it was not a real client. Our own IP is in
`ignoreip` and was never banned. A fresh SSH login after enabling fail2ban
succeeded.

### 2.5 Rate limits

- **Admin login:** 5 failed attempts per IP per 5 minutes; the 6th returns
  `429 admin_rate_limited`. A successful login clears the bucket.
- **Gateway:** 240 requests/minute per IP; search 60/min; suggest 300/min;
  import 10/min; image reads 1200/min.
- **Comments:** 10-second create cooldown, 30 comments/day, 60-second duplicate
  window.
- **Reports:** one open report per user/comment (`report_exists`); there is no
  dedicated per-user report rate limit beyond the generic gateway limit. This is
  a remaining low/medium risk and a follow-up.
- Client IP selection uses nginx's `X-Real-IP` (overwritten with
  `$remote_addr`) and the socket peer, not the client-supplied first
  `X-Forwarded-For` value.

**Verification:** five bad admin logins from a reserved test IP returned `401
admin_invalid`; the sixth returned `429 admin_rate_limited`. The bucket recovers
after the 5-minute window. Public probes with different `X-Real-IP` values
decremented the same gateway bucket, confirming that nginx overwrites the
header.

### 2.6 Secrets and logs

- `.env` is `640 root:mangapoisk`; `source-cookies.json` is `600`; keystore
  material is `600 root:root`.
- The last 24 hours of journal output on both nodes were scanned for
  `VAPID_PRIVATE_KEY`, `CLIENT_SECRET`, `ghp_`, `github_pat_`, `Bearer ` and
  `BEGIN ... PRIVATE KEY`. All counts were **0**.
- No secret values are stored in this document or in the committed unit/config
  templates.

### 2.7 Dependencies

Audited with `pip-audit` in a temporary virtualenv against the production
site-packages, and with `npm audit --omit=dev` for `apps/web`. Nothing was
updated automatically.

- **Primary node (`aeza`):** 67 packages, 47 advisory records / 44 unique
  advisories in two packages:
  - `Pillow 12.3.0` — 5 critical advisories, including heap overflows and
    Ghostscript argument injection (`CVE-2026-112900`); fix version `13.0.0`.
  - `cryptography 47.0.0` — high advisories including a Bleichenbacher oracle
    and a bundled vulnerable OpenSSL (`GHSA-537c-gmf6-5ccf`); fixes require
    `48.0.1`–`50.0.0` depending on advisory.
  - More than 20 further high-severity Pillow advisories (TIFF/JPEG/GIF/PDF
    parsing, decompression bombs, use-after-free).
- **Edge node (`jump-83`):** 44 packages, 40 advisory records in
  `Pillow 12.3.0` (the same critical/high family); no `cryptography` finding.
- **Web (`apps/web`):** `npm audit --omit=dev` reports 0 vulnerabilities across
  18 production dependencies (131 total including dev/optional).

The dependency upgrade is included in v1.3.0 (issue #77):
`Pillow 13.0.0` in `services/media`, `cryptography 50.0.2` in
`services/control` and `services/notifier`. A fresh `pip-audit` on the merged
requirements reports **0 known vulnerabilities**, and the Fernet
47 -> 50 compatibility path was verified before the rollout. See
[`DEPENDENCIES.md`](DEPENDENCIES.md) for the pinning and audit policy.

---

## 3. Verification summary (2026-11-13)

| Check | Result |
|---|---|
| All `mangapoisk-*.service` units active after UMask drop-ins | yes |
| `systemctl show -p UMask` on every unit | `0027` |
| Service process umask after restart | `0027` |
| New SQLite WAL/SHM files | `640 mangapoisk:mangapoisk` |
| Existing DB and release-copy permissions | `640` |
| `sshd -t` before reload | passed |
| Fresh SSH login after reload | passed |
| `sshd -T` effective hardening values | as listed in §2.3 |
| `fail2ban-client -t` | passed |
| `fail2ban-client status sshd` | jail active, journal backend |
| Ban/unban action test (`203.0.113.250`) | passed, address removed |
| Admin login limiter | 5×401, 6th 429, recovery after window |
| Public `X-Real-IP` spoof probe | same bucket; header overwritten by nginx |
| Journal secret scan (24h) | all counts 0 |
| `pip-audit` | findings recorded in §2.7 |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Public ports / redirects (v1.3.2) | 80/443 active; `http`/`www` 301; `:8443` API 200/web 301; `:8088` 301 except `/ads.txt` |
| TLS certificate (v1.3.2) | SAN apex+www; expires 2027-02-11; targeted `certbot renew --dry-run` passed |
| `ads.txt` direct paths | 80/443/8088 → 200 `text/plain`, 9 lines, no Location |
| Yandex ID production login | real login confirmed; redirect URI no port; scopes include `login:info` |
| Yandex RTB CSP / config | loader reaches `yandex.ru`; provider returns `config.block_id`; SDK external `PAGE_DISABLED` remains |

---

## 4. Rollback

All changes are reversible without touching application code or database
content. Backups are under `/root/security-hardening-<timestamp>/` on each node.

### UMask drop-ins

```bash
rm -f /etc/systemd/system/mangapoisk-*.service.d/umask.conf
systemctl daemon-reload
# existing processes keep their old umask until restarted
```

The original unit files are in the backup directory. To restore a specific unit:

```bash
cp -a /root/security-hardening-<timestamp>/mangapoisk-<name>.service \
  /etc/systemd/system/mangapoisk-<name>.service
systemctl daemon-reload
systemctl restart mangapoisk-<name>.service
```

### fail2ban

```bash
fail2ban-client unban --all || true
systemctl stop fail2ban
systemctl disable fail2ban
rm -f /etc/fail2ban/jail.d/mangapoisk-sshd.local
```

If fail2ban is suspected of blocking a legitimate client, stop it first; the
existing SSH session is not affected by the jail.

### SSH

```bash
rm -f /etc/ssh/sshd_config.d/99-mangapoisk-hardening.conf
sshd -t
systemctl reload ssh
```

The original `sshd_config` and `sshd_config.d/` are in the backup directory. If a
reload ever fails, the dead-man timer created during the change performs this
rollback automatically.

### Database permissions

The previous mode was `644` on the affected files. To restore it (not
recommended):

```bash
chmod 644 /opt/mangapoisk-reborn/data/*.db
```

### Timers

List and cancel any leftover transient rollback timers:

```bash
systemctl list-timers 'ssh-rollback-*' 'fail2ban-rollback-*'
systemctl stop <timer-unit>
```

---

## 5. Remaining risks and follow-ups

1. **Dependency advisories (resolved in v1.3.0).** `Pillow` 13.0.0 and
   `cryptography` 50.0.2 are merged; `pip-audit` reports 0 known
   vulnerabilities. Keep the audit cadence from [`DEPENDENCIES.md`](DEPENDENCIES.md)
   and re-run it on every dependency change.
2. **Root password SSH is still enabled (#78).** `PermitRootLogin yes` and
   `PasswordAuthentication yes` remain for operational continuity. Move to
   per-host keys, then `PermitRootLogin prohibit-password` and
   `PasswordAuthentication no`. See §6.
3. **CSP is broad (#79).** `script-src 'unsafe-inline'` and broad
   `connect-src`/`img-src` remain; v1.3.2 added the Yandex RTB domains.
   Tighten after inline boot/theme code is removed.
4. **Legacy public ports (#82).** The site is on 80/443; `:8443` is API-only
   for APK 1.3.0 and `:8088` redirects except `/ads.txt`. Keep the firewall
   rules minimal and remove both ports after the old APK/links are retired.
   The secondary-node fallback ports remain a separate follow-up.
5. **Report endpoint rate limit.** Reports are authenticated and deduplicated
   per comment, but there is no per-user daily report cap. Add one if abuse is
   observed.
6. **Admin panel exposure (#79).** There is no IP allowlist or MFA on `/admin`;
   a stolen 60-minute admin token remains usable until expiry. Consider VPN/IP
   allowlisting and TOTP.
7. **fail2ban is local.** Each node has its own jail; there is no central
   ban feed. This is acceptable for two nodes but should be revisited if the
   fleet grows.
8. **Operator egress IP is dynamic.** The current IP is in `ignoreip`; update
   it when it changes, or use a stable VPN/Tailscale address for management.
9. **Backups.** Database release copies are now `640`; ensure off-host backup
   storage is encrypted and access-controlled.

---

## 6. Future key-only SSH plan

1. Generate a separate Ed25519 key per operator/workstation and per automation
   role; do not reuse the workstation key for deployments.
2. Install public keys in `/root/.ssh/authorized_keys` (or a dedicated
   `deploy` user) with `from=`/`restrict` options where possible; verify a new
   key-based login on both nodes.
3. Keep the current password session open; test key login from a second
   terminal.
4. Set `PermitRootLogin prohibit-password` first, verify, then set
   `PasswordAuthentication no` and `KbdInteractiveAuthentication no`.
5. Update the control-plane deployer and runbooks to use keys/agent forwarding
   disabled, and rotate the root passwords after key-only access is proven.
6. Keep a console/recovery path (provider console or a break-glass key stored
   offline) before disabling password auth.
7. Re-run `sshd -t`, reload, verify a fresh login, and only then remove the
   dead-man timer.

---

## 7. Secret rotation checklist

Rotate after any suspected exposure, and at least on operator turnover:

- [ ] Root SSH passwords for both nodes (after key-only access is proven).
- [ ] GitHub PAT used by the workspace; replace with a fine-grained, expiring
      token scoped to this repository.
- [ ] `JWT_SECRET`, `INTERNAL_TOKEN`, `CONTROL_SECRET_KEY`.
- [ ] Admin username/password (invalidates existing admin tokens via `av`).
- [ ] `VAPID_PRIVATE_KEY` / push credentials.
- [ ] Yandex OAuth client secret and any source cookies.
- [ ] Re-encrypt control-plane SSH credentials after changing
      `CONTROL_SECRET_KEY`.
- [ ] Verify old credentials fail, update the password manager, and confirm no
      secrets appear in the journal.

---

## 8. Repo-managed templates

The production drop-ins are mirrored in the repository so future rebuilds do
not silently lose the hardening:

- `infra/systemd/mangapoisk-umask.conf` — `UMask=0027` drop-in.
- `infra/ssh/99-mangapoisk-hardening.conf` — SSH settings (password auth
  intentionally not disabled).
- `infra/fail2ban/mangapoisk-sshd.local` — sshd jail with the documented
  thresholds and trusted peers (add the operator egress IP locally).

Install them with the commands in the relevant section above. Do not commit
`.env`, `data.txt`, keys, tokens or host-specific credentials.
