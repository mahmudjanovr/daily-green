"""Unit tests for unexpected change cleanup, selective restoration, and workspace preservation."""

import subprocess
from pathlib import Path
import pytest
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.execution_engine import ExecutionEngine, WorkspaceContaminationError
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RiskLevel, Task, TaskSource, TaskStatus
from dailygreen.repository_manager import write_managed_workspace_marker
from dailygreen.security import safe_git_command
from dailygreen.state import StateManager
from dailygreen.task_queue import TaskQueue


def _setup_git_repo(repo_dir: Path, state_dir: Path, repo_name: str = "test-org/test-repo") -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(safe_git_command(["git", "init", "-b", "main"]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.name", "Tester"]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.email", "test@test.com"]), cwd=str(repo_dir), capture_output=True, check=True)

    (repo_dir / "README.md").write_text("# Tolkien Olami\n\nOriginal content.\n", encoding="utf-8")
    (repo_dir / "package.json").write_text('{"name": "tolkien", "version": "1.0.0"}', encoding="utf-8")
    subprocess.run(safe_git_command(["git", "add", "."]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "commit", "-m", "Initial commit"]), cwd=str(repo_dir), capture_output=True, check=True)

    write_managed_workspace_marker(repo_dir, repo_name, state_dir=state_dir)
    return repo_dir


def test_cleanup_reverts_both_authorized_and_unexpected_tracked_files(tmp_path: Path):
    """
    When a task modifies an authorized target file AND unexpectedly modifies an unrelated tracked file,
    and the quality gate rejects the task, both files are cleanly reverted to HEAD
    without using blanket 'git checkout HEAD -- .' or 'git clean -fd'.
    """
    state_dir = tmp_path / "state"
    workspace = _setup_git_repo(tmp_path / "ws", state_dir)

    # Pre-existing untracked user file (must be preserved!)
    pre_existing_untracked = workspace / "user_notes.txt"
    pre_existing_untracked.write_text("Important personal notes", encoding="utf-8")

    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md"],
        denied_paths=["package.json"],
    )
    config = DailyGreenConfig(repos=[repo_cfg], dry_run=True, allow_live_mutations=False)
    state_mgr = StateManager(state_dir=state_dir)

    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=state_mgr,
        ai_adapter=MockAIAdapter(),
        workspace_path=workspace,
    )

    task = Task(
        id="task-unexpected-edit",
        repo="test-org/test-repo",
        title="Doc typo fix",
        description="Fix typos",
        rationale="Fix docs",
        validation_strategy="markdown_link_check",
        source=TaskSource.BACKLOG,
        risk_level=RiskLevel.LOW,
        target_files=["README.md"],
    )
    queue = TaskQueue(repo=repo_cfg.name, state_dir=state_dir)
    queue.enqueue(task)

    # Capture pre-state
    pre_snapshot = engine._capture_workspace_snapshot()
    assert "user_notes.txt" in pre_snapshot.untracked_hashes

    # Simulate rogue task execution: modifies target file, modifies unexpected tracked file, creates new untracked file
    (workspace / "README.md").write_text("# Changed Content\n", encoding="utf-8")
    (workspace / "package.json").write_text('{"name": "tampered"}', encoding="utf-8")
    (workspace / "rogue_temp.tmp").write_text("rogue", encoding="utf-8")

    # Run cleanup
    engine._safe_task_cleanup(task, pre_snapshot)

    # Verify:
    # 1. README.md reverted to HEAD
    assert "Original content" in (workspace / "README.md").read_text(encoding="utf-8")
    # 2. package.json reverted to HEAD (unexpected change cleanly undone!)
    assert '"version": "1.0.0"' in (workspace / "package.json").read_text(encoding="utf-8")
    # 3. Rogue new untracked file was deleted
    assert not (workspace / "rogue_temp.tmp").exists()
    # 4. Pre-existing untracked user file was strictly PRESERVED
    assert pre_existing_untracked.exists()
    assert pre_existing_untracked.read_text(encoding="utf-8") == "Important personal notes"


def test_tampering_with_pre_existing_untracked_file_halts_and_preserves_workspace(tmp_path: Path):
    """
    If a task alters or deletes a pre-existing untracked user file, safe cleanup cannot be established.
    The engine must raise WorkspaceContaminationError and refuse further cleanup to preserve the workspace for inspection.
    """
    state_dir = tmp_path / "state"
    workspace = _setup_git_repo(tmp_path / "ws_tampered", state_dir)

    # Pre-existing untracked user file
    user_file = workspace / "pre_existing.env"
    user_file.write_text("SECRET_USER_DATA=12345", encoding="utf-8")

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])
    config = DailyGreenConfig(repos=[repo_cfg], dry_run=True, allow_live_mutations=False)
    state_mgr = StateManager(state_dir=state_dir)

    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=state_mgr,
        ai_adapter=MockAIAdapter(),
        workspace_path=workspace,
    )

    task = Task(
        id="task-tamper-untracked",
        repo="test-org/test-repo",
        title="Tamper",
        description="Tamper",
        rationale="Tamper test",
        validation_strategy="markdown_link_check",
        source=TaskSource.BACKLOG,
        risk_level=RiskLevel.LOW,
        target_files=["README.md"],
    )

    pre_snapshot = engine._capture_workspace_snapshot()
    assert "pre_existing.env" in pre_snapshot.untracked_hashes

    # Rogue action: overwrites user untracked file
    user_file.write_text("CORRUPTED", encoding="utf-8")

    # Cleanup must detect this contamination and raise WorkspaceContaminationError
    with pytest.raises(WorkspaceContaminationError, match="Pre-existing untracked file 'pre_existing.env' was modified"):
        engine._safe_task_cleanup(task, pre_snapshot)

    # Workspace is preserved for inspection, user file not deleted
    assert user_file.exists()
