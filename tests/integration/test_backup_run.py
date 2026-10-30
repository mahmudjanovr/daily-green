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


def test_backup_run_skips_when_open_pr_exists_on_fresh_runner(tmp_path: Path):
    """Ground truth check on remote GitHub API: fresh runner with open PR from primary run."""
    from datetime import datetime
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")  # Clean state, zero completed tasks

    client = MockGitHubClient(
        pull_requests={
            "org/repo": [
                {
                    "number": 42,
                    "state": "open",
                    "head": {"ref": f"dailygreen/{today_str}-task-alpha"},
                    "html_url": "https://github.com/org/repo/pull/42",
                }
            ]
        }
    )

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.SKIPPED
    assert "Primary run has already completed" in report.message
    assert report.is_backup_run is True


def test_backup_run_skips_when_merged_pr_exists_on_fresh_runner(tmp_path: Path):
    """Ground truth check: PR created by primary was already merged before backup run."""
    from datetime import datetime
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    client = MockGitHubClient(
        pull_requests={
            "org/repo": [
                {
                    "number": 43,
                    "state": "closed",
                    "merged_at": f"{today_str}T17:20:00Z",
                    "head": {"ref": f"dailygreen/{today_str}-task-merged"},
                    "html_url": "https://github.com/org/repo/pull/43",
                }
            ]
        }
    )

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.SKIPPED
    assert "Primary run has already completed" in report.message
    assert report.is_backup_run is True


def test_backup_run_skips_when_closed_pr_exists_on_fresh_runner(tmp_path: Path):
    """Ground truth check: PR created by primary was closed/declined before backup run."""
    from datetime import datetime
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    client = MockGitHubClient(
        pull_requests={
            "org/repo": [
                {
                    "number": 44,
                    "state": "closed",
                    "merged_at": None,
                    "head": {"ref": f"dailygreen/{today_str}-task-declined"},
                    "html_url": "https://github.com/org/repo/pull/44",
                }
            ]
        }
    )

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.SKIPPED
    assert "Primary run has already completed" in report.message
    assert report.is_backup_run is True


def test_backup_run_fails_safely_on_api_error_during_dedup(tmp_path: Path):
    """GitHub API 500 error during backup deduplication must fail safe and not create duplicate tasks."""
    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    client = MockGitHubClient(should_fail=True)

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.FAILED
    assert "Backup run deduplication check failed" in report.message
    assert report.is_backup_run is True
    assert state_mgr._state["consecutive_failures"]["org/repo"] == 1


def test_backup_run_fails_safely_on_rate_limit_during_dedup(tmp_path: Path):
    """GitHub rate limit (403) during backup deduplication must fail safe without duplicate task execution."""
    repo_cfg = RepoConfig(name="org/repo", enabled=True)
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    client = MockGitHubClient(rate_limit_error=True)

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )

    assert report.status == RunStatus.FAILED
    assert "Backup run deduplication check failed" in report.message
    assert report.is_backup_run is True
    assert state_mgr._state["consecutive_failures"]["org/repo"] == 1
