"""Integration test for full DailyGreen end-to-end pipeline using a temporary local git repository."""

import subprocess
import sys
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def _setup_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), capture_output=True, check=True)

    # Create initial files
    docs_dir = path / "docs"
    docs_dir.mkdir()
    # Has trailing whitespace on line 1: deterministic task candidate
    (docs_dir / "index.md").write_text("# Project Documentation   \nOverview content.\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), capture_output=True, check=True)


def test_full_pipeline_deterministic_e2e(tmp_path: Path):
    source_repo = tmp_path / "test_repo"
    source_repo.mkdir()
    _setup_git_repo(source_repo)

    state_dir = tmp_path / ".dailygreen"
    state_mgr = StateManager(state_dir=state_dir)

    repo_cfg = RepoConfig(
        name="test-org/test-project",
        default_branch="main",
        enabled=True,
        allowed_paths=["docs/**", "README.md"],
        baseline_command=[sys.executable, "-c", "import sys; sys.exit(0)"],
        test_commands=[[sys.executable, "-c", "import sys; sys.exit(0)"]],
        lint_commands=[[sys.executable, "-c", "import sys; sys.exit(0)"]],
    )

    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
    )

    github_client = MockGitHubClient()
    ai_adapter = MockAIAdapter()

    # Run 1: Should discover deterministic whitespace task and succeed
    report1 = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=source_repo,
        is_backup_run=False,
        override_dry_run=True,
    )

    assert report1.status == RunStatus.DRY_RUN_COMPLETED
    assert report1.task is not None
    assert report1.quality_gate is not None
    assert report1.quality_gate.passed is True
    assert report1.delivery is not None
    assert report1.delivery.success is True

    # Run 2: Immediately re-running should report NO_TASK (task already done in state)
    report2 = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=source_repo,
        is_backup_run=False,
        override_dry_run=True,
    )

    assert report2.status == RunStatus.NO_TASK
