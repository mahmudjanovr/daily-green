"""Scheduling, backup run detection, and multi-repo orchestration."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.ai.factory import get_ai_adapter
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.delivery import deliver_pull_request
from dailygreen.github_client import GitHubClient, MockGitHubClient
from dailygreen.models import QualityGateResult, RunReport, RunStatus, Task
from dailygreen.quality_gate import evaluate_quality_gate
from dailygreen.repository_manager import IsolatedWorkspace
from dailygreen.security import run_security_checks
from dailygreen.state import StateManager
from dailygreen.task_discovery import discover_next_task
from dailygreen.task_engine import get_git_diff, implement_task
from dailygreen.worker import run_baseline_checks, run_validation_checks


def execute_dailygreen_pipeline(
    repo_config: RepoConfig,
    config: DailyGreenConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    ai_adapter: Optional[AIAdapter] = None,
    source_dir: Optional[Path | str] = None,
    is_backup_run: bool = False,
    override_dry_run: Optional[bool] = None,
    worker_only: bool = False,
) -> RunReport:
    """
    Execute the DailyGreen maintenance pipeline on an authorized repository.
    """
    run_id = str(uuid.uuid4())[:8]
    dry_run = override_dry_run if override_dry_run is not None else config.dry_run
    effective_ai_adapter = ai_adapter or get_ai_adapter(config.ai)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    def _return_report(rep: RunReport) -> RunReport:
        state_mgr.record_run(rep.model_dump())
        return rep

    # 1. Global kill switch check
    if not config.enabled:
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.SKIPPED,
            message="DailyGreen is disabled via configuration or DAILYGREEN_ENABLED=false.",
            is_backup_run=is_backup_run,
        ))

    # 2. Repository Authorization & Enablement
    if not repo_config.enabled:
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.SKIPPED,
            message=f"Repository '{repo_config.name}' is disabled in configuration.",
            is_backup_run=is_backup_run,
        ))

    # 3. Circuit breaker check
    if state_mgr.is_circuit_tripped(repo_config.name):
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.FAILED,
            message=f"Circuit breaker is tripped for repository '{repo_config.name}' due to repeated failures. Human intervention required.",
            is_backup_run=is_backup_run,
        ))

    # 4. Backup Run Deduplication check (inspect local state AND remote GitHub API)
    if is_backup_run:
        completed_today = False
        for key in state_mgr._state.get("completed_tasks", {}):
            if key.startswith(f"{today_str}:{repo_config.name.lower()}:"):
                completed_today = True
                break

        # Ground truth check on remote GitHub API (runner-local state might be fresh)
        if not completed_today:
            try:
                open_prs = github_client.get_open_pull_requests(repo_config.name)
                for pr in open_prs:
                    ref = pr.get("head", {}).get("ref", "")
                    if ref.startswith(f"dailygreen/{today_str}"):
                        completed_today = True
                        break
            except Exception:
                pass

        if completed_today:
            return _return_report(RunReport(
                run_id=run_id,
                repo=repo_config.name,
                status=RunStatus.SKIPPED,
                message="Backup run: Primary run has already completed a maintenance task today. Skipping duplicate execution.",
                is_backup_run=True,
            ))

    # 5. Acquire execution lease to prevent concurrent race conditions
    if not state_mgr.acquire_run_lease(repo_config.name, run_id):
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.SKIPPED,
            message=f"Another run is actively in progress for repository '{repo_config.name}'. Skipping to prevent concurrency conflict.",
            is_backup_run=is_backup_run,
        ))

    # 6. Open Isolated Workspace and execute
    clone_url = None
    if not source_dir and not isinstance(github_client, MockGitHubClient):
        clone_url = f"https://github.com/{repo_config.name}.git"
    token = getattr(github_client, "token", None)

    try:
        with IsolatedWorkspace(repo_config=repo_config, source_dir=source_dir, clone_url=clone_url, token=token) as workspace_path:
            # Step A: Baseline test run before any changes
            baseline_result = run_baseline_checks(workspace_path, repo_config)
            if baseline_result is not None and not baseline_result.passed:
                state_mgr.record_failure(repo_config.name, "Baseline test failure")
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.FAILED,
                    quality_gate=QualityGateResult(
                        passed=False,
                        reason=f"Repository baseline tests failed prior to changes (exit code {baseline_result.exit_code})",
                        baseline_result=baseline_result,
                    ),
                    message="Baseline verification failed. Changes cannot be applied safely to an already broken baseline.",
                    is_backup_run=is_backup_run,
                ))

            # Step B: Task Discovery
            task = discover_next_task(
                workspace_dir=workspace_path,
                repo_config=repo_config,
                policy=config.policy,
                github_client=github_client,
                state_mgr=state_mgr,
                ai_adapter=effective_ai_adapter,
            )

            if not task:
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.NO_TASK,
                    message="No legitimate maintenance tasks found. Exiting cleanly without fabricating activity.",
                    is_backup_run=is_backup_run,
                ))

            # Step C: Implement Task
            try:
                diff_text = implement_task(workspace_path, task, effective_ai_adapter)
            except Exception as e:
                state_mgr.record_failure(repo_config.name, f"Task implementation failed: {e}")
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.FAILED,
                    task=task,
                    message=f"Failed to apply task changes: {e}",
                    is_backup_run=is_backup_run,
                ))

            # Step D: Run Post-Change Tests & Lints
            post_tests, post_lints = run_validation_checks(workspace_path, repo_config)

            # Step E: Evaluate Mandatory Quality Gate (seals diff and tree hash)
            qg_result = evaluate_quality_gate(
                workspace_dir=workspace_path,
                task=task,
                diff_text=diff_text,
                repo_config=repo_config,
                policy=config.policy,
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
            )

            if not qg_result.passed:
                state_mgr.record_failure(repo_config.name, f"Quality gate failure: {qg_result.reason}")
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.FAILED,
                    task=task,
                    quality_gate=qg_result,
                    message=f"Quality gate rejected changes: {qg_result.reason}",
                    is_backup_run=is_backup_run,
                ))

            # If worker-only mode is requested (e.g. CI worker job with zero write tokens), write sealed artifact and finish
            if worker_only:
                sealed_dir = Path(config.state_dir)
                sealed_dir.mkdir(parents=True, exist_ok=True)
                sealed_file = sealed_dir / "sealed_task.json"
                import json
                sealed_payload = {
                    "repo": repo_config.name,
                    "task": task.model_dump(),
                    "quality_gate": qg_result.model_dump(),
                    "diff_text": qg_result.verified_diff or diff_text,
                    "dry_run": dry_run,
                    "today_str": today_str,
                }
                with open(sealed_file, "w", encoding="utf-8") as f:
                    json.dump(sealed_payload, f, indent=2)

                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.TASK_COMPLETED,
                    task=task,
                    quality_gate=qg_result,
                    message=f"Worker evaluation passed. Sealed artifact written to {sealed_file}.",
                    is_backup_run=is_backup_run,
                ))

            # Step F: Delivery (Publish Branch and PR, or Dry Run)
            delivery_result = deliver_pull_request(
                workspace_dir=workspace_path,
                task=task,
                quality_gate=qg_result,
                diff_text=qg_result.verified_diff or diff_text,
                repo_config=repo_config,
                policy=config.policy,
                github_client=github_client,
                dry_run=dry_run,
                date_str=today_str,
            )

            # Step G: State recording
            if delivery_result.success:
                state_mgr.record_task_completion(
                    repo=repo_config.name,
                    task_id=task.id,
                    details={
                        "branch": delivery_result.branch_name,
                        "pr_number": delivery_result.pr_number,
                        "dry_run": dry_run,
                    },
                    date_str=today_str,
                )

            overall_status = RunStatus.DRY_RUN_COMPLETED if dry_run else RunStatus.PULL_REQUEST_CREATED

            report = RunReport(
                run_id=run_id,
                repo=repo_config.name,
                status=overall_status,
                task=task,
                quality_gate=qg_result,
                delivery=delivery_result,
                message=delivery_result.message,
                is_backup_run=is_backup_run,
            )
            return _return_report(report)

    except Exception as e:
        state_mgr.record_failure(repo_config.name, f"Unexpected pipeline error: {e}")
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.FAILED,
            message=f"Pipeline encountered unexpected error: {e}",
            is_backup_run=is_backup_run,
        ))
    finally:
        state_mgr.release_run_lease(repo_config.name, run_id)
