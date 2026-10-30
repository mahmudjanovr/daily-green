"""Integration tests for Phase 3 Autonomous Execution Engine: multi-task queue, sealed artifacts, dependencies, and recovery."""

import json
import subprocess
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, ExecutionConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus, TaskStatus
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def _create_test_repo(path: Path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "bot@dailygreen.local"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DailyGreen Bot"], cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("# Test Repo\nDocumentation content with typo teh in intro.\n", encoding="utf-8")
    (path / "GUIDE.md").write_text("# User Guide\nFollow teh instructions carefully.\n", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname='test-pkg'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(path), capture_output=True, check=True)


def test_phase3_multi_task_execution_e2e(tmp_path: Path):
    """Verify autonomous pipeline discovers, plans, and executes multiple tasks per run."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["doc_typos"],
        max_tasks_per_run=2,
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
    )

    assert report.status == RunStatus.DRY_RUN_COMPLETED
    assert report.queue_summary is not None
    assert report.queue_summary.total_queued == 2
    assert report.queue_summary.completed_count == 2
    assert report.queue_summary.failed_count == 0
    assert len(report.tasks) == 2

    for task in report.tasks:
        assert task.status == TaskStatus.COMPLETED
        assert task.duration_seconds > 0
        assert task.attempt_count == 1
        assert task.worker_id is not None


def test_phase3_worker_only_sealed_artifact_extended(tmp_path: Path):
    """Verify worker-only mode extends sealed_task.json with queue_summary and multi-task execution records."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["doc_typos"],
        max_tasks_per_run=2,
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
        worker_only=True,
    )

    assert report.status == RunStatus.TASK_COMPLETED
    assert report.queue_summary is not None
    assert report.queue_summary.completed_count == 2

    sealed_file = state_dir / "sealed_task.json"
    assert sealed_file.exists()

    with open(sealed_file, "r", encoding="utf-8") as f:
        artifact = json.load(f)

    # Verify backward-compatible Phase 2 fields
    assert artifact["repo"] == "test-org/test-repo"
    assert artifact["task"] is not None
    assert artifact["evaluation"] is not None
    assert artifact["plan"] is not None
    assert "quality_gate" in artifact
    assert "diff_text" in artifact

    # Verify Phase 3 additions
    assert "tasks" in artifact
    assert len(artifact["tasks"]) == 2
    assert "queue_summary" in artifact
    assert artifact["queue_summary"]["completed_count"] == 2


def test_phase3_partial_failure_reporting(tmp_path: Path):
    """Verify partial failure (one task completed, one task failed) produces accurate queue accounting."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    # Curate one valid task and one invalid task in backlog
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["curated_backlog"],
        max_tasks_per_run=2,
        curated_tasks=[
            {
                "id": "valid-backlog-task",
                "title": "Fix typo in README",
                "description": "Fix reproducible typo",
                "target_files": ["README.md"],
                "acceptance_criteria": ["Typo 'teh' is corrected to 'the' in 'README.md'"],
                "metadata": {"typo": "teh", "replacement": "the"},
                "validation_strategy": "typo_verification",
            },
            {
                "id": "invalid-backlog-task",
                "title": "Invalid backlog patch task",
                "description": "Corrupted patch",
                "target_files": ["GUIDE.md"],
                "patch": "INVALID CORRUPTED GIT PATCH THAT WILL FAIL\n",
                "acceptance_criteria": ["Apply valid patch safely"],
                "validation_strategy": "verify",
            },
        ],
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
    )

    # When at least one task completes, pipeline finishes dry run with partial status recorded
    assert report.status == RunStatus.DRY_RUN_COMPLETED
    assert report.queue_summary is not None
    assert report.queue_summary.completed_count == 1
    assert report.queue_summary.failed_count == 1
    assert "1 completed, 1 failed" in report.message


def test_phase3_dependency_cascade_in_pipeline(tmp_path: Path):
    """Verify that when a prerequisite task fails, dependent tasks are safely cascade-skipped."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["curated_backlog"],
        max_tasks_per_run=2,
        curated_tasks=[
            {
                "id": "prereq-task",
                "title": "Failing prerequisite task",
                "description": "Fails git apply",
                "target_files": ["README.md"],
                "patch": "INVALID BROKEN PATCH\n",
                "acceptance_criteria": ["Apply patch"],
                "validation_strategy": "verify",
            },
            {
                "id": "dependent-task",
                "title": "Dependent task",
                "description": "Depends on prereq-task",
                "target_files": ["GUIDE.md"],
                "dependencies": ["prereq-task"],
                "acceptance_criteria": ["Run only after prereq"],
                "validation_strategy": "verify",
            },
        ],
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
    )

    assert report.status == RunStatus.FAILED
    assert report.queue_summary is not None
    assert report.queue_summary.completed_count == 0
    assert report.queue_summary.failed_count == 1
    assert report.queue_summary.skipped_count == 1

    dep_task = [t for t in report.tasks if t.id == "dependent-task"][0]
    assert dep_task.status == TaskStatus.SKIPPED
    assert "prerequisite" in (dep_task.last_failure_reason or "").lower()


def test_failed_first_successful_second_reporting_and_delivery(tmp_path: Path):
    """Verify failed-first/successful-second sets successful task as primary and delivers it (DG3-04, DG3-07)."""
    from click.testing import CliRunner
    from dailygreen.cli import main

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["curated_backlog"],
        max_tasks_per_run=2,
        curated_tasks=[
            {
                "id": "task-fail-first",
                "title": "Failing task",
                "description": "Fails git patch",
                "target_files": ["README.md"],
                "patch": "BAD PATCH\n",
                "acceptance_criteria": ["Apply bad patch"],
                "validation_strategy": "verify",
            },
            {
                "id": "task-succeed-second",
                "title": "Fix teh in GUIDE.md",
                "description": "Fix typo",
                "target_files": ["GUIDE.md"],
                "patch": "--- a/GUIDE.md\n+++ b/GUIDE.md\n@@ -1,2 +1,2 @@\n # User Guide\n-Follow teh instructions carefully.\n+Follow the instructions carefully.\n",
                "acceptance_criteria": ["Typo corrected"],
                "validation_strategy": "verify",
            },
        ],
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    # Run in worker-only mode to generate sealed artifact
    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
        worker_only=True,
    )

    # DG3-07: Verify primary_task is the SUCCESSFUL task, not the failed first task!
    assert report.task is not None
    assert report.task.id == "task-succeed-second"
    assert report.queue_summary.completed_count == 1
    assert report.queue_summary.failed_count == 1

    # Check sealed_task.json
    sealed_file = state_dir / "sealed_task.json"
    assert sealed_file.exists()
    sealed_data = json.loads(sealed_file.read_text(encoding="utf-8"))
    assert sealed_data["task"]["id"] == "task-succeed-second"
    assert len(sealed_data["tasks"]) == 2

    # DG3-04: Deliver sealed artifact via CLI
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("""
repositories:
  - name: "test-org/test-repo"
    allowed_paths: ["README.md", "GUIDE.md"]
""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "deliver",
            "--sealed-artifact", str(sealed_file),
            "--source-dir", str(workspace),
            "--repos-config", str(repos_file),
            "--dry-run",
            "--mock-github",
        ],
    )
    assert result.exit_code == 0
    # Delivery should deliver the successful task and cleanly skip the failed one
    assert "Task 'task-succeed-second'" in result.output
    assert "1 delivered, 1 skipped, 0 failed" in result.output


def test_multi_task_delivery_delivers_both_tasks_and_prevents_duplicates(tmp_path: Path):
    """Verify delivery delivers all completed tasks in multi-task artifact and skips duplicates (DG3-04)."""
    from click.testing import CliRunner
    from dailygreen.cli import main

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_test_repo(workspace)

    state_dir = tmp_path / ".dailygreen"
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "GUIDE.md"],
        supported_task_types=["doc_typos"],
        max_tasks_per_run=2,
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
        execution=ExecutionConfig(max_tasks_per_run=2, max_workers=1),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    # Generate multi-task sealed artifact in worker-only mode
    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
        worker_only=True,
    )
    assert report.queue_summary.completed_count == 2

    sealed_file = state_dir / "sealed_task.json"
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("""
repositories:
  - name: "test-org/test-repo"
    allowed_paths: ["README.md", "GUIDE.md"]
""", encoding="utf-8")

    runner = CliRunner()

    # 1. First delivery run (both tasks should be delivered)
    res1 = runner.invoke(
        main,
        [
            "deliver",
            "--sealed-artifact", str(sealed_file),
            "--source-dir", str(workspace),
            "--repos-config", str(repos_file),
            "--state-dir", str(state_dir),
            "--dry-run",
            "--mock-github",
        ],
    )
    assert res1.exit_code == 0
    assert "2 delivered, 0 skipped, 0 failed" in res1.output

    # 2. Mark task 1 as completed in state_mgr to simulate duplicate delivery avoidance
    task_1_id = report.tasks[0].id
    state_mgr.record_task_completion("test-org/test-repo", task_1_id, details={"branch": "main"})

    res2 = runner.invoke(
        main,
        [
            "deliver",
            "--sealed-artifact", str(sealed_file),
            "--source-dir", str(workspace),
            "--repos-config", str(repos_file),
            "--state-dir", str(state_dir),
            "--dry-run",
            "--mock-github",
        ],
    )
    assert res2.exit_code == 0
    # Task 1 should be skipped, task 2 delivered
    assert "1 delivered, 1 skipped, 0 failed" in res2.output

