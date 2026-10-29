"""Integration tests verifying strict dry-run guarantees: no remote mutations."""

import subprocess
import sys
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def test_dry_run_produces_no_remote_mutations(tmp_path: Path):
    source_repo = tmp_path / "repo"
    source_repo.mkdir()

    # Init local git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=str(source_repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(source_repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(source_repo), capture_output=True, check=True)
    (source_repo / "README.md").write_text("Hello world   \n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(source_repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(source_repo), capture_output=True, check=True)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")
    github_client = MockGitHubClient()

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=MockAIAdapter(),
        source_dir=source_repo,
        override_dry_run=True,
    )

    assert report.status == RunStatus.DRY_RUN_COMPLETED
    assert report.delivery.is_dry_run is True

    # Zero remote calls should have been made to create branches or PRs
    assert len(github_client.created_branches) == 0
    assert len(github_client.created_prs) == 0
