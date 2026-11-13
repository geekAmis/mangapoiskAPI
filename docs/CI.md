# CI

The workflow lives in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
and runs on every pull request to `main`, every push to `main`, and on manual
`workflow_dispatch`.

## Jobs

| Job | What it verifies |
| --- | --- |
| `backend` | `ruff check .` and `pytest` for all services and shared packages. Pytest also imports every service app, which is the source import smoke test. |
| `web` | TypeScript typecheck, production Vite build, and `npm run test:unit` (Node's built-in test runner). |
| `docs-encoding` | `README.md` and `docs/*.md` are valid UTF-8 without BOM, `U+FFFD` characters, CP1251 mojibake, or mixed CRLF/LF endings. |
| `mobile-web` | Capacitor web bundle builds from `apps/mobile` (`npm run build:www`). The job installs both the mobile and web workspaces because `build:www` runs the web build first. The `release/android-1.3.2` build additionally rejects stale `:8088`/`:8443` endpoints and packages API 443. |
| `ops-scripts` | `bash -n scripts/ops/*.sh` parses every ops shell script. |
| `android` | `./gradlew assembleDebug` when `apps/android/gradlew` is present. |
| `compose` | `docker compose config -q` validates the compose file. |

All jobs are required unless a job is conditionally skipped by the workflow
(for example `android` when the Gradle wrapper is absent).

## Before merging

1. Wait for every CI job on the latest commit to pass.
2. Rebase or merge `main` into the branch if it moved; do not merge with a red
   or stale run.
3. Run the local checks below for the areas you changed. Documentation changes
   must pass the encoding check.
4. Keep tests offline: no live source scraping, no production API calls and no
   secrets in the workflow. Network parser tests are opt-in with
   `RUN_NETWORK_TESTS=1` and are not part of CI.

## Run checks locally

From the repository root:

```bash
# Backend lint and tests
ruff check .
pytest

# Web typecheck, build and unit tests
cd apps/web
npm ci            # or npm install when experimenting
npm run typecheck
npm run build
npm run test:unit
cd ../..

# Documentation encoding
python scripts/check_docs_encoding.py

# Mobile web bundle (builds apps/web, then copies it to apps/mobile/www)
cd apps/mobile
npm ci            # or npm install
npm run build:www
cd ../..

# Ops shell syntax (Git Bash on Windows)
bash -n scripts/ops/*.sh
```

The docs check also accepts explicit paths:

```bash
python scripts/check_docs_encoding.py README.md docs/CI.md
```

## Runtime and caching

The new jobs run in parallel with the existing ones. `docs-encoding` and
`ops-scripts` finish in seconds; `mobile-web` is the slowest addition and takes
roughly two minutes on a cold cache, less when the npm cache hits. Overall CI
stays within the three-minute budget for the added checks.

`actions/setup-node` caches npm downloads using
`apps/web/package-lock.json` and `apps/mobile/package-lock.json`; the backend
job keeps the existing pip cache. The docs and ops jobs have no dependencies to
cache.
