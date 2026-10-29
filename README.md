# DailyGreen

> Reliable, secure, and production-minded automated code maintenance across authorized GitHub repositories.

[![CI](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## 1. What DailyGreen Does (and Does Not Do)

### What DailyGreen Does:
- **Discovers legitimate, bounded tasks** using a strict **rules-first, AI-second** priority (labeled GitHub issues, curated backlog, deterministic documentation link/format/typo fixes, and optional AI proposals).
- **Executes changes in an isolated workspace** without modifying your working tree.
- **Enforces an independent, mandatory Quality Gate** with baseline pre-tests, strict path allowlists, file denylists, secret scanning, and diff limits (max 150 changed lines).
- **Seals verified patches** with a SHA-256 cryptographic hash.
- **Proposes dedicated Pull Requests** with detailed audit trails and security disclosures.
- **Provides high availability** with a primary scheduled run (22:15 Asia/Tashkent) and a deduplicated backup run (22:35 Asia/Tashkent).
- **Maintains durable state** to avoid duplicate work and circuit-break repeated failures.

### What DailyGreen NEVER Does:
- **Never fabricates activity or empty commits.** If there is no worthwhile task, it reports `NO_TASK` and exits cleanly.
- **Never pushes directly to default branches** (`main` / `master`).
- **Never automatically merges Pull Requests.** Human maintainers always retain final merge authority.
- **Never touches unauthorized repositories.** It operates strictly on an explicit allowlist and fails closed.
- **Never modifies CI/CD workflows, dependency lockfiles, or executable scripts.**
- **Never exposes GitHub write tokens or cloud secrets to test execution environments.**

---

## 2. Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │          Rules-First Task Discovery          │
                  │ 1. Issues labeled 'dailygreen'               │
                  │ 2. Curated local backlog                     │
                  │ 3. Deterministic checks (links, format, typo)│
                  │ 4. AI-assisted proposals (if permitted)      │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │              Isolated Worker                 │
                  │  - Sanitized env (no tokens or API keys)     │
                  │  - Baseline test must pass before changes    │
                  │  - Apply changes & run test/lint commands    │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │            Mandatory Quality Gate            │
                  │  - Max 150 lines changed                     │
                  │  - Secret scanning (regex + Gitleaks)        │
                  │  - Block .env, workflows, lockfiles, scripts │
                  │  - Seal approved diff with SHA-256 hash      │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │               GitHub Delivery                │
                  │  - Re-verify patch hash against seal         │
                  │  - Idempotency: skip if branch/PR exists     │
                  │  - Dry-run: simulate without remote calls    │
                  │  - Live: publish branch & create PR          │
                  └──────────────────────────────────────────────┘
```

---

## 3. Installation and Local Development

### Requirements
- Python 3.11 or 3.12+
- Git 2.30+

### Setup
```bash
# Clone repository
git clone https://github.com/my-org/dailyGreen.git
cd dailyGreen

# Install DailyGreen in editable mode with dev dependencies
pip install -e .[dev]

# Run automated test suite
python -m pytest
```

---

## 4. Configuration

DailyGreen uses YAML configuration files and environment variables.

### Copy Example Configuration
```bash
cp config/repos.example.yml config/repos.yml
cp .env.example .env
```

### Adding an Authorized Repository
Add your repository to `config/repos.yml`:
```yaml
repositories:
  - name: "my-org/my-project"
    default_branch: "main"
    enabled: true
    max_diff_lines: 120
    timeout_seconds: 300
    allowed_paths:
      - "docs/**"
      - "README.md"
    denied_paths:
      - "pyproject.toml"
    supported_task_types:
      - "doc_links"
      - "doc_formatting"
      - "doc_typos"
      - "curated_backlog"
      - "issue_task"
    allow_ai_tasks: false
    baseline_command:
      - "pytest"
      - "-q"
    test_commands:
      - ["pytest", "-q"]
    lint_commands:
      - ["flake8", "docs/"]
```

### Validate Configuration
```bash
python -m dailygreen.cli check-config --repos-config config/repos.yml
```

---

## 5. CLI Usage

### Check GitHub Connectivity (Read-Only)
Verify GitHub authentication, API rate limits, and read-only repository access with zero mutations:
```bash
python -m dailygreen.cli check-github --repo my-org/my-project
```

### Discover Next Task (Read-Only)
Preview what task DailyGreen would select without making any remote or local modifications:
```bash
python -m dailygreen.cli discover --repo my-org/my-project
```

### Dry-Run Execution (Safe Simulation)
Simulate worker checks, test execution, diff generation, and delivery without modifying GitHub:
```bash
python -m dailygreen.cli run --repo my-org/my-project --dry-run
```

### Inspect Run History
```bash
python -m dailygreen.cli report
```

---

## 6. Emergency Kill Switch

To immediately disable DailyGreen across all runners:
```bash
export DAILYGREEN_ENABLED=false
```
Or in `config/repos.yml`, set `enabled: false`.

---

## 7. Scheduling and Timezone Reference

DailyGreen runs on GitHub Actions schedules configured in UTC:

| Run Type | Asia/Tashkent (UTC+5) | UTC Cron | Purpose |
| :--- | :--- | :--- | :--- |
| **Primary** | 22:15 | `15 17 * * *` | Main daily maintenance pass |
| **Backup** | 22:35 | `35 17 * * *` | Deduplicated fallback check |

---

## 8. GitHub Contribution Semantics

- **Commit Squares**: Commits register on your contribution graph only after the Pull Request is merged into the default branch (`main`) or `gh-pages`, and when the Git author email matches a verified email address on your GitHub account.
- **Pull Request Activity**: Pull Requests appear in your activity profile only if private contributions or PR activity is enabled in your GitHub profile settings.
- DailyGreen never claims contribution status is verified unless confirmed via GitHub.

---

## 9. Documentation Links
- [Security Architecture and Threat Model](docs/SECURITY.md)
- [Operations Manual and Runbook](docs/OPERATIONS.md)

---

## 10. License
MIT License.
