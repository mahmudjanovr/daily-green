"""Tests for read-only GitHub connectivity checking, authentication verification, and zero mutation enforcement."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from dailygreen.cli import main
from dailygreen.github_client import GitHubAPIError, MockGitHubClient


class MutationAssertingMockGitHubClient(MockGitHubClient):
    """Mock client that immediately fails with AssertionError if any write method is called."""

    def create_branch(self, repo: str, branch: str, sha: str):
        pytest.fail(f"Violation: create_branch called during read-only operation ({repo}, {branch})")

    def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str = "main"):
        pytest.fail(f"Violation: create_pull_request called during read-only operation ({repo}, {title})")

    def create_blob(self, repo: str, content: str):
        pytest.fail("Violation: create_blob called during read-only operation")

    def create_tree(self, repo: str, base_tree: str, tree: list):
        pytest.fail("Violation: create_tree called during read-only operation")

    def create_commit(self, repo: str, message: str, tree: str, parents: list):
        pytest.fail("Violation: create_commit called during read-only operation")

    def update_branch_ref(self, repo: str, branch: str, sha: str, force: bool = False):
        pytest.fail("Violation: update_branch_ref called during read-only operation")

    def delete_branch(self, repo: str, branch: str):
        pytest.fail("Violation: delete_branch called during read-only operation")


def _write_repos_config(path: Path) -> None:
    path.write_text("""
repositories:
  - name: "test-org/public-repo"
    default_branch: "main"
    enabled: true
    allowed_paths: ["docs/**", "README.md"]
  - name: "test-org/private-repo"
    default_branch: "main"
    enabled: true
    allowed_paths: ["README.md"]
  - name: "test-org/disabled-repo"
    enabled: false
    allowed_paths: ["README.md"]
""", encoding="utf-8")


def test_check_github_success(tmp_path: Path):
    """Verify successful read-only check of authorized repositories with mock client."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    runner = CliRunner()
    result = runner.invoke(main, [
        "check-github",
        "--repos-config", str(repos_file),
        "--mock-github",
    ])

    assert result.exit_code == 0
    assert "=== GitHub Read-Only Connectivity Check ===" in result.output
    assert "API Rate Limit:" in result.output
    assert "Authenticated Identity: mock-operator" in result.output
    assert "Verifying Repository Access: test-org/public-repo" in result.output
    assert "Status: ACCESSIBLE" in result.output
    assert "Read-Only Check Completed: Zero remote mutations performed." in result.output


def test_check_github_unauthorized_repo_rejected(tmp_path: Path):
    """check-github strictly rejects repositories not present in the allowlist."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    runner = CliRunner()
    result = runner.invoke(main, [
        "check-github",
        "--repo", "unauthorized-org/rogue-repo",
        "--repos-config", str(repos_file),
        "--mock-github",
    ])

    assert result.exit_code == 1
    assert "is not authorized in allowlist" in result.output


def test_check_github_inaccessible_repository_reports_error(tmp_path: Path, monkeypatch):
    """When repository returns 404, check-github reports inaccessible and exits with error code."""
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("""
repositories:
  - name: "test-org/missing-repo"
    allowed_paths: ["README.md"]
""", encoding="utf-8")

    # Mock client where repository is missing
    client = MockGitHubClient(repositories={})
    monkeypatch.setattr("dailygreen.cli.GitHubClient", lambda **kw: client)

    runner = CliRunner()
    result = runner.invoke(main, [
        "check-github",
        "--repos-config", str(repos_file),
    ])

    assert result.exit_code == 1
    assert "INACCESSIBLE (HTTP 404" in result.output


def test_check_github_rate_limit_handling(tmp_path: Path, monkeypatch):
    """When GitHub API returns rate limit 403, check-github handles it gracefully."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    client = MockGitHubClient(rate_limit_error=True)
    monkeypatch.setattr("dailygreen.cli.GitHubClient", lambda **kw: client)

    runner = CliRunner()
    result = runner.invoke(main, [
        "check-github",
        "--repos-config", str(repos_file),
    ])

    assert result.exit_code == 1
    assert "rate limit exceeded" in result.output.lower()


def test_check_github_never_leaks_token(tmp_path: Path):
    """Verify that sensitive token passed via parameter or environment is never echoed."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    secret_token = "ghp_VerySecretRealToken1234567890abcdef"
    runner = CliRunner()
    result = runner.invoke(main, [
        "check-github",
        "--repos-config", str(repos_file),
        "--token", secret_token,
        "--mock-github",
    ])

    # The actual token string must NEVER appear in stdout or stderr
    assert secret_token not in result.output
    assert "Token Status: DETECTED" in result.output


def test_check_github_and_discover_enforce_zero_mutations(tmp_path: Path, monkeypatch):
    """Use MutationAssertingMockGitHubClient to prove zero write methods are ever called."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "README.md").write_text("# Hello World\nteh doc link [guide](nonexistent.md)\n", encoding="utf-8")

    strict_client = MutationAssertingMockGitHubClient(
        repositories={
            "test-org/public-repo": {"name": "test-org/public-repo", "default_branch": "main", "private": False, "permissions": {"pull": True, "push": True, "admin": True}},
            "test-org/private-repo": {"name": "test-org/private-repo", "default_branch": "main", "private": True, "permissions": {"pull": True, "push": False, "admin": False}},
        },
        labeled_issues={
            "test-org/public-repo": [
                {
                    "number": 42,
                    "title": "Fix doc links",
                    "body": "Please fix broken link in README.md",
                    "html_url": "https://github.com/test-org/public-repo/issues/42",
                }
            ]
        },
    )
    monkeypatch.setattr("dailygreen.cli.GitHubClient", lambda **kw: strict_client)
    monkeypatch.setattr("dailygreen.cli.MockGitHubClient", lambda **kw: strict_client)

    runner = CliRunner()

    # 1. check-github must invoke zero write methods
    r1 = runner.invoke(main, ["check-github", "--repos-config", str(repos_file)])
    assert r1.exit_code == 0
    assert "Read-Only Check Completed: Zero remote mutations performed." in r1.output
    assert len(strict_client.created_branches) == 0
    assert len(strict_client.created_prs) == 0
    assert len(strict_client.created_blobs) == 0
    assert len(strict_client.created_trees) == 0
    assert len(strict_client.created_commits) == 0
    assert len(strict_client.updated_refs) == 0
    assert len(strict_client.deleted_branches) == 0

    # 2. discover must invoke zero write methods even when issues and tasks are found
    r2 = runner.invoke(main, [
        "discover",
        "--repo", "test-org/public-repo",
        "--source-dir", str(source_dir),
        "--repos-config", str(repos_file),
    ])
    assert r2.exit_code == 0
    assert "Read-Only Discovery Result:" in r2.output
    assert "CANDIDATE_DISCOVERED" in r2.output
    assert "Zero remote or local modifications were made." in r2.output

    # Assert that zero mutations occurred on the strict client
    assert len(strict_client.created_branches) == 0
    assert len(strict_client.created_prs) == 0
    assert len(strict_client.created_blobs) == 0
    assert len(strict_client.created_trees) == 0
    assert len(strict_client.created_commits) == 0
    assert len(strict_client.updated_refs) == 0
    assert len(strict_client.deleted_branches) == 0


def test_mutation_asserting_client_detects_unintended_mutation():
    """Verify that MutationAssertingMockGitHubClient fails immediately if any write method is called."""
    client = MutationAssertingMockGitHubClient()

    with pytest.raises(pytest.fail.Exception, match="create_branch called during read-only operation"):
        client.create_branch("org/repo", "test-branch", "sha123")

    with pytest.raises(pytest.fail.Exception, match="create_pull_request called during read-only operation"):
        client.create_pull_request("org/repo", "PR Title", "Body", "head-branch")

    with pytest.raises(pytest.fail.Exception, match="create_blob called during read-only operation"):
        client.create_blob("org/repo", "content")

    with pytest.raises(pytest.fail.Exception, match="create_tree called during read-only operation"):
        client.create_tree("org/repo", "base", [])

    with pytest.raises(pytest.fail.Exception, match="create_commit called during read-only operation"):
        client.create_commit("org/repo", "msg", "tree", [])

    with pytest.raises(pytest.fail.Exception, match="update_branch_ref called during read-only operation"):
        client.update_branch_ref("org/repo", "main", "sha123")

    with pytest.raises(pytest.fail.Exception, match="delete_branch called during read-only operation"):
        client.delete_branch("org/repo", "branch")


def test_discover_unauthorized_repository_fails_closed_before_network(tmp_path: Path, monkeypatch):
    """Verify discover fails closed without any network calls if repo is not in config/repos.yml."""
    repos_file = tmp_path / "repos.yml"
    _write_repos_config(repos_file)

    def _unexpected_call(**kw):
        pytest.fail("Network client should never be constructed for unauthorized repo")

    monkeypatch.setattr("dailygreen.cli.GitHubClient", _unexpected_call)
    monkeypatch.setattr("dailygreen.cli.MockGitHubClient", _unexpected_call)

    runner = CliRunner()
    result = runner.invoke(main, [
        "discover",
        "--repo", "mahmudjanovr/tolkin-olami",
        "--repos-config", str(repos_file),
    ])

    assert result.exit_code == 1
    assert "Repository 'mahmudjanovr/tolkin-olami' is not authorized in allowlist." in result.output
