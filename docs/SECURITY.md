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
- Production is HTTPS-only; HTTP is a compatibility fallback. Admin endpoints
  should be restricted to a management network or allowlist.
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
