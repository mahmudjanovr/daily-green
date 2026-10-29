"""Unit tests simulating the 8 edge cases for idempotency, scheduler recovery, and concurrency."""

import time
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import deliver_pull_request
from dailygreen.github_client import GitHubAPIError, MockGitHubClient
from dailygreen.models import QualityGateResult, RunStatus, Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def _dummy_task(task_id: str = "task-alpha") -> Task:
    return Task(
        id=task_id,
        repo="test-org/test-repo",
        title="Automated improvement",
        description="Fix documentation typo",
        rationale="Clean repo",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )


def test_scenario_1_primary_run_completed_backup_skips(tmp_path: Path):
    """Scenario 1: Primary run completes successfully; backup run starts and skips duplicate."""
    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path)

    # Primary run completed a task today
    state_mgr.record_task_completion("test-org/test-repo", "task-alpha")

    client = MockGitHubClient()
    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=client,
        state_mgr=state_mgr,
        is_backup_run=True,
    )
    assert report.status == RunStatus.SKIPPED
    assert "Primary run has already completed" in report.message


def test_scenario_2_primary_in_progress_backup_skips(tmp_path: Path):
    """Scenario 2: Primary run is still in progress (lease held) when backup starts."""
    state_mgr = StateManager(state_dir=tmp_path)
    # Primary acquires lease
    assert state_mgr.acquire_run_lease("test-org/test-repo", run_id="primary-run-1") is True

    # Backup attempts to run
    repo_cfg = RepoConfig(name="test-org/test-repo")
    config = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=state_mgr,
        is_backup_run=True,
    )
    assert report.status == RunStatus.SKIPPED
    assert "actively in progress" in report.message


def test_scenario_3_recovery_when_branch_exists_without_pr(tmp_path: Path):
    """Scenario 3: Primary crashed after creating branch but before opening PR. Recovery opens PR."""
    repo_cfg = RepoConfig(name="test-org/test-repo")
    policy = SecurityPolicyConfig()
    diff = "@@ -1,1 +1,2 @@\n+line\n"
    gate = QualityGateResult(passed=True, reason="ok", patch_hash=compute_patch_hash(diff))

    branch_name = "dailygreen/2026-10-29-task-alpha"
    # Branch exists remotely, but NO PR was opened yet
    client = MockGitHubClient(
        existing_branches={"test-org/test-repo": [branch_name]},
        open_prs={"test-org/test-repo": []},
    )

    res = deliver_pull_request(
        workspace_dir=tmp_path,
        task=_dummy_task(),
        quality_gate=gate,
        diff_text=diff,
        repo_config=repo_cfg,
        policy=policy,
        github_client=client,
        dry_run=False,
        date_str="2026-10-29",
        allow_live_mutations=True,
    )
    assert res.success is True
    assert "Recovered interrupted delivery" in res.message
    assert res.pr_number is not None
    assert len(client.open_prs["test-org/test-repo"]) == 1


def test_scenario_4_pr_timeout_recovery_when_pr_created_remotely(tmp_path: Path):
    """Scenario 4: PR creation succeeds remotely but API call times out. Recovery finds and returns PR."""
    client = MockGitHubClient(simulate_timeout_on_pr_create=True)

    # Calling create_pull_request recovers and returns the created PR despite the timeout
    pr = client.create_pull_request(
        repo="test-org/test-repo",
        title="[DailyGreen] Fix typo",
        body="PR body",
        head="dailygreen/2026-10-29-task-alpha",
        base="main",
    )
    assert pr["number"] == 1
    assert "html_url" in pr


def test_scenario_5_concurrent_runs_prevented_by_lease(tmp_path: Path):
    """Scenario 5: Two runs attempt to process the same task concurrently. Lease prevents collision."""
    state_mgr = StateManager(state_dir=tmp_path)

    # Run 1 acquires lease
    assert state_mgr.acquire_run_lease("test-org/test-repo", run_id="run-A") is True

    # Run 2 immediately attempts to acquire lease for the same repository
    assert state_mgr.acquire_run_lease("test-org/test-repo", run_id="run-B") is False

    # After Run 1 releases lease, Run 2 can acquire
    state_mgr.release_run_lease("test-org/test-repo", run_id="run-A")
    assert state_mgr.acquire_run_lease("test-org/test-repo", run_id="run-B") is True


def test_scenario_6_stale_or_incomplete_state_repaired(tmp_path: Path):
    """Scenario 6: A previous run left a stale lease or corrupted state. State manager auto-heals."""
    state_file = tmp_path / "state.json"
    # Write a stale lease with old timestamp (> 30 mins ago)
    stale_data = {
        "active_leases": {
            "test-org/test-repo": {
                "run_id": "crashed-run",
                "timestamp": time.time() - 3600,  # 1 hour ago
            }
        }
    }
    import json
    state_file.write_text(json.dumps(stale_data), encoding="utf-8")

    state_mgr = StateManager(state_dir=tmp_path)
    # Stale lease should have been cleared on load
    assert "test-org/test-repo" not in state_mgr._state["active_leases"]

    # New run can immediately acquire lease
    assert state_mgr.acquire_run_lease("test-org/test-repo", run_id="new-run") is True


def test_scenario_7_github_rate_limit_and_error_handling():
    """Scenario 7: GitHub API returns rate limit or 500 error."""
    client_rate = MockGitHubClient(rate_limit_error=True)
    try:
        client_rate.get_repository("test-org/test-repo")
        assert False, "Should have raised GitHubAPIError"
    except GitHubAPIError as e:
        assert e.status_code == 403
        assert "rate limit" in str(e).lower()

    client_500 = MockGitHubClient(should_fail=True)
    try:
        client_500.get_repository("test-org/test-repo")
        assert False, "Should have raised GitHubAPIError"
    except GitHubAPIError as e:
        assert e.status_code == 500


def test_scenario_8_open_pr_already_exists_for_task(tmp_path: Path):
    """Scenario 8: The same task is already represented by an open PR."""
    repo_cfg = RepoConfig(name="test-org/test-repo")
    policy = SecurityPolicyConfig()
    diff = "@@ -1,1 +1,2 @@\n+line\n"
    gate = QualityGateResult(passed=True, reason="ok", patch_hash=compute_patch_hash(diff))

    # An open PR exists referencing this task ID in the body
    client = MockGitHubClient(
        open_prs={
            "test-org/test-repo": [
                {
                    "number": 15,
                    "title": "Existing PR",
                    "body": "DailyGreen Task: (task-alpha)",
                    "head": {"ref": "other-branch"},
                    "html_url": "https://github.com/test-org/test-repo/pull/15",
                }
            ]
        }
    )

    res = deliver_pull_request(
        workspace_dir=tmp_path,
        task=_dummy_task(task_id="task-alpha"),
        quality_gate=gate,
        diff_text=diff,
        repo_config=repo_cfg,
        policy=policy,
        github_client=client,
        dry_run=True,
    )
    assert res.success is False
    assert "already represented by open PR #15" in res.message
    assert res.contribution_status == "SKIPPED"
