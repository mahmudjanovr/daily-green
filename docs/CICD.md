# DailyGreen CI/CD Pipeline Documentation

## 1. Overview

DailyGreen employs automated GitHub Actions workflows to guarantee code quality, secret hygiene, container stability, and deployment safety across every commit and pull request.

---

## 2. Workflows

### 1. Verification & Quality Pipeline (`.github/workflows/ci.yml`)
- **Trigger**: Every push or pull request to `main`.
- **Stages**:
  1. `Checkout`: Fetches repository source tree.
  2. `Setup`: Configures Node.js 22 and Python 3.10.
  3. `Lint`: Executes TypeScript typecheck (`tsc --noEmit`).
  4. `Test`: Executes complete test suite across all 11 test suites (70+ unit & integration tests).
  5. `Build`: Compiles production frontend bundles via Vite (`npm run build`).
  6. `Secret Hygiene`: Scans compiled assets in `dist/assets/*.js` for accidentally bundled tokens or credentials.

### 2. Docker Container Healthcheck (`.github/workflows/docker.yml`)
- **Trigger**: Changes to `Dockerfile`, `docker-compose.yml`, or server entry points.
- **Stages**:
  1. Builds multi-stage production Docker image (`dailygreen:test`).
  2. Spins up container locally.
  3. Polls `http://localhost:3000/api/health` to verify that process starts, non-root user functions, and endpoints respond.
  4. Tears down container cleanly.

### 3. Production Release & Deployment (`.github/workflows/release.yml`)
- **Trigger**: Git release tag `v*.*.*` or manual `workflow_dispatch`.
- **Environment**: `production` with mandatory manual review approval gate.
- **Gatekeeper Verification**:
  - Validates that `allow_live_mutations: false` remains set in `config/policy.yml`.
  - Re-executes test suite before permitting artifact promotion.

### 4. Autonomous Maintenance Action (`.github/workflows/dailygreen.yml`)
- **Trigger**: Cron schedule at 17:15 UTC (22:15 Asia/Tashkent) and 17:35 UTC (22:35 Asia/Tashkent).
- **Execution**: Runs sandboxed maintenance evaluation and artifact sealing.
