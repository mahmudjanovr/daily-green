"""Integration test for backup run behavior and deduplication."""

from pathlib import Path
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def test_backup_run_skips_when_primary_already_completed(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    # Simulate that primary run already completed a task today
    state_mgr.record_task_completion("org/repo", "primary-task-1")

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.SKIPPED
    assert "Primary run has already completed" in report.message
    assert report.is_backup_run is True
