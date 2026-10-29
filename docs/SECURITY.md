# DailyGreen Security Architecture and Policy

## 1. Security Overview and Philosophy

DailyGreen is designed according to **strict fail-closed, defense-in-depth principles**. Automated code maintenance must never become a vector for supply-chain compromise, secret exfiltration, or unauthorized repository tampering.

A green contribution graph is a desired outcome, **not permission to fabricate activity**. Empty commits, trivial white-noise edits, or bypassing security controls are strictly prohibited.

---

## 2. Threat Model

| Threat | Mitigation Mechanism |
| :--- | :--- |
| **Prompt Injection / Malicious Issue Content** | GitHub issues and repository texts are treated as **untrusted data**. They are never evaluated as system prompts. Target files must match strict allowlists and pass all quality gates. |
| **Credential Exfiltration in Subprocesses** | The worker executes tests in a **sanitized environment**. `GITHUB_TOKEN`, `PAT`, `GEMINI_API_KEY`, cloud credentials, and any variables matching `*SECRET*` or `*KEY*` are stripped before spawning test or build processes. |
| **Path Traversal / Symlink Hijacking** | All file operations resolve paths against the isolated workspace root. Symlinks pointing outside the workspace and traversal sequences (`..`) are rejected immediately. |
| **Workflow / CI Tampering** | Automated modifications to `.github/workflows/**` are strictly denied by policy. |
| **Supply Chain & Lockfile Modification** | Package lockfiles (`package-lock.json`, `poetry.lock`, etc.) and executable scripts (`*.sh`, `*.exe`) are blocked from automated modification. |
| **Diff Tampering between Gate and Delivery** | Verified diffs are sealed with a **SHA-256 cryptographic hash**. The delivery engine refuses to create a PR if the patch hash changes. |
| **Unauthorized Repository Access** | Only repositories explicitly defined in the allowlist (`repos.yml`) can be accessed. Discovery fails closed on unlisted repositories. |

---

## 3. Credential and Process Isolation

DailyGreen separates code execution from delivery privileges:

```
[ Scheduled Trigger / Dispatch ]
             │
             ▼
┌──────────────────────────────────────────────┐
│  Worker Job (Untrusted Code Execution)       │
│  - Environment Sanitized (No Write Tokens)   │
│  - Baseline Verification (Must Pass)         │
│  - Rules-First / AI Task Execution           │
│  - Post-Change Test & Lint Commands          │
│  - Secret Scanning & Diff Limits (≤150 lines)│
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
└──────────────────────────────────────────────┘
```

---

## 4. Quality Gate Policies

Every proposed change must satisfy all of the following gates:

1. **Baseline Pre-Check**: If the repository baseline tests fail *before* any changes, DailyGreen aborts immediately. Broken repos must be repaired by humans.
2. **Path Allowlist**: Target files must match the repository's configured `allowed_paths` (e.g. `docs/**`, `README.md`).
3. **Denylist Enforcement**: Forbidden paths and extensions are blocked regardless of allowlist matching:
   - Environment files: `.env*`, `*.env`
   - Private keys and certificates: `*.key`, `*.pem`, `*.pfx`, `*.cert`
   - CI/CD workflows: `.github/workflows/**`
   - Package manager lockfiles: `package-lock.json`, `poetry.lock`, `yarn.lock`, etc.
   - Executable binaries & scripts: `*.sh`, `*.bat`, `*.cmd`, `*.exe`, `*.bin`, `*.so`, `*.dll`
4. **Secret Scanning**: Scans diffs and file contents using high-precision patterns for AWS keys, GitHub tokens, Slack tokens, private keys, and high-entropy secrets, and invokes Gitleaks when installed on the host.
5. **Diff Size Bound**: Maximum 150 changed lines per task (configurable per repo up to 500 max).
6. **No Empty Commits**: Tasks producing empty diffs are rejected with `NO_TASK`.
7. **No Auto-Merge**: Pull Requests must be reviewed and merged manually by humans.

---

## 5. Kill Switch and Emergency Deactivation

To disable DailyGreen immediately across all environments:

Set the environment variable or GitHub Actions secret:
```bash
DAILYGREEN_ENABLED=false
```
Or in `config/repos.yml`, set `enabled: false` for the repository.
