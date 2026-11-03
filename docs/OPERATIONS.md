# DailyGreen Operations Manual and Runbook

## 1. Operating Model

DailyGreen runs as a scheduled and on-demand maintenance harness. It discovers, validates, and proposes Pull Requests across explicitly authorized GitHub repositories without manual babysitting or risky automated pushes.

---

## 2. GitHub Credentials and Permissions Setup

### Option A: GitHub App (Recommended for Multi-Repo / Enterprise)
1. In your GitHub Organization or Account Settings, navigate to **Developer Settings -> GitHub Apps -> New GitHub App**.
2. Set permissions:
   - **Repository contents**: Read & Write (for branch and commit creation during delivery)
   - **Pull requests**: Read & Write (for opening PRs)
   - **Issues**: Read (for discovering tasks labeled `dailygreen`)
3. Install the App strictly on the authorized repositories.
4. Generate a Private Key and configure secrets `GH_APP_ID` and `GH_APP_PRIVATE_KEY` in GitHub Actions.

### Option B: Fine-Grained Personal Access Token (PAT)
1. Navigate to **Developer Settings -> Personal Access Tokens -> Fine-grained tokens**.
2. Select **Only select repositories** and pick only the authorized repositories.
3. Grant minimum repository permissions:
   - `Contents: Read and Write`
   - `Pull Requests: Read and Write`
   - `Issues: Read-only`
4. Store the token as `GITHUB_TOKEN` in GitHub Secrets.

---

## 3. Windows PowerShell Operational Runbook (Phase 1 Read-Only Integration)

This section provides exact Windows PowerShell commands for configuring an authorized repository, supplying credentials securely, validating configuration, verifying GitHub read-only access, discovering maintenance candidates, and inspecting run history.

### Step 1: Configure Your Authorized Repository
1. Copy the example configuration to `config/repos.yml`:
   ```powershell
   Copy-Item config\repos.example.yml config\repos.yml
   ```
2. Open `config\repos.yml` in your editor and configure your specific authorized repository:
   ```yaml
   repositories:
     - name: "your-org/your-repo"
       default_branch: "main"
       enabled: true
       max_diff_lines: 120
       timeout_seconds: 300
       allowed_paths:
         - "docs/**"
         - "README.md"
       denied_paths:
         - "pyproject.toml"
         - "setup.py"
         - ".github/**"
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

> [!NOTE]
> `config/repos.yml` is listed in `.gitignore` and is kept strictly out of version control. DailyGreen fails closed if a repository is not explicitly present in `config/repos.yml`.

### Step 2: Supply GitHub Token Securely in PowerShell
Never commit tokens or write them to files. Use one of the following methods to inject the token into the current PowerShell process:

**Method A: Secure Prompt (Recommended - No token echoing or command history logging)**
```powershell
$secureToken = Read-Host -Prompt "Enter GitHub Personal Access Token (Read-Only)" -AsSecureString
$env:GITHUB_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
```

**Method B: In-Memory Session Variable**
```powershell
$env:GITHUB_TOKEN = "ghp_yourTokenHere"
```

To clear the token after your session:
```powershell
Remove-Item Env:\GITHUB_TOKEN
```

### Step 3: Validate Configuration
Verify that `config/repos.yml` conforms to schema, path allowlist rules, and security limits:
```powershell
python -m dailygreen.cli check-config --repos-config config/repos.yml
```
**Expected Output**:
```text
Configuration validated successfully:
  - Enabled (Global Kill Switch): True
  - Dry Run Default: True
  - Max Diff Lines Policy: 150
  - AI Provider: mock (Model: gemini-1.5-flash)
  - Authorized Repositories (1):
    * your-org/your-repo [ENABLED] (Tasks: doc_links, doc_formatting, doc_typos, curated_backlog, issue_task)
```

### Step 4: Verify GitHub Read-Only Connectivity
Execute `check-github` to verify GitHub authentication, rate limits, and repository access:
```powershell
python -m dailygreen.cli check-github --repo your-org/your-repo
```
Or check all enabled repositories in `config/repos.yml`:
```powershell
python -m dailygreen.cli check-github
```

**Offline / Mock verification** (works without network or token):
```powershell
python -m dailygreen.cli check-github --mock-github --repos-config config/repos.example.yml
```

**Expected Output**:
```text
=== GitHub Read-Only Connectivity Check ===
Token Status: DETECTED (credentials provided via parameter or GITHUB_TOKEN)
API Rate Limit: 4999/5000 remaining (resets at ...)
Authenticated Identity: your-github-handle (Type: User)

Verifying Repository Access: your-org/your-repo
  - Status: ACCESSIBLE
  - Visibility: Public
  - Remote Default Branch: main
  - Permissions: Read: True, Write: False, Admin: False
  - Issues labeled 'dailygreen': 0 open issue(s) discovered
  - Open Pull Requests: 0 found

Read-Only Check Completed: Zero remote mutations performed.
```

### Step 5: Discover Maintenance Candidates in Read-Only Mode
Discover the highest-priority legitimate maintenance candidate without making any changes:
```powershell
python -m dailygreen.cli discover --repo your-org/your-repo
```

**Expected Output (Candidate Found)**:
```text
Read-Only Discovery Result:
  Status: CANDIDATE_DISCOVERED (Proposed candidate only; no changes applied)
  Task Title: Fix broken relative links in docs
  Task ID: doc-link-fix-guide
  Source: doc_links
  Risk Level: low
  Target Files: ['docs/guide.md']
  Rationale: Broken relative links degrade reader navigation.
  Acceptance Criteria:
    - Target markdown file exists and contains broken relative link
    - Link targets are resolved to valid paths

Notice: Discovered candidate is proposed only. Zero remote or local modifications were made.
```

**Expected Output (No Task Found)**:
```text
Read-Only Discovery Result:
  Status: NO_TASK
  Notice: No eligible maintenance tasks found for repository 'your-org/your-repo'. Zero modifications performed.
```

### Step 6: View History and Diagnose Errors
Inspect recorded runs and diagnoses:
```powershell
python -m dailygreen.cli report
```

#### Common Diagnostic Scenarios:
- **HTTP 401 Unauthorized**: The provided token is invalid, expired, or malformed. Re-enter a valid Personal Access Token using Step 2.
- **HTTP 404 Repository Inaccessible**: Either the repository name is misspelled or the authenticated token lacks read permission for that repository. Verify repository spelling and PAT resource permissions.
- **HTTP 403 Rate Limit**: GitHub API rate limits have been exhausted. Check the reset time reported by `check-github`. Authenticated PATs receive 5,000 requests/hour compared to 60 for unauthenticated requests.
- **Baseline Test Failure**: The repository baseline test command failed prior to applying any changes. DailyGreen will refuse to modify an already-broken repository.

---

## 4. Scheduling and Backup Architecture

DailyGreen executes on a scheduled cadence in Asia/Tashkent time (UTC+5, no DST):

- **Primary Scheduled Run**: 22:15 Asia/Tashkent -> `15 17 * * *` UTC.
- **Backup Scheduled Run**: 22:35 Asia/Tashkent -> `35 17 * * *` UTC.

### How the Backup Run Works
The backup run executes 20 minutes after the primary run. Before doing any work, it checks the persistent idempotency state and open PRs.
- If the primary run succeeded in completing a task today, the backup run logs:
  `Backup run: Primary run has already completed a maintenance task today. Skipping duplicate execution.`
  and exits with code 0 (`SKIPPED`).
- If the primary run was skipped, failed, or missed due to GitHub Actions queue delays, the backup run picks up an eligible task.

> [!NOTE]
> GitHub Actions schedules are best-effort and subject to runner queue delays during peak hours. The backup run provides high-availability resilience without duplicating Pull Requests.

---

## 5. Local Execution and Testing

### 1. Test in Dry-Run Mode (Safe, No Remote Calls)
```bash
python -m dailygreen.cli run --repo my-org/my-project --dry-run
```

### 2. Run Task Discovery Only
```bash
python -m dailygreen.cli discover --repo my-org/my-project
```

### 3. Inspect Run History
```bash
python -m dailygreen.cli report
```

---

## 6. GitHub Actions Manual Dry-Run Execution

To safely test the complete GitHub Actions pipeline in simulation mode without writing to your repository:

1. Navigate to your DailyGreen repository on GitHub.
2. Go to **Actions** -> **DailyGreen Maintenance Automation**.
3. Click **Run workflow**.
4. Inputs:
   - **Specific authorized repository**: e.g., `my-org/my-project` (or leave empty for all).
   - **Run in dry-run simulation mode**: Keep set to `true` (default).
5. Click **Run workflow**.

### Security Boundary Guarantees:
- **Worker Job**: Runs in an isolated sandbox with read-only permissions (`contents: read`, `issues: read`). Evaluates baseline checks, tests, task discovery, and quality gates. If a task passes, it uploads `.dailygreen/sealed_task.json`.
- **Delivery Job**: Evaluates the condition `if: needs.worker.outputs.has_task == 'true' && needs.worker.outputs.dry_run != 'true'`. Because `dry_run` is `true`, **the delivery job is completely skipped**. No runner ever holds write credentials during dry-run execution.

---

## 7. Opt-In Live GitHub Integration Testing

DailyGreen includes an opt-in integration test suite designed to verify real GitHub API connectivity against a **disposable sandbox test repository**.

### Prerequisites
- A dedicated disposable GitHub repository (e.g. `disposable-org/sandbox-repo`). Never use production or personal profile repositories.
- A GitHub Personal Access Token or GitHub App token with `contents: write`, `pull_requests: write`, and `issues: read`.
- Add the test repository to your `config/repos.yml`.

### Step 1: Read-Only Connectivity Check (Safe, No Mutations)
Set the required environment variables:
```bash
export RUN_LIVE_GITHUB_TEST=1
export LIVE_GITHUB_TEST_REPO="disposable-org/sandbox-repo"
export LIVE_GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
```
Run the read-only connectivity test:
```bash
python -m pytest tests/integration/test_live_github.py -k test_live_github_connectivity_read_only -v
```
**Expected Outcome**: Validates repository connectivity, permissions, issue retrieval, and open PR listing. Zero remote branches or PRs are created.

### Step 2: Controlled Live PR Delivery Verification (Explicit Opt-In)
To verify branch and PR creation on the disposable repository:
```bash
export ALLOW_LIVE_MUTATIONS=1
python -m pytest tests/integration/test_live_github.py -k test_live_github_pr_delivery_opt_in -v
```
**Expected Outcome**:
1. Creates a temporary branch `dailygreen/live-test-<timestamp>`.
2. Creates a verified test Pull Request.
3. Tests duplicate PR detection (asserts rejection on duplicate attempt).
4. Cleans up and deletes the remote test branch.

---

## 8. Circuit Breaker and Failure Recovery

DailyGreen includes an automated circuit breaker to prevent repeated failures on broken repositories:

- If a repository encounters **3 consecutive failures** (e.g. broken baseline, test failures, or syntax errors), DailyGreen trips the circuit breaker and marks the repository as skipped on subsequent runs.
- **Lease Expiration**: Active run leases expire automatically after 30 minutes to recover from crashed or interrupted runner processes.
- **Manual Reset**: Maintainers can resolve the underlying defect, run the repository tests locally, and clear the failure counter in `.dailygreen/state.json`:
  ```json
  "consecutive_failures": { "my-org/my-project": 0 },
  "circuit_tripped": { "my-org/my-project": false }
  ```

---

## 9. Explicit Human Approval Before Production Activation

Before changing DailyGreen to live delivery (`DRY_RUN=false` or scheduled live PR publication):

1. **Perform Local Dry-Run**: Run `dailygreen run --dry-run` and verify `status=dry_run_completed`.
2. **Review Proposed Diffs**: Inspect generated diffs to ensure changes are accurate, minimal, and non-breaking.
3. **Confirm Baseline Checks**: Ensure `baseline_command` passes cleanly on all authorized repositories.
4. **Maintainer Sign-Off**: Do not enable scheduled live runs without formal sign-off from authorized repository owners. Human maintainers always retain final merge authority for all Pull Requests.

---

## 10. Understanding GitHub Contribution Verification

DailyGreen strictly adheres to GitHub's contribution accounting semantics:

1. **Commit Email Association**: Commits generated during delivery use the configured Git author email. For commits to appear on your contribution graph, this email must be added and verified in your GitHub account settings.
2. **Default Branch Requirement**: Commits on branches or Pull Requests **do not** register as green contribution squares until the Pull Request is merged into the default branch (`main`) or `gh-pages`.
3. **Pull Request Activity**: Opening a Pull Request counts towards your contribution activity only if you have enabled **Include private contributions in your profile** or public PR activity in your GitHub profile settings.
4. **Honest Reporting**: DailyGreen never reports a contribution as verified unless confirmed by GitHub. If status cannot be confirmed, it reports `UNKNOWN`.

---

## 11. Production Observability & SRE Metrics

DailyGreen exposes standard HTTP monitoring endpoints:

| Endpoint | Purpose | Format |
| :--- | :--- | :--- |
| `GET /api/health` | Liveness & Readiness probe (Node, Git, Python, Invariants) | JSON |
| `GET /api/metrics` | SRE Observability (HTTP latencies p50/p95, memory, disk, scheduler ticks) | JSON |
| `GET /api/logs` | Structured application logs with correlation IDs and levels | JSON |
| `GET /api/backups` | Catalog of disaster recovery snapshots and SHA-256 seals | JSON |

### SRE Alerting Thresholds
- **Circuit Breaker Alert**: Trigger P2 alert if `circuit_tripped_repos` array is non-empty.
- **Latency Spike**: Alert if `p95_latency_ms > 2000ms`.
- **Rate Limiting Anomaly**: Alert if `client_error_4xx` rate exceeds 20% of total traffic.
- **Disk Storage Footprint**: Alert if `.dailygreen-data` exceeds 5GB.

---

## 12. Disaster Recovery & Emergency Procedures

### Immediate Kill Switch
Toggle the UI **SYSTEM ENABLED** button to **DISABLED** or execute:
```bash
curl -X POST http://localhost:3000/api/policy -H "Content-Type: application/json" -d '{"enabled": false}'
```

### Creating Disaster Recovery Snapshot
```bash
./scripts/backup.sh "Emergency Pre-Maintenance Snapshot"
```

### Restoring State from Verified Backup
```bash
./scripts/restore.sh <backup-id>
```
