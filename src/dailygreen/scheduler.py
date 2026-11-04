"""Scheduling, backup run detection, and multi-repo orchestration with Phase 2 intelligence."""

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.ai.factory import get_ai_adapter
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.delivery import deliver_pull_request
from dailygreen.execution_engine import ExecutionEngine
from dailygreen.github_client import GitHubClient, MockGitHubClient
from dailygreen.models import QualityGateResult, RunReport, RunStatus, Task, TaskStatus
from dailygreen.quality_gate import evaluate_quality_gate
from dailygreen.repository_manager import IsolatedWorkspace
from dailygreen.security import run_security_checks
from dailygreen.state import StateManager
from dailygreen.task_discovery import (
    discover_and_evaluate_queue,
    discover_and_evaluate_task,
    discover_next_task,
)
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
    Includes Phase 2 intelligent task discovery, multi-factor evaluation, structured planning,
    context-aware execution, and automated validation.
    """
    start_time = time.time()
    run_id = str(uuid.uuid4())[:8]
    dry_run = override_dry_run if override_dry_run is not None else config.dry_run
    effective_ai_adapter = ai_adapter or get_ai_adapter(config.ai)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    def _return_report(rep: RunReport) -> RunReport:
        rep.execution_duration_seconds = round(time.time() - start_time, 2)
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

    # 1b. Independent live mutation safety gate check
    if not dry_run and not worker_only and not config.allow_live_mutations:
        return _return_report(RunReport(
            run_id=run_id,
            repo=repo_config.name,
            status=RunStatus.FAILED,
            message="Security violation: Live delivery rejected because ALLOW_LIVE_MUTATIONS is not explicitly enabled.",
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
                if hasattr(github_client, "get_pull_requests"):
                    prs = github_client.get_pull_requests(repo_config.name, state="all")
                else:
                    prs = github_client.get_open_pull_requests(repo_config.name)
                for pr in prs:
                    ref = pr.get("head", {}).get("ref", "")
                    label = pr.get("head", {}).get("label", "")
                    if ref.startswith(f"dailygreen/{today_str}") or f"dailygreen/{today_str}" in label:
                        completed_today = True
                        break
            except Exception as e:
                state_mgr.record_failure(repo_config.name, f"Backup deduplication check failed: {e}")
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.FAILED,
                    message=f"Backup run deduplication check failed: unable to verify remote pull requests due to GitHub API error: {e}",
                    is_backup_run=True,
                ))

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
        with IsolatedWorkspace(
            repo_config=repo_config,
            source_dir=source_dir,
            clone_url=clone_url,
            token=token,
            state_dir=state_mgr.state_dir,
        ) as workspace_path:
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

            # Step B: Intelligent Task Discovery, Evaluation, and Planning into TaskQueue
            effective_max_tasks = repo_config.max_tasks_per_run or config.execution.max_tasks_per_run
            queue, discovery_summary = discover_and_evaluate_queue(
                workspace_dir=workspace_path,
                repo_config=repo_config,
                policy=config.policy,
                github_client=github_client,
                state_mgr=state_mgr,
                ai_adapter=effective_ai_adapter,
                max_tasks=effective_max_tasks,
            )

            active_queue_tasks = [t for t in queue.get_all_tasks() if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRY_SCHEDULED)]
            if len(active_queue_tasks) == 0:
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.NO_TASK,
                    discovery_summary=discovery_summary,
                    rejection_reason="No legitimate maintenance tasks found meeting evaluation criteria or passing hard gates.",
                    message="No legitimate maintenance tasks found. Exiting cleanly without fabricating activity.",
                    is_backup_run=is_backup_run,
                ))

            # Step C: Autonomous Execution Engine (orchestrates queue, workers, retries, and validations)
            engine = ExecutionEngine(
                repo_config=repo_config,
                config=config,
                github_client=github_client,
                state_mgr=state_mgr,
                ai_adapter=effective_ai_adapter,
                workspace_path=workspace_path,
                baseline_result=baseline_result,
                max_workers=config.execution.max_workers,
                max_retries=config.execution.max_retries,
                retry_backoff_factor=config.execution.retry_backoff_factor,
                task_timeout_seconds=config.execution.task_timeout_seconds,
                dry_run=dry_run,
                worker_only=worker_only,
                today_str=today_str,
            )
            executed_tasks, queue_summary = engine.run(queue)

            completed_tasks = [t for t in executed_tasks if t.status == TaskStatus.COMPLETED]
            failed_tasks = [t for t in executed_tasks if t.status == TaskStatus.FAILED]
            skipped_tasks = [t for t in executed_tasks if t.status == TaskStatus.SKIPPED]

            # DG3-07: Prioritize first successfully completed task as primary_task.
            # If no tasks succeeded, select the first failed task for diagnostic reporting.
            if completed_tasks:
                primary_task = completed_tasks[0]
            elif failed_tasks:
                primary_task = failed_tasks[0]
            elif skipped_tasks:
                primary_task = skipped_tasks[0]
            else:
                primary_task = executed_tasks[0] if executed_tasks else None
            files_analyzed: list[str] = []
            files_modified: list[str] = []
            for t in executed_tasks:
                files_analyzed.extend(t.target_files)
                if t.plan and t.plan.evidence_and_affected_files:
                    files_analyzed.extend(t.plan.evidence_and_affected_files)
                if t.quality_gate and t.quality_gate.changed_files:
                    files_modified.extend(t.quality_gate.changed_files)
            files_analyzed = sorted(list(set(files_analyzed)))
            files_modified = sorted(list(set(files_modified)))

            # If worker-only mode is requested (e.g. CI worker job with zero write tokens), write sealed artifact and finish
            if worker_only:
                sealed_dir = Path(config.state_dir)
                sealed_dir.mkdir(parents=True, exist_ok=True)
                sealed_file = sealed_dir / "sealed_task.json"
                import json
                sealed_payload = {
                    "repo": repo_config.name,
                    "task": primary_task.model_dump() if primary_task else None,
                    "tasks": [t.model_dump() for t in executed_tasks],
                    "queue_summary": queue_summary.model_dump(),
                    "evaluation": primary_task.evaluation.model_dump() if (primary_task and primary_task.evaluation) else None,
                    "plan": primary_task.plan.model_dump() if (primary_task and primary_task.plan) else None,
                    "discovery_summary": discovery_summary.model_dump() if discovery_summary else None,
                    "files_analyzed": files_analyzed,
                    "files_modified": files_modified,
                    "validation_details": primary_task.quality_gate.validation_details if (primary_task and primary_task.quality_gate) else [],
                    "quality_gate": primary_task.quality_gate.model_dump() if (primary_task and primary_task.quality_gate) else None,
                    "diff_text": (primary_task.quality_gate.verified_diff or primary_task.patch) if (primary_task and primary_task.quality_gate) else "",
                    "dry_run": dry_run,
                    "today_str": today_str,
                    "duration_seconds": round(time.time() - start_time, 2),
                }
                with open(sealed_file, "w", encoding="utf-8") as f:
                    json.dump(sealed_payload, f, indent=2)

                status = RunStatus.TASK_COMPLETED if completed_tasks else RunStatus.FAILED
                rejection_reason = failed_tasks[0].last_failure_reason if failed_tasks and not completed_tasks else None
                msg = f"Worker evaluation finished: {len(completed_tasks)} completed, {len(failed_tasks)} failed, {len(skipped_tasks)} skipped. Sealed artifact written to {sealed_file}."
                return _return_report(RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=status,
                    task=primary_task,
                    tasks=executed_tasks,
                    queue_summary=queue_summary,
                    evaluation=primary_task.evaluation if primary_task else None,
                    plan=primary_task.plan if primary_task else None,
                    discovery_summary=discovery_summary,
                    files_analyzed=files_analyzed,
                    files_modified=files_modified,
                    quality_gate=primary_task.quality_gate if primary_task else None,
                    rejection_reason=rejection_reason,
                    message=msg,
                    is_backup_run=is_backup_run,
                ))

            # Non-worker-only mode
            if completed_tasks:
                overall_status = RunStatus.DRY_RUN_COMPLETED if dry_run else RunStatus.PULL_REQUEST_CREATED
                msg_parts = [f"{len(completed_tasks)} completed"]
                if failed_tasks:
                    msg_parts.append(f"{len(failed_tasks)} failed")
                if skipped_tasks:
                    msg_parts.append(f"{len(skipped_tasks)} skipped")
                msg = f"Queue execution finished: {', '.join(msg_parts)}."
                delivery = primary_task.delivery if primary_task else None
                if delivery and delivery.message:
                    msg += f" {delivery.message}"

                report = RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=overall_status,
                    task=primary_task,
                    tasks=executed_tasks,
                    queue_summary=queue_summary,
                    evaluation=primary_task.evaluation if primary_task else None,
                    plan=primary_task.plan if primary_task else None,
                    discovery_summary=discovery_summary,
                    files_analyzed=files_analyzed,
                    files_modified=files_modified,
                    quality_gate=primary_task.quality_gate if primary_task else None,
                    delivery=delivery,
                    message=msg,
                    is_backup_run=is_backup_run,
                )
                return _return_report(report)
            else:
                rejection_reason = failed_tasks[0].last_failure_reason if failed_tasks else "All tasks skipped or prerequisites unfulfilled."
                report = RunReport(
                    run_id=run_id,
                    repo=repo_config.name,
                    status=RunStatus.FAILED,
                    task=primary_task,
                    tasks=executed_tasks,
                    queue_summary=queue_summary,
                    evaluation=primary_task.evaluation if primary_task else None,
                    plan=primary_task.plan if primary_task else None,
                    discovery_summary=discovery_summary,
                    files_analyzed=files_analyzed,
                    files_modified=files_modified,
                    rejection_reason=rejection_reason,
                    message=f"Queue execution failed: 0 completed, {len(failed_tasks)} failed, {len(skipped_tasks)} skipped.",
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
