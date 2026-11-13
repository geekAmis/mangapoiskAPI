# Dependency policy

This document defines how Python, Node and container dependencies are pinned,
audited and upgraded in MangaPoisk Reborn.

## Sources of truth

| Ecosystem | Source | Installed by |
|---|---|---|
| Python shared package | `packages/manga_common/pyproject.toml` | `pip install -e packages/manga_common` |
| Python services | `services/*/requirements.txt` | CI, Dockerfiles, `control` deployer |
| Python tests/lint | `services/parser/requirements-dev.txt` plus the CI install step | CI / developers |
| Web | `apps/web/package-lock.json` | `npm ci` |
| Containers | `services/*/Dockerfile`, `docker-compose.yml` | Docker Compose |

There is currently no Python lock file. CI installs every service requirement
file into one fresh virtualenv, which is also the environment used for the full
test suite. A lock file (pip-tools or uv) can be added later, but the
`requirements.txt` ranges below remain the security contract until then.

## Current security pins

| Package | Pin | Used by | Notes |
|---|---|---|---|
| Pillow | `>=13.0.0,<14` | `services/media` | Image decode, WebP variants, CBZ/PDF export. 13.0.0 fixes the 12.3.0 critical/high advisories. |
| cryptography | `>=50.0.2,<51` | `services/control`, `services/notifier` | Fernet for SSH/ad/integration secrets, VAPID key handling. 50.0.2 is the newest 50.x patch. |

`cryptography` is pinned directly in `services/notifier/requirements.txt` even
though it is also a transitive dependency of `pywebpush`: `notifier` imports
`cryptography` in `app/push.py`, so it must not rely on a resolver choosing an
old transitive release.

## Pinning rules

1. Pin direct runtime dependencies with a security floor and a compatible upper
   bound: `package>=X.Y.Z,<next-major`.
2. Never widen a floor below a version that fixes a known critical/high
   advisory.
3. If code imports a package directly, list it directly even when another
   dependency already pulls it in.
4. Keep the same security floor in every service that needs the package. Do not
   create per-service exceptions without a comment in the requirements file.
5. Container base images stay on supported tags. The current Python base is
   `python:3.12-slim` (Debian bookworm, glibc 2.36).
6. Do not use `--no-deps` or `--no-binary` in production builds unless the
   resulting image has been audited and documented.

## Audit cadence

Run a full audit on the first working day of each month, and before every
release:

```bash
# Fresh environment that mirrors CI
python -m venv .venv-audit
. .venv-audit/bin/activate            # Windows: .venv-audit\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e packages/manga_common
for req in services/*/requirements.txt; do pip install -r "$req"; done
pip install pip-audit
pip-audit --desc

# Frontend production dependencies
cd apps/web
npm audit --omit=dev
```

Record the before/after counts in the security issue. `pip-audit` findings are
triaged by severity and exploitability:

| Severity | Target remediation |
|---|---|
| Critical | 48 hours |
| High | 7 days |
| Medium | 30 days |
| Low | Next scheduled dependency release |

If no fixed release exists, document the compensating control (for example,
disabling the affected decoder or restricting the feature) and keep the issue
open.

## Upgrade process

1. Open or update a security/dependency issue with the audit output and the
   affected services.
2. Create a branch from current `main`; do not upgrade unrelated packages in the
   same change.
3. Bump the floor in every affected `requirements.txt` (and any constraints or
   lock file).
4. Create a fresh virtualenv, install the updated requirements and run:
   - `pytest` (full suite);
   - targeted media image/WebP/thumbnail/archive tests;
   - control Fernet/secret tests;
   - auth/JWT/security tests;
   - `ruff check .`.
5. Run `pip-audit` on the updated environment and attach the result.
6. Build the affected Docker images and smoke-test `/health`. Check wheel
   platform tags against the base image before deploying.
7. Update `docs/CHANGELOG.md` and this document if pins or policy change.
8. Open a pull request; the lead reviews and deploys. Never auto-deploy a
   dependency bump.
9. Deploy in a controlled window with a rollback path (previous image or
   previous commit plus a rebuilt venv).

## Container and native-library notes

Pillow 13.0.0 publishes `manylinux_2_28` wheels. `python:3.12-slim`
(Debian bookworm) has glibc 2.36, so the wheels install without apt packages and
without compiling. The wheels bundle the image codecs used by this project
(JPEG, WebP, zlib, TIFF and friends), so no `libjpeg`/`zlib` development
packages are required for the current images.

If a future base image has no compatible wheel (for example, Alpine/musl or a
glibc older than the wheel tag), install the build dependencies instead of
forcing a source build silently. For Debian/Ubuntu media images the equivalent
packages are:

```text
libjpeg62-turbo-dev zlib1g-dev libwebp-dev libtiff-dev libfreetype6-dev
liblcms2-dev libopenjp2-7-dev
```

Do not change system packages on production hosts as part of a dependency
bump. Rebuild the image or recreate the service virtualenv instead.

`cryptography` 50.0.2 publishes `manylinux_2_28`/`manylinux_2_34` wheels and
bundles its own OpenSSL. `python:3.12-slim` is compatible; no base image update
is required for this change.

## Reporting

Report suspected dependency vulnerabilities through the process in
[`SECURITY.md`](SECURITY.md). Do not open a public issue with exploit details.
