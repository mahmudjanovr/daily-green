"""Integration test for global kill switch and disabled repository handling."""

from pathlib import Path
from dailygreen.config import DailyGreenConfig, RepoConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def test_disabled_system_kill_switch(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=False, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")
    github_client = MockGitHubClient()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
    )

    assert report.status == RunStatus.SKIPPED
    assert "disabled" in report.message.lower()


def test_disabled_repo_skipped(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", enabled=False)
    config = DailyGreenConfig(enabled=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")
    github_client = MockGitHubClient()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
    )

    assert report.status == RunStatus.SKIPPED
    assert "disabled in configuration" in report.message
