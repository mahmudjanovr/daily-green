# Supervised Gemini Dry-Run Runbook

## Notice & Preconditions
> [!IMPORTANT]
> **Human Operator Required**: Antigravity agents are strictly prohibited from generating, inventing, or persisting a `GEMINI_API_KEY`. This runbook is intended solely for an authorized human engineer operating in a local, supervised PowerShell terminal session.
>
> **Safety Guarantees in Place**:
> - `dry_run = true` (default): Zero Git branches or PRs will be created or pushed to remote GitHub.
> - `ALLOW_LIVE_MUTATIONS = false`: Enforced by security gate.
> - `max_workers = 1`: Strictly sequential execution.
> - Working directory isolation: Cloned in temporary workspace; original checkout is untouched.

---

## 1. Environment Preparation (One-Session Only)

Open a dedicated **PowerShell** window. Do NOT persist the API key into user or system environment variables.

```powershell
# Navigate to the DailyGreen repository root
cd C:\Users\b2506583\Documents\dailyGreen

# Set the Gemini API key strictly for this single PowerShell process
$env:GEMINI_API_KEY = "AIzaSy_YOUR_ACTUAL_GEMINI_KEY_HERE"

# Define isolated temporary state directory to prevent contamination with prior runs
$STATE_DIR = "$env:TEMP\dailygreen_gemini_supervised_state"
Remove-Item -Recurse -Force $STATE_DIR -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $STATE_DIR -Force
```

---

## 2. Execute the Supervised Dry-Run

Run DailyGreen with `--repo mahmudjanovr/tolkin-olami`, pointing `--source-dir` to your local clean checkout of Tolkien Olami:

```powershell
python -m dailygreen.cli run `
  --repo mahmudjanovr/tolkin-olami `
  --source-dir "C:\Users\b2506583\Documents\web\tolkin-olami" `
  --state-dir $STATE_DIR `
  --dry-run
```

---

## 3. Locate and Inspect the Sealed Diff Artifact

Once the execution completes, locate the generated sealed artifact:

```powershell
# List generated artifact JSON files
Get-ChildItem -Path "$STATE_DIR\artifacts" -Filter "*.json"

# Capture path to the newest artifact
$ARTIFACT_PATH = (Get-ChildItem -Path "$STATE_DIR\artifacts\*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Write-Host "Inspecting Artifact: $ARTIFACT_PATH"

# View summary metadata and task states
Get-Content $ARTIFACT_PATH | ConvertFrom-Json | Select-Object -ExpandProperty tasks | Format-Table id, title, risk_level, status

# Print the cryptographic patch hash and full unified diff
python -c @"
import json
data = json.load(open(r'$ARTIFACT_PATH', encoding='utf-8'))
for t in data.get('tasks', []):
    print(f'=== TASK: {t[\"id\"]} ({t[\"status\"]}) ===')
    qg = t.get('quality_gate') or {}
    print(f'Patch Seal SHA256: {qg.get(\"patch_hash\")}')
    print('--- VERIFIED DIFF ---')
    print(qg.get('verified_diff', '<NO DIFF>'))
"@
```

---

## 4. Human Review Checklist for the Verified Diff

Before approving or proceeding, verify the following criteria:

- [ ] **Allowed Paths**: Are all modified files within `allowed_paths` (`README.md`, `src/content/**/*.md`)? Are configuration or build files (`package.json`, `astro.config.mjs`, `tsconfig.json`) untouched?
- [ ] **Minimality & Scope**: Is the change minimal and focused strictly on the task objective (under 50 lines changed)?
- [ ] **Markdown Link Resolution**:
  - [ ] If links were added or modified, do all target files actually exist on disk?
  - [ ] Are self-links absent (file not linking to itself)?
  - [ ] Are administrative/unrelated links absent (no random links to `LICENSE` or `.gitignore`)?
- [ ] **Code Fence Preservation**: If formatting or prose was modified, are code blocks (```` ```...``` ````) completely untouched?
- [ ] **Secret Scanning**: Are there zero API keys, auth tokens, passwords, or credentials in the diff?
- [ ] **Build Validation**: Does the baseline command (`npm run build`) pass cleanly with the patch applied?

---

## 5. Abort and Cleanup

Immediately revoke the key from the PowerShell session and wipe the temporary state directory:

```powershell
# 1. Unset the session API key
Remove-Item Env:\GEMINI_API_KEY

# 2. Delete the temporary state directory
Remove-Item -Recurse -Force $STATE_DIR -ErrorAction SilentlyContinue

# 3. Verify original Tolkien Olami repository remains clean and completely unmodified
git -C "C:\Users\b2506583\Documents\web\tolkin-olami" status
```
