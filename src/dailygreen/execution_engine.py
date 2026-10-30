"""Autonomous execution engine: orchestrates multi-task queue, sequential execution, and idempotent retries."""

import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.delivery import deliver_pull_request
from dailygreen.github_client import GitHubClient
from dailygreen.models import (
    DeliveryResult,
    FailureClassification,
    QualityGateResult,
    QueueSummary,
    RunReport,
    RunStatus,
    Task,
    TaskStatus,
)
from dailygreen.quality_gate import evaluate_quality_gate
from dailygreen.repository_manager import verify_managed_workspace_ownership
from dailygreen.retry import evaluate_retry_eligibility
from dailygreen.security import safe_git_command
from dailygreen.state import StateManager
from dailygreen.task_engine import implement_task
from dailygreen.task_queue import TaskQueue
from dailygreen.worker import run_baseline_checks, run_validation_checks


logger = logging.getLogger("dailygreen")


import hashlib

class TaskTimeoutError(Exception):
    """Raised when task execution exceeds configured task_timeout_seconds."""
    pass


class WorkspaceContaminationError(Exception):
    """Raised when unrecoverable workspace contamination is detected, such as alteration of pre-existing untracked files."""
    pass


class WorkspaceSnapshot:
    """Pre-task snapshot of tracked modifications and untracked file content hashes."""
    def __init__(self, modified_tracked: set[str], untracked_hashes: dict[str, str]):
        self.modified_tracked = modified_tracked
        self.untracked_hashes = untracked_hashes


def _compute_file_sha256(filepath: Path) -> str:
    """Calculate SHA-256 hash of a file for integrity verification."""
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


class ExecutionEngine:
    """
    Autonomous Execution Engine for DailyGreen:
    - Enforces strictly sequential execution (max_workers=1) for shared workspace safety
    - Dispatches ready tasks from the TaskQueue respecting historical and intra-run dependencies
    - Implements cooperative deadline checks at execution stage boundaries
    - Executes tasks with plan, validation, and quality gates
    - Advances local repository baseline cleanly between sequential tasks
    - Handles transient failures with idempotent retries and exponential backoff
    - Prevents unsafe retries on task timeout or permanent policy failures
    """

    def __init__(
        self,
        repo_config: RepoConfig,
        config: DailyGreenConfig,
        github_client: GitHubClient,
        state_mgr: StateManager,
        ai_adapter: AIAdapter,
        workspace_path: Path,
        baseline_result: Optional[Any] = None,
        max_workers: int = 1,
        max_retries: int = 2,
        retry_backoff_factor: float = 1.0,
        task_timeout_seconds: int = 300,
        dry_run: bool = True,
        worker_only: bool = False,
        today_str: Optional[str] = None,
    ):
        if max_workers != 1:
            raise ValueError(
                f"Parallel worker execution is not supported in shared workspaces (max_workers={max_workers}). "
                "max_workers must be strictly 1."
            )

        self.repo_config = repo_config
        self.config = config
        self.github_client = github_client
        self.state_mgr = state_mgr
        self.ai_adapter = ai_adapter
        self.workspace_path = workspace_path
        self.baseline_result = baseline_result
        self.current_baseline_result = baseline_result
        self.max_workers = 1
        self.max_retries = max(0, min(5, max_retries))
        self.retry_backoff_factor = max(0.1, retry_backoff_factor)
        self.task_timeout_seconds = task_timeout_seconds
        self.dry_run = dry_run
        self.worker_only = worker_only
        self.today_str = today_str or datetime.utcnow().strftime("%Y-%m-%d")
        self.initial_base_sha = self._get_head_sha()

    def _get_head_sha(self) -> Optional[str]:
        """Query Git for the current HEAD commit SHA with strict timeout."""
        if (self.workspace_path / ".git").exists():
            try:
                res = subprocess.run(
                    safe_git_command(["git", "rev-parse", "HEAD"]),
                    cwd=str(self.workspace_path),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                )
                return res.stdout.strip()
            except Exception:
                pass
        return None

    def _get_git_status_files(self) -> tuple[set[str], dict[str, str]]:
        """
        Query Git status porcelain for modified tracked files and untracked files with content hashes.
        Returns (modified_tracked_set, untracked_hashes_dict).
        """
        if not (self.workspace_path / ".git").exists():
            return set(), {}

        res = subprocess.run(
            safe_git_command(["git", "status", "--porcelain=v1"]),
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if res.returncode != 0:
            return set(), {}

        modified_tracked: set[str] = set()
        untracked_hashes: dict[str, str] = {}

        for raw_line in res.stdout.splitlines():
            line = raw_line.rstrip()
            if len(line) < 4:
                continue
            status_code = line[:2]
            raw_path = line[3:].strip()
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ")[-1].strip()
            rel_path = raw_path.strip('"')

            if status_code == "??":
                full_p = self.workspace_path / rel_path
                if full_p.is_file():
                    untracked_hashes[rel_path] = _compute_file_sha256(full_p)
            else:
                modified_tracked.add(rel_path)

        return modified_tracked, untracked_hashes

    def _capture_workspace_snapshot(self) -> WorkspaceSnapshot:
        """Capture pre-task workspace snapshot to safely detect unexpected modifications."""
        modified_tracked, untracked_hashes = self._get_git_status_files()
        return WorkspaceSnapshot(modified_tracked=modified_tracked, untracked_hashes=untracked_hashes)

    def _safe_task_cleanup(self, task: Task, pre_snapshot: Optional[WorkspaceSnapshot] = None) -> None:
        """
        Safely restore files modified or created by the current task (DG3-08).
        - Verifies workspace ownership via HMAC with the state directory signing key.
        - Reverts all task target files and ANY unexpected tracked files modified during execution.
        - Never uses blanket `git checkout HEAD -- .` or `git clean -fd`.
        - Strictly preserves pre-existing user untracked files.
        - Unlinks only newly created untracked files.
        - If a pre-existing untracked file was modified or deleted, raises WorkspaceContaminationError.
        """
        if not verify_managed_workspace_ownership(
            self.workspace_path,
            expected_repo=self.repo_config.name,
            state_dir=self.state_mgr.state_dir,
        ):
            logger.error(
                f"Ownership verification failed: workspace '{self.workspace_path}' is not a verified "
                "DailyGreen-managed disposable clone. Destructive Git cleanup refused."
            )
            return

        if not (self.workspace_path / ".git").exists():
            return

        # 1. Reset staging index without touching working tree files
        subprocess.run(
            safe_git_command(["git", "reset", "HEAD"]),
            cwd=str(self.workspace_path),
            capture_output=True,
            check=False,
            timeout=30,
        )

        curr_tracked, curr_untracked = self._get_git_status_files()

        # 2. Determine which tracked files were altered during the task
        pre_tracked = pre_snapshot.modified_tracked if pre_snapshot else set()
        newly_modified_tracked = (curr_tracked - pre_tracked) | set(task.target_files or [])

        for rel_path in newly_modified_tracked:
            target_p = self.workspace_path / rel_path
            # Check if tracked in HEAD
            res_tracked = subprocess.run(
                safe_git_command(["git", "ls-tree", "HEAD", rel_path]),
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if res_tracked.stdout.strip():
                # Revert specifically this tracked file
                subprocess.run(
                    safe_git_command(["git", "checkout", "HEAD", "--", rel_path]),
                    cwd=str(self.workspace_path),
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
            elif target_p.exists() and not (pre_snapshot and rel_path in pre_snapshot.untracked_hashes):
                # File was newly added/untracked during task
                try:
                    target_p.unlink(missing_ok=True)
                except Exception:
                    pass

        # 3. Handle untracked files with strict preservation of pre-existing user files
        if pre_snapshot:
            # Verify pre-existing untracked files were not modified or deleted
            for orig_rel_path, orig_hash in pre_snapshot.untracked_hashes.items():
                orig_file = self.workspace_path / orig_rel_path
                if not orig_file.exists():
                    msg = f"Pre-existing untracked file '{orig_rel_path}' was deleted during task execution."
                    logger.critical(f"{msg} Preserving workspace for inspection.")
                    raise WorkspaceContaminationError(msg)
                curr_hash = _compute_file_sha256(orig_file)
                if curr_hash != orig_hash:
                    msg = f"Pre-existing untracked file '{orig_rel_path}' was modified during task execution."
                    logger.critical(f"{msg} Preserving workspace for inspection.")
                    raise WorkspaceContaminationError(msg)

            # Safely unlink only newly created untracked files
            new_untracked = set(curr_untracked.keys()) - set(pre_snapshot.untracked_hashes.keys())
            for rel_path in new_untracked:
                try:
                    (self.workspace_path / rel_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def run(self, queue: TaskQueue) -> tuple[list[Task], QueueSummary]:
        """
        Execute the multi-task queue strictly sequentially until all tasks have reached
        a terminal state (COMPLETED, FAILED, or SKIPPED).
        Returns (all_tasks, queue_summary).
        """
        # Resolve dependencies initially
        queue.resolve_dependencies(state_mgr=self.state_mgr)

        while not queue.is_finished():
            # Re-check dependencies and cascades
            queue.resolve_dependencies(state_mgr=self.state_mgr)

            # In safe sequential mode (max_workers=1), fetch the next ready task
            ready = queue.get_ready_tasks(state_mgr=self.state_mgr)
            if ready:
                task = ready[0]
                worker_id = "worker-1"
                queue.mark_running(task.id, worker_id)
                self._execute_single_task(task, queue, worker_id)
            else:
                # No tasks currently ready. Check if tasks are waiting for backoff retry.
                now = time.time()
                retry_tasks = [t for t in queue.get_all_tasks() if t.status == TaskStatus.RETRY_SCHEDULED]
                if retry_tasks:
                    earliest = min(t.next_retry_time or now for t in retry_tasks)
                    wait_seconds = max(0.05, min(earliest - now, 2.0))
                    time.sleep(wait_seconds)
                else:
                    # Deadlock or unresolvable state: finalize remaining as skipped
                    for t in queue.get_all_tasks():
                        if t.status in (TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED):
                            queue.mark_skipped(t.id, "Dependencies unfulfilled or queue unresolved")
                    break

        # Final dependency cascade check
        queue.resolve_dependencies(state_mgr=self.state_mgr)
        summary = queue.summary()
        return queue.get_all_tasks(), summary

    def _execute_single_task(self, task: Task, queue: TaskQueue, worker_id: str) -> None:
        """
        Execute a single task with plan implementation, validation, and retry handling.
        Enforces cooperative deadline checks at safe execution boundaries (DG3-02)
        and preserves clean Git baseline tracking across sequential tasks (DG3-08).
        """
        start_time = time.time()
        logger.info(f"[{worker_id}] Executing task '{task.id}' (Attempt {task.attempt_count}/{task.max_retries})")

        # Baseline SHA capture for consistent sequential task evaluation (DG3-08)
        task_base_sha = self._get_head_sha()
        task.metadata["initial_run_base_sha"] = self.initial_base_sha
        task.metadata["task_base_sha"] = task_base_sha

        # Cooperative deadline check at execution stage boundaries (DG3-02)
        def _check_deadline(stage: str):
            elapsed = time.time() - start_time
            if elapsed > self.task_timeout_seconds:
                raise TaskTimeoutError(
                    f"Task '{task.id}' exceeded execution timeout ({self.task_timeout_seconds}s) "
                    f"during stage '{stage}' (elapsed {round(elapsed, 2)}s)."
                )

        # Capture pre-task snapshot to detect and safely revert unexpected modifications
        pre_snapshot = self._capture_workspace_snapshot()

        try:
            # Stage 1: Pre-implementation deadline check & AI implementation
            _check_deadline("pre_implementation")
            diff_text = implement_task(self.workspace_path, task, self.ai_adapter)

            # Stage 2: Post-implementation deadline check & validation checks
            _check_deadline("post_implementation")
            post_tests, post_lints = run_validation_checks(self.workspace_path, self.repo_config)

            # Stage 3: Pre-quality-gate deadline check & quality gate evaluation
            _check_deadline("pre_quality_gate")
            qg_result = evaluate_quality_gate(
                workspace_dir=self.workspace_path,
                task=task,
                diff_text=diff_text,
                repo_config=self.repo_config,
                policy=self.config.policy,
                baseline_result=self.current_baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
            )

            # Stage 4: Pre-delivery deadline check
            _check_deadline("pre_delivery")

            duration = time.time() - start_time

            if not qg_result.passed:
                self._safe_task_cleanup(task, pre_snapshot)
                self._handle_failure(task, queue, qg_result.reason, duration)
                return

            # Stage 5: Delivery or Worker-Only Sealed Artifact
            delivery_res = None
            if not self.worker_only:
                delivery_res = deliver_pull_request(
                    workspace_dir=self.workspace_path,
                    task=task,
                    quality_gate=qg_result,
                    diff_text=qg_result.verified_diff or diff_text,
                    repo_config=self.repo_config,
                    policy=self.config.policy,
                    github_client=self.github_client,
                    dry_run=self.dry_run,
                    date_str=self.today_str,
                    allow_live_mutations=self.config.allow_live_mutations,
                )

                if not delivery_res.success:
                    self._safe_task_cleanup(task, pre_snapshot)
                    self._handle_failure(task, queue, delivery_res.message, duration)
                    return

            # Stage 6: Success - record completion and commit to local workspace for next task
            if not self.worker_only:
                self.state_mgr.record_task_completion(
                    repo=self.repo_config.name,
                    task_id=task.id,
                    details={
                        "branch": delivery_res.branch_name if delivery_res else None,
                        "pr_number": delivery_res.pr_number if delivery_res else None,
                        "dry_run": self.dry_run,
                        "worker_id": worker_id,
                        "duration": round(duration, 2),
                    },
                    date_str=self.today_str,
                )

            # Advance local Git HEAD only if a subsequent task in queue depends on this task (DG3-08).
            # Otherwise, revert modified files so subsequent independent tasks evaluate cleanly against initial_base_sha.
            remaining_tasks = queue.get_all_tasks()
            is_prereq_for_later = any(
                task.id in t.dependencies
                for t in remaining_tasks
                if t.status in (TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED)
            )

            if is_prereq_for_later:
                if task.target_files:
                    subprocess.run(
                        safe_git_command(["git", "add"] + task.target_files),
                        cwd=str(self.workspace_path),
                        capture_output=True,
                        check=False,
                        timeout=30,
                    )
                    clean_title = task.title.replace("\n", " ").replace("\r", " ").strip()
                    subprocess.run(
                        safe_git_command(["git", "commit", "--no-verify", "-m", f"docs: [dailygreen] {clean_title}"]),
                        cwd=str(self.workspace_path),
                        capture_output=True,
                        check=False,
                        timeout=30,
                    )
            else:
                # Safely restore only files modified by this task; preserve baseline for next task (DG3-08)
                self._safe_task_cleanup(task, pre_snapshot)

            # Refresh baseline check result after local commit to establish true baseline for next task
            try:
                self.current_baseline_result = run_baseline_checks(self.workspace_path, self.repo_config)
            except Exception:
                pass

            task.quality_gate = qg_result
            task.delivery = delivery_res
            queue.mark_completed(task.id, duration=duration)
            logger.info(f"[{worker_id}] Task '{task.id}' COMPLETED successfully in {round(duration, 2)}s.")

        except WorkspaceContaminationError as e:
            duration = time.time() - start_time
            logger.critical(f"[{worker_id}] Task '{task.id}' caused unrecoverable workspace contamination: {e}")
            self.state_mgr.record_failure(self.repo_config.name, str(e))
            queue.mark_failed(task.id, str(e), is_transient=False, duration=duration)
            # Stop queue immediately to preserve the contaminated workspace for human inspection
            for t in queue.get_all_tasks():
                if t.status in (TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED):
                    queue.mark_skipped(t.id, f"Queue halted: workspace contamination detected ({e})")
            return

        except TaskTimeoutError as e:
            duration = time.time() - start_time
            try:
                self._safe_task_cleanup(task, pre_snapshot)
            except Exception:
                pass
            logger.error(f"[{worker_id}] Task '{task.id}' TIMED OUT after {round(duration, 2)}s: {e}")
            self.state_mgr.record_failure(self.repo_config.name, str(e))
            # Permanently mark as failed (is_transient=False) to prevent unsafe concurrent retries
            queue.mark_failed(task.id, str(e), is_transient=False, duration=duration)
            return

        except Exception as e:
            duration = time.time() - start_time
            try:
                self._safe_task_cleanup(task, pre_snapshot)
            except Exception:
                pass
            self._handle_failure(task, queue, str(e), duration)

    def _handle_failure(self, task: Task, queue: TaskQueue, error_msg: str, duration: float) -> None:
        """Classify failure and either schedule retry or mark task permanently failed."""
        eligible, reason, classification, backoff = evaluate_retry_eligibility(
            task=task,
            error_msg=error_msg,
            max_retries=self.max_retries,
            backoff_factor=self.retry_backoff_factor,
        )

        if eligible:
            logger.warning(f"Task '{task.id}' failed transiently: {reason}. Scheduling retry in {backoff}s.")
            queue.schedule_retry(task.id, error_msg, backoff_seconds=backoff)
        else:
            is_transient = (classification == FailureClassification.TRANSIENT)
            logger.error(f"Task '{task.id}' failed permanently: {reason}")
            self.state_mgr.record_failure(self.repo_config.name, error_msg)
            queue.mark_failed(task.id, reason, is_transient=is_transient, duration=duration)
