"""Unit tests for Phase 3 Worker Orchestration: concurrency bounding, file locking, and worker isolation."""

import time
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, ExecutionConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.execution_engine import ExecutionEngine
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RiskLevel, Task, TaskCategory, TaskPlan, TaskSource, TaskStatus
from dailygreen.state import StateManager
from dailygreen.task_queue import TaskQueue


def _create_git_repo(path: Path):
    import subprocess
    from dailygreen.repository_manager import write_managed_workspace_marker
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "bot@dailygreen.local"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DailyGreen Bot"], cwd=str(path), capture_output=True, check=True)
    (path / "file1.md").write_text("# File 1\nContent with typo teh here.\n", encoding="utf-8")
    (path / "file2.md").write_text("# File 2\nContent with typo recieve here.\n", encoding="utf-8")
    (path / "file3.md").write_text("# File 3\nStandard content.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)
    write_managed_workspace_marker(path, "test-org/test-repo")


def _make_task(task_id: str, target_file: str, typo: str, fix: str) -> Task:
    return Task(
        id=task_id,
        repo="test-org/test-repo",
        title=f"Fix {typo} in {target_file}",
        description=f"Replace {typo} with {fix}",
        rationale="Fix spelling error",
        acceptance_criteria=[f"Typo '{typo}' is corrected to '{fix}' in '{target_file}'"],
        risk_level=RiskLevel.LOW,
        validation_strategy="typo_verification",
        source=TaskSource.DETERMINISTIC,
        category=TaskCategory.DOCUMENTATION,
        target_files=[target_file],
        metadata={"typo": typo, "replacement": fix},
        plan=TaskPlan(
            task_id=task_id,
            problem_statement=f"Typo in {target_file}",
            evidence_and_affected_files=[target_file],
            proposed_solution=f"Replace with {fix}",
            implementation_steps=["Update file"],
            expected_behavior="Clean text",
            tests_required=[],
            risk_assessment="Low",
            acceptance_criteria=[f"Typo '{typo}' is corrected to '{fix}' in '{target_file}'"],
        ),
    )


def test_sequential_worker_execution(tmp_path: Path):
    """Verify max_workers=1 executes tasks strictly sequentially and completes successfully."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_git_repo(workspace)

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["*.md"])
    state_mgr = StateManager(state_dir=tmp_path / "state")
    github_client = MockGitHubClient()
    ai_adapter = MockAIAdapter()

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        execution=ExecutionConfig(max_workers=1),
    )

    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        workspace_path=workspace,
        max_workers=1,
        dry_run=True,
    )

    queue = TaskQueue(repo=repo_cfg.name, max_tasks=5)
    t1 = _make_task("task-1", "file1.md", "teh", "the")
    t2 = _make_task("task-2", "file2.md", "recieve", "receive")
    queue.enqueue(t1)
    queue.enqueue(t2)

    executed, summary = engine.run(queue)
    assert len(executed) == 2
    assert summary.completed_count == 2
    assert summary.failed_count == 0

    assert queue.get_task("task-1").status == TaskStatus.COMPLETED
    assert queue.get_task("task-2").status == TaskStatus.COMPLETED


def test_worker_failure_isolation(tmp_path: Path):
    """Verify that failure of one task does not prevent or corrupt another independent task."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_git_repo(workspace)

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["*.md"])
    state_mgr = StateManager(state_dir=tmp_path / "state")
    github_client = MockGitHubClient()
    ai_adapter = MockAIAdapter()

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        execution=ExecutionConfig(max_workers=1),
    )

    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        workspace_path=workspace,
        max_workers=1,
        dry_run=True,
    )

    queue = TaskQueue(repo=repo_cfg.name, max_tasks=5)
    # Task 1: Valid typo fix
    t1 = _make_task("task-1", "file1.md", "teh", "the")
    # Task 2: Invalid task targeting non-existent typo (will fail quality gate or validation)
    t2 = _make_task("task-2", "file2.md", "nonexistenttypo", "fixed")
    queue.enqueue(t1)
    queue.enqueue(t2)

    executed, summary = engine.run(queue)
    assert summary.completed_count == 1
    assert summary.failed_count == 1

    t1_done = queue.get_task("task-1")
    t2_failed = queue.get_task("task-2")

    assert t1_done.status == TaskStatus.COMPLETED
    assert t2_failed.status == TaskStatus.FAILED
    assert t2_failed.last_failure_reason is not None


def test_max_workers_engine_rejection(tmp_path: Path):
    """Verify ExecutionEngine rejects max_workers > 1 at construction boundary (DG3-01)."""
    import pytest
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_git_repo(workspace)

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["*.md"])
    state_mgr = StateManager(state_dir=tmp_path / "state")
    github_client = MockGitHubClient()
    ai_adapter = MockAIAdapter()
    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        execution=ExecutionConfig(max_workers=1),
    )

    with pytest.raises(ValueError, match="Parallel worker execution is not supported"):
        ExecutionEngine(
            repo_config=repo_cfg,
            config=config,
            github_client=github_client,
            state_mgr=state_mgr,
            ai_adapter=ai_adapter,
            workspace_path=workspace,
            max_workers=2,
        )


def test_task_timeout_deadline_cooperative_enforcement(tmp_path: Path):
    """Verify cooperative deadline timeout marks task failed without unsafe retries (DG3-02)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_git_repo(workspace)

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["*.md"])
    state_mgr = StateManager(state_dir=tmp_path / "state")
    github_client = MockGitHubClient()

    # AI adapter that takes 0.5s
    class SlowMockAIAdapter(MockAIAdapter):
        def generate_patch(self, *args, **kwargs):
            time.sleep(0.3)
            return super().generate_patch(*args, **kwargs)

    ai_adapter = SlowMockAIAdapter()
    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        execution=ExecutionConfig(max_workers=1, task_timeout_seconds=10),
    )

    # Configure engine with a tiny timeout of 0.1s so deadline expires during/after implementation
    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        workspace_path=workspace,
        max_workers=1,
        max_retries=2,
        task_timeout_seconds=0,  # Immediate deadline expiration
        dry_run=True,
    )

    queue = TaskQueue(repo=repo_cfg.name, max_tasks=5)
    t1 = _make_task("timeout-task-1", "file1.md", "teh", "the")
    queue.enqueue(t1)

    executed, summary = engine.run(queue)
    assert summary.failed_count == 1
    assert summary.completed_count == 0

    failed_task = queue.get_task("timeout-task-1")
    assert failed_task.status == TaskStatus.FAILED
    assert "timeout" in failed_task.last_failure_reason.lower()
    # Ensured non-transient to prevent unsafe retry loops (DG3-02)
    assert failed_task.last_failure_transient is False
    assert failed_task.attempt_count == 1  # Not retried


def test_sequential_git_baseline_tracking(tmp_path: Path):
    """Verify sequential tasks maintain consistent Git baseline and disjoint diffs (DG3-08)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _create_git_repo(workspace)

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["*.md"])
    state_mgr = StateManager(state_dir=tmp_path / "state")
    github_client = MockGitHubClient()
    ai_adapter = MockAIAdapter()

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        execution=ExecutionConfig(max_workers=1),
    )

    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        workspace_path=workspace,
        max_workers=1,
        dry_run=True,
    )

    queue = TaskQueue(repo=repo_cfg.name, max_tasks=5)
    t1 = _make_task("task-1", "file1.md", "teh", "the")
    t2 = _make_task("task-2", "file2.md", "recieve", "receive")
    queue.enqueue(t1)
    queue.enqueue(t2)

    executed, summary = engine.run(queue)
    assert summary.completed_count == 2
    assert summary.failed_count == 0

    rec_t1 = queue.get_task("task-1")
    rec_t2 = queue.get_task("task-2")

    # Verify task 1 only modified file1.md
    assert rec_t1.quality_gate.changed_files == ["file1.md"]
    # Verify task 2 only modified file2.md (not file1.md from task 1!)
    assert rec_t2.quality_gate.changed_files == ["file2.md"]

    # Verify task base SHAs reflect pristine repository baseline for independent tasks
    assert rec_t1.metadata.get("task_base_sha") is not None
    assert rec_t2.metadata.get("task_base_sha") is not None
    assert rec_t1.metadata["task_base_sha"] == rec_t2.metadata["task_base_sha"]
