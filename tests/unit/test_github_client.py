"""Unit tests for GitHubClient API communication, rate limits, retries, and MockGitHubClient."""

import pytest
from dailygreen.github_client import GitHubAPIError, GitHubClient, MockGitHubClient


def test_mock_github_client_branch_and_pr():
    client = MockGitHubClient(
        existing_branches={"org/repo": ["main", "feature"]},
        open_prs={"org/repo": []},
    )

    assert client.branch_exists("org/repo", "main") is True
    assert client.branch_exists("org/repo", "dailygreen/new-branch") is False

    # Create branch
    res_b = client.create_branch("org/repo", "dailygreen/new-branch", "mock_sha")
    assert client.branch_exists("org/repo", "dailygreen/new-branch") is True

    # Create PR
    pr = client.create_pull_request(
        repo="org/repo",
        title="[DailyGreen] Maintenance",
        body="PR body",
        head="dailygreen/new-branch",
        base="main",
    )
    assert pr["number"] == 1
    assert "html_url" in pr
    assert len(client.get_open_pull_requests("org/repo")) == 1


def test_mock_github_client_rate_limit():
    client = MockGitHubClient(rate_limit_error=True)
    with pytest.raises(GitHubAPIError) as exc:
        client.get_repository("org/repo")
    assert exc.value.status_code == 403


def test_mock_github_client_server_error():
    client = MockGitHubClient(should_fail=True)
    with pytest.raises(GitHubAPIError) as exc:
        client.get_labeled_issues("org/repo")
    assert exc.value.status_code == 500
