# DailyGreen Security Architecture and Policy
## Production Release Security Specification (v1.3.0)

## 1. Security Overview and Philosophy

DailyGreen is designed according to **strict fail-closed, defense-in-depth principles**. Automated code maintenance must never become a vector for supply-chain compromise, secret exfiltration, or unauthorized repository tampering.

A green contribution graph is a desired outcome, **not permission to fabricate activity**. Empty commits, trivial white-noise edits, or bypassing security controls are strictly prohibited.

---

## 2. Threat Model & Mitigation Matrix

| Threat | Mitigation Mechanism |
| :--- | :--- |
| **Command-Line Credential Leakage** | Credentials are **never** passed via process arguments (`process.argv` / `-c http.extraheader`). Ephemeral `GIT_ASKPASS` scripts with mode `0o700` and process environment variables (`DAILYGREEN_EPHEMERAL_PAT`) are used with guaranteed cleanup in `finally` blocks. |
| **Prompt Injection / Malicious Issue Content** | GitHub issues and repository texts are treated as **untrusted data**. They are never evaluated as system prompts. Target files must match strict allowlists, pass TypeScript AST analysis, and satisfy all quality gates. |
| **Credential Exfiltration in Subprocesses** | The worker executes tests in a **sanitized environment**. `GITHUB_TOKEN`, `PAT`, `GEMINI_API_KEY`, cloud credentials, and any variables matching `*SECRET*` or `*KEY*` are stripped before spawning test or build processes. |
| **Path Traversal / Symlink Hijacking** | All file operations resolve paths against the isolated workspace root. Symlinks pointing outside the workspace and traversal sequences (`..`, null bytes) are rejected immediately. |
| **Workflow / CI Tampering** | Automated modifications to `.github/workflows/**` are strictly denied by policy. |
| **Supply Chain & Lockfile Modification** | Package lockfiles (`package-lock.json`, `poetry.lock`, etc.) and executable scripts (`*.sh`, `*.exe`) are blocked from automated modification across 22 global deny patterns. |
| **Diff Tampering between Gate and Delivery** | Verified diffs are sealed with a **cryptographic SHA-256 hash**. The delivery engine refuses to create a PR if the patch hash changes. |
| **AST AST Structural vs Source Integrity Conflation** | Source files are independently checked via both a structural AST grammar topology fingerprint (`ast_structural_fingerprint`) and an exact cryptographic SHA-256 byte digest (`source_integrity_hash`). |
| **Unauthorized Repository Access** | Only repositories explicitly defined in the allowlist (`repos.yml`) can be accessed. Discovery fails closed on unlisted repositories. |
| **Container Breakout / Privilege Escalation** | Production Docker container runs as dedicated unprivileged user `dailygreen` (UID/GID 10001) with `no-new-privileges:true` and read-only non-root execution permissions. |

---

## 3. Credential and Process Isolation

DailyGreen separates code execution from delivery privileges:

```
[ Scheduled Trigger / Dispatch ]
             │
             ▼
┌──────────────────────────────────────────────┐
│  Worker Job (Untrusted Code Execution)       │
│  - Ephemeral GIT_ASKPASS (0o700 permissions) │
│  - Environment Sanitized (No Write Tokens)   │
│  - Baseline Verification (Must Pass)         │
│  - Rules-First / AI Task Execution           │
│  - Post-Change Test & Lint Commands          │
│  - TypeScript AST Analysis & Secret Scanning │
│  - Seal Approved Patch with SHA256 Hash      │
└──────────────────────────────────────────────┘
             │ (Sealed Patch Hash & Artifacts)
             ▼
┌──────────────────────────────────────────────┐
│  Delivery Job (Trusted API Interaction)      │
│  - NEVER executes repository code/scripts    │
│  - Validates Repository Allowlist            │
│  - Re-verifies Patch Hash against Seal       │
│  - Publishes Branch & Creates Pull Request   │
│  - Subject to 2-Person Approval in Live Mode │
└──────────────────────────────────────────────┘
```

---

## 4. Quality Gate Policies

Every proposed change must satisfy all of the following gates:

1. **Baseline Pre-Check**: If the repository baseline tests fail *before* any changes, DailyGreen aborts immediately. Broken repos must be repaired by humans.
2. **Path Allowlist**: Target files must match the repository's configured `allowed_paths` (e.g. `docs/**`, `README.md`).
3. **Path Denylist**: Target files must not match any of the 22 denied patterns:
   - Credentials and keys: `.env*`, `*.key`, `*.pem`, `*.cert`, `*.pfx`, `*.p12`
   - CI/CD workflows: `.github/workflows/**`
   - Dependency lockfiles: `package-lock.json`, `poetry.lock`, `Pipfile.lock`, `pnpm-lock.yaml`, `yarn.lock`, `composer.lock`, `Cargo.lock`
   - Executable scripts: `*.sh`, `*.bat`, `*.cmd`, `*.exe`, `*.bin`
   - Internal state: `.dailygreen/**`, `.git/**`
4. **Secret Scanning**: Both modified files and unified diffs are scanned for sensitive credential patterns.
5. **Diff Line Limits**: Maximum 150 changed lines per run (configurable down to 50 for AI tasks).
6. **AST Security Analysis**: TypeScript/TSX/JS code is parsed using the TypeScript Compiler API AST. It forbids:
   - Dynamic code evaluation (`eval()`)
   - Dynamic function construction (`new Function(...)`)
   - Dangerous subprocess imports (`child_process`, `exec`, `spawn`)
   - Prototype pollution (`__proto__`, `constructor.prototype`)
7. **Post-Change Verification**: Test and lint commands must pass cleanly after changes are applied.
8. **Cryptographic Patch Sealing**: Diff is hashed with SHA-256 and signed with HMAC-SHA256 prior to delivery.

---

## 5. Live Mutation Safety Defaults

The following safety invariants are hardcoded and non-negotiable:

- `dry_run = true`
- `allow_live_mutations = false`
- `max_workers = 1`
- `circuit_breaker_threshold = 3`
- Global kill switch functional at all times.

---

## 6. Disaster Recovery & Backup Architecture

- DailyGreen generates atomic JSON/gzip backups of live state and configuration in `.dailygreen-data/backups/`.
- Each backup archive is sealed with a computed SHA-256 checksum.
- Automated restoration verifies the checksum prior to extraction and captures a safety rollback snapshot before altering state.
