# DailyGreen Live Mutation Authorization Procedure
## Operational Runbook & Safety Protocol (Two-Person Rule)

This document defines the strict operational procedure required to authorize real GitHub mutations (`ALLOW_LIVE_MUTATIONS=true`). 

By default, DailyGreen runs strictly in **DRY-RUN simulation mode** with `allow_live_mutations: false`. Enabling live mutations is an exceptional operational event requiring multi-party review.

---

## 1. Prerequisites (Pre-Flight Verification Checklist)

Before requesting live mutation authorization, the following must be verified:

- [ ] **Dry-Run Track Record**: The repository has completed at least 7 consecutive daily maintenance dry-runs without errors.
- [ ] **Circuit Breaker Status**: The circuit breaker is clear (0 failures recorded in `.dailygreen-data/state.json`).
- [ ] **Baseline Health**: The target repository's baseline test and lint commands execute with 0 failures on the default branch.
- [ ] **Allowlist Scrutiny**: The repository `allowed_paths` is restricted exclusively to non-executable documentation paths (e.g. `docs/**`, `README.md`).
- [ ] **Branch Protection**: The remote GitHub repository enforces branch protection rules requiring status checks and PR reviews before merging into the default branch. Direct pushes to `main` must be disabled on GitHub.
- [ ] **Clean Git Working Tree**: Ephemeral workspaces have no leftover files.

---

## 2. Two-Person Authorization Flow

1. **Requestor Role**:
   - Creates a documented change ticket outlining the repository, planned maintenance scope, and operational window.
   - Provides recent Dry-Run Quality Gate SHA-256 seal proofs.
2. **Reviewer Role (Security / DevSecOps Lead)**:
   - Verifies the pre-flight checklist.
   - Confirms that the target repository has branch protection enabled.
   - Signs and approves the change ticket.

---

## 3. Activation Procedure

1. In the DailyGreen UI or environment configuration, adjust:
   ```bash
   ALLOW_LIVE_MUTATIONS=true
   DRY_RUN=false
   ```
2. In `config/policy.yml`, update `allow_live_mutations`:
   ```yaml
   security:
     allow_live_mutations: true
     dry_run: false
   ```
3. Restart the DailyGreen engine or trigger the scheduled slot.
4. The engine will record an `AUDIT` log entry noting the authorizing personnel and timestamp.

---

## 4. Automatic Safety Circuit Breaker

DailyGreen continuously monitors execution outcomes during live mode:

- If **1 failure** occurs (test failure, lint error, or gate rejection), the execution is aborted immediately and no branch is pushed.
- If **3 consecutive failures** occur on any repository, the repository's **circuit breaker trips**.
- Once tripped:
  - The repository is frozen from further execution.
  - An emergency alert is logged.
  - Human intervention and explicit administrative reset are required to restore automation.

---

## 5. Emergency Deactivation (Kill Switch)

If unexpected behavior is observed:

1. **Instant UI Kill Switch**: Toggle the top-level **SYSTEM ENABLED** switch to **DISABLED**. This stops all workers immediately.
2. **Environment Override**:
   ```bash
   export DAILYGREEN_ENABLED=false
   export ALLOW_LIVE_MUTATIONS=false
   ```
3. Restart the service to force immediate fail-closed state:
   ```bash
   docker compose restart dailygreen
   ```
