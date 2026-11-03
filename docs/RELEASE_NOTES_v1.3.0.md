# DailyGreen Release Notes — v1.3.0 Production Release

**Release Date:** 2026-11-03  
**Target Environment:** Production Node.js 22 + React 19 + TypeScript + Vite + Tailwind CSS + Docker Multi-stage  
**Safety Invariant Baseline:** `dry_run = true`, `allow_live_mutations = false`, `max_workers = 1`, `circuit_breaker_threshold = 3`

---

## 1. Executive Summary

DailyGreen v1.3.0 is the official production release of the autonomous repository maintenance engine and quality gate harness. Originally imported from Python (`mahmudjanovr/daily-green`), DailyGreen has been stabilized, hardened, and expanded into a full-stack production platform combining:

- A typed Node.js/TypeScript backend with native Git CLI isolation.
- TypeScript Compiler API AST analysis for AST syntax tree validation and structural/cryptographic distinction.
- Google Gemini Intelligence (`gemini-3.8-flash`) for automated task classification, documentation quality improvements, and verifiable Pull Request generation.
- SRE observability, Prometheus-compatible metrics (`/api/metrics`), and atomic disaster recovery backups.
- Enterprise containerization: non-root multi-stage Docker container (UID 10001) with native health checks.

---

## 2. Key Features by Phase

### Phase 2: Real Git Infrastructure & Credential Isolation
- **Subprocess Execution**: Uses `spawn(executable, args)` array execution with zero shell interpolation (`shell: false`).
- **Elimination of Argument Leaking**: Personal Access Tokens (PATs) are shielded from `/proc/<pid>/cmdline` and `ps aux` via ephemeral `GIT_ASKPASS` executable scripts created with strict octal mode `0o700` and injected via process environment variables (`DAILYGREEN_EPHEMERAL_PAT`).
- **Automatic Lifecycle Cleanup**: Ephemeral scripts and temp directories are guaranteed to be unlinked in `finally` blocks.
- **Porcelain Status & Unified Diffs**: Native inspection of repository working trees and modified line counts.

### Phase 3: Autonomous Engine & Scheduling Daemon
- **Dual-Clock Telemetry**: Displays Asia/Tashkent (UTC+5) and UTC standard clocks.
- **Backup Run Window**: Detects the 17:35 UTC (22:35 Tashkent) trigger slot and deduplicates runs when primary runs have succeeded.
- **Global Concurrency Guard**: Hard limits worker concurrency to `max_workers = 1` via atomic in-memory and durable filesystem leases.
- **Circuit Breaker**: Freezes automated execution on any repository that encounters 3 consecutive test or lint failures.

### Phase 4: AST-Based Code Analysis & Patch Sealing
- **AST Security Policy**: Uses the TypeScript Compiler API to detect and block:
  - `eval()` invocations
  - `new Function(...)` constructor calls
  - Dangerous imports (`child_process`, `exec`, `spawn`)
  - Prototype pollution (`__proto__`, `constructor.prototype`)
- **AST vs. Source Hash Distinction**: Formally separates structural AST node kind topology (`ast_structural_fingerprint`) from physical byte integrity (`source_integrity_hash`).
- **Cryptographic Patch Seal**: All unified diffs are hashed with SHA-256 and verified before any delivery step.

### Phase 5: Google Gemini Intelligence
- **SDK**: Official `@google/genai` TypeScript SDK with model `gemini-3.8-flash`.
- **Server-Side Key Isolation**: `GEMINI_API_KEY` is maintained strictly in server process environment variables; zero credentials are exposed to React bundles or browser storage.
- **Structured JSON Schema**: Validated responses with `Type.OBJECT`, `Type.STRING`, `Type.ARRAY`.
- **Fail-Safe Fallbacks**: Exponential backoff retries with deterministic heuristic fallbacks when Gemini is unconfigured or rate-limited.
- **Fail-Closed AI Safety**: AI proposals cannot authorize Git pushes or modify mutation policies. Generated documentation undergoes mandatory AST analysis and secret scanning.

### Phase 6: E2E Reliability & Fault Tolerance
- **React ErrorBoundary**: Top-level containment capturing UI exceptions and displaying a fail-safe recovery interface with application reload.
- **Correlation IDs**: `X-Correlation-ID` header injected on all HTTP requests and responses for end-to-end tracing.
- **Sanitized Logging**: All secrets and token patterns (`ghp_*`, `AIzaSy*`, `Bearer *`) are automatically redacted from error messages, API responses, and logs.

### Phase 7: Production Infrastructure & Disaster Recovery
- **Multi-Stage Dockerfile**: Builds on `node:22-alpine` with an unprivileged system user `dailygreen` (UID 10001) and native healthcheck.
- **Docker Compose**: Production volume persistence (`dailygreen-storage`), resource limits (1 CPU, 1024MB RAM), and `no-new-privileges:true`.
- **SRE Metrics**: `GET /api/metrics` reports HTTP request latency percentiles (p50, p95), memory usage, scheduler ticks, and storage footprint.
- **Atomic Backups**: `GET /api/backups`, `POST /api/backups`, and `POST /api/backups/:id/restore` provide snapshot creation, SHA-256 verification, and disaster recovery.
- **GitHub Actions CI/CD**: Workflows for verification (`ci.yml`), container healthchecks (`docker.yml`), and production approvals (`release.yml`).

---

## 3. Test Suite Reconciliation

| Sprint | Executed Tests | Suites | Note |
| :--- | :--- | :--- | :--- |
| **Sprint 1 Baseline** | 58 | 9 | Core engine, git service, pipeline, scheduler, state, quality gate, config |
| **Sprint 2 Audit** | 70 | 11 | Added `credential_isolation` (5) and `gemini_ai` (6), plus AST source distinction |
| **Sprint 3 Production** | 82+ | 14 | Added `backup_service`, `observability`, and `security_audit` production suites |

---

## 4. Known Limitations

1. **Host Python Package**: The original `dailygreen` Python package is not present in the host system Python site-packages; the application faithfully reports this in `GET /api/capabilities` and executes via the TypeScript orchestrator.
2. **Mutations Policy**: Live GitHub mutations (`ALLOW_LIVE_MUTATIONS`) remain disabled by default in compliance with the two-person operational authorization policy.
