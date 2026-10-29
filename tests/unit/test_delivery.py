"""Unit tests for GitHub delivery, patch hash verification, idempotency, and dry-run guarantees."""

import pytest
from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import DeliveryError, deliver_pull_request
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import QualityGateResult, Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash


def _setup_test_task() -> Task:
    return Task(
        id="test-task",
        repo="org/repo",
        title="Test Task",
        description="Desc",
        rationale="Rat",
        validation_strategy="strategy",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )


def test_delivery_gate_failed_raises(tmp_path: Path):
    repo = RepoConfig(name="org/repo")
    policy = SecurityPolicyConfig()
    github_client = MockGitHubClient()
    failed_gate = QualityGateResult(passed=False, reason="Tests failed")

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=tmp_path,
            task=_setup_test_task(),
            quality_gate=failed_gate,
            diff_text="diff",
            repo_config=repo,
            policy=policy,
            github_client=github_client,
            dry_run=True,
        )
    assert "Quality gate failed" in str(exc.value)


def test_delivery_patch_hash_tampered_raises(tmp_path: Path):
    repo = RepoConfig(name="org/repo")
    policy = SecurityPolicyConfig()
    github_client = MockGitHubClient()
    gate = QualityGateResult(passed=True, reason="ok", patch_hash="original_hash_12345")

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=tmp_path,
            task=_setup_test_task(),
            quality_gate=gate,
            diff_text="tampered diff content",
            repo_config=repo,
            policy=policy,
            github_client=github_client,
            dry_run=True,
        )
    assert "Patch hash does not match" in str(exc.value)


def test_delivery_dry_run_success(tmp_path: Path):
    repo = RepoConfig(name="org/repo")
    policy = SecurityPolicyConfig()
    github_client = MockGitHubClient()
    diff = "@@ -1,1 +1,2 @@\n+clean line\n"
    gate = QualityGateResult(passed=True, reason="ok", patch_hash=compute_patch_hash(diff))

    res = deliver_pull_request(
        workspace_dir=tmp_path,
        task=_setup_test_task(),
        quality_gate=gate,
        diff_text=diff,
        repo_config=repo,
        policy=policy,
        github_client=github_client,
        dry_run=True,
    )
    assert res.success is True
    assert res.is_dry_run is True
    assert "Dry-run mode" in res.message
    # No branches or PRs should have been created on the client
    assert len(github_client.created_branches) == 0
    assert len(github_client.created_prs) == 0


def test_delivery_skips_existing_branch(tmp_path: Path):
    repo = RepoConfig(name="org/repo")
    policy = SecurityPolicyConfig()
    diff = "@@ -1,1 +1,2 @@\n+clean line\n"
    gate = QualityGateResult(passed=True, reason="ok", patch_hash=compute_patch_hash(diff))

    # Existing branch and open PR on remote for today
    github_client = MockGitHubClient(
        existing_branches={"org/repo": ["dailygreen/2026-10-29-test-task"]},
        open_prs={
            "org/repo": [
                {
                    "number": 1,
                    "title": "[DailyGreen] Test Task",
                    "body": "DailyGreen Task: (test-task)",
                    "head": {"ref": "dailygreen/2026-10-29-test-task"},
                    "html_url": "https://github.com/org/repo/pull/1",
                }
            ]
        },
    )

    res = deliver_pull_request(
        workspace_dir=tmp_path,
        task=_setup_test_task(),
        quality_gate=gate,
        diff_text=diff,
        repo_config=repo,
        policy=policy,
        github_client=github_client,
        dry_run=False,
        date_str="2026-10-29",
    )
    assert res.success is False
    assert "already" in res.message.lower()
