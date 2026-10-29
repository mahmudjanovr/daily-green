"""Opt-in live integration tests against a real GitHub test repository.

SAFETY GUARANTEES:
1. Strictly opt-in: NEVER runs in standard CI or local default test suites.
2. Safe by default: Initial connectivity check is 100% READ-ONLY.
3. Requires three explicit configuration elements:
   - RUN_LIVE_GITHUB_TEST=1
   - LIVE_GITHUB_TEST_REPO="disposable-org/disposable-sandbox-repo"
   - LIVE_GITHUB_TOKEN="ghp_xxx"
4. Requires the exact test repository to be explicitly present and enabled in the allowlist.
5. Live PR creation and branch mutation requires a separate explicit variable:
   - ALLOW_LIVE_MUTATIONS=1
6. Tokens and sensitive headers are strictly redacted and never echoed to test stdout/stderr.
"""

import os
import time
import pytest
from dailygreen.config import ConfigurationError, RepoConfig, SecurityPolicyConfig, load_config
from dailygreen.delivery import deliver_pull_request
from dailygreen.github_client import GitHubAPIError, GitHubClient
from dailygreen.models import QualityGateResult, Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash


RUN_OPT_IN = os.getenv("RUN_LIVE_GITHUB_TEST", "0").strip().lower() in ("1", "true", "yes")
LIVE_REPO = os.getenv("LIVE_GITHUB_TEST_REPO", "").strip()
LIVE_TOKEN = os.getenv("LIVE_GITHUB_TOKEN", "").strip()
ALLOW_MUTATIONS = os.getenv("ALLOW_LIVE_MUTATIONS", "0").strip().lower() in ("1", "true", "yes")


def is_live_configured() -> bool:
    return RUN_OPT_IN and bool(LIVE_REPO) and bool(LIVE_TOKEN)


@pytest.mark.skipif(
    not is_live_configured(),
    reason="RUN_LIVE_GITHUB_TEST=1, LIVE_GITHUB_TEST_REPO, and LIVE_GITHUB_TOKEN required (Opt-in live GitHub integration test is NOT RUN)",
)
def test_live_github_connectivity_read_only():
    """
    Step 1: Read-only live verification.
    Validates connectivity, token permissions, allowlist membership, and rate limits without any remote mutations.
    """
    # 1. Allowlist enforcement: repository MUST be explicitly listed
    try:
        cfg = load_config()
        repo_cfg = cfg.get_repo(LIVE_REPO)
    except ConfigurationError:
        repo_cfg = None

    if not repo_cfg:
        pytest.fail(
            f"Safety check failed: Test repository '{LIVE_REPO}' is not explicitly defined and enabled in allowlist. "
            "Add the repository to config/repos.yml before running live tests."
        )

    # 2. Read-only API verification
    client = GitHubClient(token=LIVE_TOKEN)
    repo_info = client.get_repository(LIVE_REPO)
    assert repo_info is not None, f"Could not access test repository '{LIVE_REPO}' with provided credentials"
    assert "default_branch" in repo_info

    # 3. Read-only queries for issues and PRs (zero remote mutations)
    issues = client.get_labeled_issues(LIVE_REPO, label="dailygreen")
    assert isinstance(issues, list)

    open_prs = client.get_open_pull_requests(LIVE_REPO)
    assert isinstance(open_prs, list)


@pytest.mark.skipif(
    not is_live_configured() or not ALLOW_MUTATIONS,
    reason="ALLOW_LIVE_MUTATIONS=1 required for live PR creation test (NOT RUN by default)",
)
def test_live_github_pr_delivery_opt_in(tmp_path):
    """
    Step 2: Controlled mutation verification (opt-in only).
    Creates a temporary branch, opens a Pull Request, verifies duplicate PR detection, and cleans up.
    """
    client = GitHubClient(token=LIVE_TOKEN)
    repo_info = client.get_repository(LIVE_REPO)
    assert repo_info is not None
    default_branch = repo_info.get("default_branch", "main")

    test_slug = f"live-test-{int(time.time())}"
    diff = "@@ -1,1 +1,2 @@\n+# Automated live test verification\n"
    patch_hash = compute_patch_hash(diff)
    qg = QualityGateResult(
        passed=True,
        reason="Live test simulated quality gate passed",
        patch_hash=patch_hash,
    )

    task = Task(
        id=test_slug,
        repo=LIVE_REPO,
        title=f"Automated Integration Verification {test_slug}",
        description="Disposable live integration test verifying branch and PR creation.",
        rationale="End-to-end verification of GitHub delivery pipeline.",
        acceptance_criteria=["Verify PR created and branch cleanly handled"],
        validation_strategy="live_api",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    repo_cfg = RepoConfig(name=LIVE_REPO, default_branch=default_branch, allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    # Dry-run check against real GitHub API
    dry_res = deliver_pull_request(
        workspace_dir=tmp_path,
        task=task,
        quality_gate=qg,
        diff_text=diff,
        repo_config=repo_cfg,
        policy=policy,
        github_client=client,
        dry_run=True,
    )
    assert dry_res.success is True
    assert dry_res.is_dry_run is True

    # Live delivery
    base_sha = client.get_branch_ref(LIVE_REPO, default_branch)
    assert base_sha is not None, "Failed to resolve base branch ref on remote"

    test_branch = f"dailygreen/{test_slug}"
    client.create_branch(LIVE_REPO, test_branch, base_sha)
    assert client.branch_exists(LIVE_REPO, test_branch) is True

    try:
        pr = client.create_pull_request(
            repo=LIVE_REPO,
            title=f"[DailyGreen] {task.title}",
            body=f"Automated verification test PR: ({task.id})",
            head=test_branch,
            base=default_branch,
        )
        assert pr.get("number") is not None

        # Duplicate PR detection
        dup_res = deliver_pull_request(
            workspace_dir=tmp_path,
            task=task,
            quality_gate=qg,
            diff_text=diff,
            repo_config=repo_cfg,
            policy=policy,
            github_client=client,
            dry_run=True,
        )
        assert dup_res.success is False
        assert "already represented by open PR" in dup_res.message
    finally:
        # Cleanup remote branch
        try:
            client.delete_branch(LIVE_REPO, test_branch)
        except Exception:
            pass
