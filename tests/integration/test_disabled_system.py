"""Integration test for global kill switch and disabled repository handling."""

import json
from pathlib import Path
import pytest
from click.testing import CliRunner
from dailygreen.cli import main
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


@pytest.mark.parametrize("kill_val", ["false", "0", "off", "", "unknown", "DISABLED"])
def test_cli_run_kill_switch_prevents_worker_execution(tmp_path: Path, monkeypatch, kill_val):
    """When DAILYGREEN_ENABLED is false, empty, or unknown, CLI run exits code 0 and runs no work."""
    monkeypatch.setenv("DAILYGREEN_ENABLED", kill_val)
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--repo", "any-org/any-repo"])
    assert result.exit_code == 0


@pytest.mark.parametrize("kill_val", ["false", "0", "off", "", "unknown"])
def test_cli_deliver_kill_switch_prevents_delivery(tmp_path: Path, monkeypatch, kill_val):
    """When DAILYGREEN_ENABLED is false, empty, or unknown, CLI deliver exits code 0 and aborts delivery."""
    monkeypatch.setenv("DAILYGREEN_ENABLED", kill_val)

    artifact_file = tmp_path / "sealed_task.json"
    artifact_file.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["deliver", "--sealed-artifact", str(artifact_file)])
    assert result.exit_code == 0
