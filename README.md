# DailyGreen

> Reliable, secure, and production-minded automated code maintenance across authorized GitHub repositories.

[![React](https://img.shields.io/badge/react-19-blue.svg)]()
[![TypeScript](https://img.shields.io/badge/typescript-5-blue.svg)]()
[![Vite](https://img.shields.io/badge/vite-6-purple.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## 1. What DailyGreen Does (and Does Not Do)

### What DailyGreen Does:
- **Discovers legitimate, bounded tasks** using a strict **rules-first, AI-second** priority (labeled GitHub issues, curated backlog, deterministic documentation link/format/typo fixes, and optional AI proposals).
- **Executes changes in an isolated workspace** without modifying unauthorized repositories or files.
- **Enforces an independent, mandatory Quality Gate** with baseline pre-tests, strict path allowlists, file denylists, secret scanning (AWS keys, GitHub tokens, Slack keys, private key blocks), and diff limits (max 150 changed lines).
- **Seals verified patches** with a SHA-256 cryptographic hash.
- **Proposes dedicated Pull Requests** with detailed audit trails, verification command results, and security disclosures.
- **Provides high availability** with primary scheduled cadence (22:15 Asia/Tashkent) and deduplicated backup execution (22:35 Asia/Tashkent).
- **Maintains durable state & circuit breakers** to avoid duplicate work and circuit-break repeated failures (threshold >= 3).

### What DailyGreen NEVER Does:
- **Never fabricates activity or empty commits.** If there is no worthwhile task, it reports `NO_TASK` and exits cleanly.
- **Never pushes directly to default branches** (`main` / `master`).
- **Never automatically merges Pull Requests.** Human maintainers always retain final merge authority.
- **Never touches unauthorized repositories.** It operates strictly on an explicit allowlist and fails closed.
- **Never modifies CI/CD workflows, dependency lockfiles, or executable scripts.**
- **Never exposes GitHub write tokens or cloud secrets to test execution environments.**

---

## 2. Architecture & Pipeline

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
                  │  - Secret scanning (AWS, PATs, Slack, keys)  │
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

## 3. Web Application Features

The React application implements the complete operational console for DailyGreen:

- **Pipeline Runner**: Step-by-step interactive runner simulating workspace isolation, baseline checks, task application, post-change validation, quality gate scorecard, and delivery. Supports Standard, Backup (22:35 Tashkent), and Worker Sandbox modes.
- **Task Discovery Engine**: Read-only candidate exploration with priority breakdown (Labeled Issues → Curated Backlog → Deterministic Checks → AI Proposals).
- **GitHub Connectivity (`check-github`)**: Tests token status, GitHub API rate limits (5,000 req/hr), authenticated user profile, and repository read-only accessibility.
- **Authorized Repositories Allowlist (`repos.yml`)**: Interactive allowlist manager for repositories, default branches, allowed/denied path patterns, baseline commands, and test suites.
- **Security Policy Safeguards (`policy.yml`)**: Global diff limits, workflow/lockfile blockers, mandatory secret scanning, and emergency global kill switch (`DAILYGREEN_ENABLED`).
- **Audit Reports & Durable State (`report`)**: GitHub Step Summary markdown renderer, run history, active execution leases, and circuit breaker trip resets.
- **Workspace File Sandbox**: Interactive file editor allowing maintainers to test common issues (typos, trailing spaces, broken links, secrets) and verify DailyGreen detection and remediation.

---

## 4. Local Development

```bash
# Install dependencies
npm install

# Start development server on port 3000
npm run dev

# Compile and build for production
npm run build
```

---

## 5. GitHub Contribution Semantics

- **Commit Squares**: Commits register on your contribution graph only after the Pull Request is merged into the default branch (`main`) or `gh-pages`, and when the Git author email matches a verified email address on your GitHub account.
- **Pull Request Activity**: Pull Requests appear in your activity profile only if private contributions or PR activity is enabled in your GitHub profile settings.
- DailyGreen never claims contribution status is verified unless confirmed via GitHub.

---

## 6. License

MIT License.
