# DailyGreen Phase 3 — Human Reviewer Risk & Safety Guide

## Overview

DailyGreen Phase 3 introduces an autonomous execution engine capable of running multi-task queues, managing isolated Git workspaces, staging dependencies via filesystem junctions, enforcing process timeouts, cryptographically sealing diff artifacts, and orchestrating PR deliveries.

This document serves as a high-density, risk-focused audit guide for human reviewers. It details every code path that can delete files, terminate processes, execute subprocesses, or mutate local or remote state.

---

## 1. Audit Table of State-Mutating and Destructive Operations

The following table catalogs every state-mutating and destructive call in `src/`, the exact hazards, the security guards protecting execution, and the covering test:

| Review Order | File & Function | Operation | Hazard / Destructive Capability | Safety Guard | Covering Test |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `delivery.py`<br>`deliver_pull_request` | `git checkout -b <branch>` | Mutates workspace local Git branch | `dry_run` guard blocks remote pushes; workspace is isolated clone | `tests/unit/test_delivery.py::test_deliver_pull_request_dry_run` |
| **2** | `repository_manager.py`<br>`IsolatedWorkspace.cleanup` | `shutil.rmtree(p)` | Deletes `.astro` and `.cache` directories in workspace | Guarded by `verify_managed_workspace_ownership`; targets restricted to `{'.astro', '.cache'}` within workspace `node_modules` | `tests/unit/test_repository_manager.py::test_isolated_dependencies_staging_and_cleanup` |
| **3** | `repository_manager.py`<br>`IsolatedWorkspace.cleanup` | `os.rmdir(str(p))` | Removes Windows NTFS directory junctions to staged packages | Guarded by `verify_managed_workspace_ownership`; `os.rmdir` on Windows junctions removes only junction link, never mutating target files | `tests/unit/test_repository_manager.py::test_isolated_dependencies_staging_and_cleanup` |
| **4** | `repository_manager.py`<br>`IsolatedWorkspace.cleanup` | `os.unlink(str(p))` | Unlinks package symlinks (POSIX) | Guarded by `verify_managed_workspace_ownership`; symlink unlink does not delete target contents | `tests/unit/test_repository_manager.py::test_isolated_dependencies_staging_and_cleanup` |
| **5** | `repository_manager.py`<br>`IsolatedWorkspace.cleanup` | `os.rmdir(str(target_nm))` | Deletes workspace-local `node_modules` directory | Guarded by `verify_managed_workspace_ownership`; only called after directory is empty | `tests/unit/test_repository_manager.py::test_isolated_dependencies_staging_and_cleanup`, `tests/unit/test_workspace_ownership.py::test_isolated_workspace_cleanup_aborts_on_unverified_ownership` |
| **6** | `execution_engine.py`<br>`_safe_task_cleanup` | `git reset HEAD` | Resets Git staging index | Guarded by `verify_managed_workspace_ownership`; does not touch working tree files | `tests/unit/test_unexpected_changes_cleanup.py::test_cleanup_reverts_both_authorized_and_unexpected_tracked_files` |
| **7** | `execution_engine.py`<br>`_safe_task_cleanup` | `git checkout HEAD -- <rel_path>` | Reverts modified tracked files to clean HEAD state | Guarded by `verify_managed_workspace_ownership`; never uses blanket checkout (`git checkout .`); strictly selective | `tests/unit/test_unexpected_changes_cleanup.py::test_cleanup_reverts_both_authorized_and_unexpected_tracked_files` |
| **8** | `execution_engine.py`<br>`_safe_task_cleanup` | `target_p.unlink()` | Deletes newly added target file created during task | Guarded by `verify_managed_workspace_ownership`; excludes pre-existing untracked files | `tests/unit/test_unexpected_changes_cleanup.py::test_cleanup_reverts_both_authorized_and_unexpected_tracked_files` |
| **9** | `execution_engine.py`<br>`_safe_task_cleanup` | `(workspace / rel_path).unlink()` | Deletes newly created untracked files created by rogue task | Guarded by `verify_managed_workspace_ownership`; strictly preserves pre-existing user files via `untracked_hashes` snapshot; raises `WorkspaceContaminationError` if user files modified | `tests/unit/test_unexpected_changes_cleanup.py::test_cleanup_reverts_both_authorized_and_unexpected_tracked_files`, `tests/unit/test_unexpected_changes_cleanup.py::test_tampering_with_pre_existing_untracked_file_halts_and_preserves_workspace` |
| **10** | `worker.py`<br>`kill_process_tree` | `taskkill /F /T /PID` (Windows) / `os.killpg(SIGKILL)` (POSIX) | Forcefully terminates process tree | Only invoked when subprocess exceeds `timeout_seconds`; PID strictly scoped to spawned worker process | `tests/unit/test_process_tree_timeout.py::test_run_command_timeout_kills_process_tree` |
| **11** | `state.py`<br>`acquire_run_lease` / `release_run_lease` | Writes lease records and PID tracking | Mutates concurrency state in `state.json` | Cross-process file locking via `Portalocker`; atomic file writes; PID liveness verification (`is_process_alive`); 1800s timeout | `tests/unit/test_phase3_reliability.py::test_reclaim_orphaned_lease_from_dead_process`, `tests/integration/test_true_crash_recovery.py::test_true_crash_recovery_from_orphaned_lease` |
| **12** | `task_queue.py`<br>`_save_state` | `temp_file.unlink()` | Cleans up atomic write temporary file | File path strictly inside state directory (`queue.json.tmp.<pid>.<uuid>`) | `tests/unit/test_task_queue.py::test_task_queue_save_and_reload` |
| **13** | `cli.py`<br>`deliver_cmd` | `git apply --ignore-whitespace` | Applies patch to isolated delivery clone | Guarded by `ALLOW_LIVE_MUTATIONS` check, quality gate pass, SHA256 patch seal hash match, secret scan, and dry-run check | `tests/unit/test_delivery.py::test_deliver_pull_request_dry_run`, `tests/unit/test_artifact_security.py::test_tampered_patch_fails_validation` |

---

## 2. Comprehensive Call Site Verification (`rmtree`, `rmdir`, `unlink`, `os.remove`, `git clean/checkout/reset`)

A comprehensive grep across `src/` confirms the following exact call sites and their corresponding guards:

```text
src\dailygreen\delivery.py:322: safe_git_command(["git", "checkout", "-b", branch_name]),
src\dailygreen\execution_engine.py:209: safe_git_command(["git", "reset", "HEAD"]),
src\dailygreen\execution_engine.py:236: safe_git_command(["git", "checkout", "HEAD", "--", rel_path]),
src\dailygreen\execution_engine.py:245: target_p.unlink(missing_ok=True)
src\dailygreen\execution_engine.py:268: (self.workspace_path / rel_path).unlink(missing_ok=True)
src\dailygreen\repository_manager.py:350: shutil.rmtree(p)
src\dailygreen\repository_manager.py:356: os.rmdir(str(p))
src\dailygreen\repository_manager.py:358: os.unlink(str(p))
src\dailygreen\repository_manager.py:361: os.rmdir(str(target_nm))
src\dailygreen\task_queue.py:404: temp_file.unlink(missing_ok=True)
```

### Analysis of Ownership Guarding:
1. **`execution_engine.py`**:
   - Every `git reset`, `git checkout`, and `unlink` call in `_safe_task_cleanup` is preceded by:
     ```python
     if not verify_managed_workspace_ownership(
         self.workspace_path,
         expected_repo=self.repo_config.name,
         state_dir=self.state_mgr.state_dir,
     ):
         return
     ```
   - Blanket Git operations (`git checkout HEAD -- .` or `git clean -fd`) are **strictly prohibited and absent from the codebase**.
2. **`repository_manager.py`**:
   - `shutil.rmtree`, `os.rmdir`, and `os.unlink` in `IsolatedWorkspace.cleanup()` are guarded by:
     ```python
     if (self.workspace_path / MARKER_FILENAME).exists():
         if not verify_managed_workspace_ownership(
             self.workspace_path,
             expected_repo=self.repo_config.name,
             state_dir=self.state_dir,
         ):
             return
     ```
   - Staged dependency junctions are removed using `os.rmdir(junction)` on Windows and `os.unlink(symlink)` on POSIX, which never deletes files in the target `source_dir/node_modules`.
3. **`task_queue.py`**:
   - `temp_file.unlink()` only cleans up the temporary write file in the state directory if an atomic rename fails.

---

## 3. Review Order for Human Inspection

Reviewers should follow this sequential path through the codebase to verify critical boundaries:

1. **Workspace Ownership & HMAC Verification**:
   - Inspect `src/dailygreen/repository_manager.py`: `get_or_create_signing_key`, `write_managed_workspace_marker`, and `verify_managed_workspace_ownership`.
   - Confirm signing key is stored in restricted state dir and never copied into workspace clones.
2. **Task Cleanup & Untracked User File Preservation**:
   - Inspect `src/dailygreen/execution_engine.py`: `_capture_workspace_snapshot` and `_safe_task_cleanup`.
   - Verify that pre-existing untracked files are hashed before task execution, and any tampering halts cleanup with `WorkspaceContaminationError`.
3. **Dependency Junction Isolation**:
   - Inspect `src/dailygreen/repository_manager.py`: `IsolatedWorkspace.__enter__` and `IsolatedWorkspace.cleanup`.
   - Confirm packages are linked individually while `.astro` and `.cache` remain independent local directories.
4. **Process Tree Termination**:
   - Inspect `src/dailygreen/worker.py`: `kill_process_tree` and `run_command_in_workspace`.
   - Confirm `TimeoutExpired` triggers process tree termination on Windows (`taskkill /F /T /PID`) and POSIX (`killpg`).
5. **Quality Gate & Adversarial Rejections**:
   - Inspect `src/dailygreen/quality_gate.py`: `validate_semantic_diff` and `evaluate_quality_gate`.
   - Confirm rejection of self-links, unrelated administrative links, fenced code block edits, mass deletions, comment-only patches, secrets, and whitespace-only changes.
6. **Delivery & Mutation Failsafes**:
   - Inspect `src/dailygreen/delivery.py` and `src/dailygreen/cli.py` (`deliver_cmd`).
   - Confirm `ALLOW_LIVE_MUTATIONS` is required for live push/PR creation and that dry-run is default.
