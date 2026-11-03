# DailyGreen Docker Production Deployment Guide

## 1. Architecture

DailyGreen is packaged using a multi-stage Alpine Linux image (`node:22-alpine`):

- **Build Stage**: Compiles frontend assets into `dist/` with Vite and verifies TypeScript types.
- **Runtime Stage**:
  - Unprivileged user `dailygreen` (UID 10001, GID 10001).
  - Minimal runtime packages: `git`, `python3`, `curl`, `wget`, `tzdata`.
  - Non-root file ownership on all persistence paths (`/app/.dailygreen-data`).
  - Read-only execution permissions.
  - Native Docker healthcheck polling `/api/health`.

---

## 2. Quickstart with Docker Compose

### Step 1: Prepare Environment
```bash
cp .env.example .env
# Edit .env to set GEMINI_API_KEY if AI features are desired
```

### Step 2: Build and Start Container
```bash
docker compose up -d --build
```

### Step 3: Verify Status & Health
```bash
docker compose ps
docker compose logs -f dailygreen
```

### Step 4: Healthcheck Verification
```bash
curl -s http://localhost:3000/api/health
```

---

## 3. Persistent Volumes

DailyGreen stores all durable state inside a Docker named volume:

- `dailygreen-storage` mounts to `/app/.dailygreen-data`.
- Contents:
  - `.dailygreen-data/state.json`: Execution run history, leases, circuit breaker.
  - `.dailygreen-data/config.json`: Repository policies and configurations.
  - `.dailygreen-data/workspaces/`: Ephemeral isolated workspace directories.
  - `.dailygreen-data/backups/`: Atomic SHA-256 sealed backup snapshots.
  - `.dailygreen-data/logs/`: Structured JSON application logs.

To back up the volume directly:
```bash
docker run --rm -v dailygreen-storage:/data -v $(pwd):/backup alpine tar czf /backup/dailygreen-volume-backup.tar.gz -C /data .
```

---

## 4. Resource Allocation & Limits

The `docker-compose.yml` configures production limits:

- **CPU Limit**: 1.0 CPU cores
- **Memory Limit**: 1024 MB
- **Security Options**: `no-new-privileges:true`
- **Restart Policy**: `unless-stopped`
