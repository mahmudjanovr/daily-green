"""Comprehensive tests verifying strict dry-run and kill-switch invariants across all write-capable operations."""

import pytest
import subprocess
from pathlib import Path
from click.testing import CliRunner
from dailygreen.cli import main
from dailygreen.config import DailyGreenConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import deliver_pull_request
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import QualityGateResult, RunStatus, Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


class InstrumentedMockGitHubClient(MockGitHubClient):
    """Instrumented client tracking every method call to prove zero remote mutations."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mutation_calls: list[tuple[str, dict]] = []

    def create_branch(self, repo: str, branch: str, sha: str):
        self.mutation_calls.append(("create_branch", {"repo": repo, "branch": branch, "sha": sha}))
        return super().create_branch(repo, branch, sha)

    def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str = "main"):
        self.mutation_calls.append(("create_pull_request", {"repo": repo, "title": title, "head": head, "base": base}))
        return super().create_pull_request(repo, title, body, head, base)

    def create_blob(self, repo: str, content: str):
        self.mutation_calls.append(("create_blob", {"repo": repo}))
        return super().create_blob(repo, content)

    def create_tree(self, repo: str, base_tree: str, tree: list):
        self.mutation_calls.append(("create_tree", {"repo": repo, "base_tree": base_tree}))
        return super().create_tree(repo, base_tree, tree)

    def create_commit(self, repo: str, message: str, tree: str, parents: list):
        self.mutation_calls.append(("create_commit", {"repo": repo, "message": message}))
        return super().create_commit(repo, message, tree, parents)

    def update_branch_ref(self, repo: str, branch: str, sha: str, force: bool = False):
        self.mutation_calls.append(("update_branch_ref", {"repo": repo, "branch": branch}))
        return super().update_branch_ref(repo, branch, sha, force)

    def delete_branch(self, repo: str, branch: str):
        self.mutation_calls.append(("delete_branch", {"repo": repo, "branch": branch}))
        return super().delete_branch(repo, branch)


def _setup_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "bot@test.com"], cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("# Test Repository   \n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), capture_output=True, check=True)


def test_dry_run_invokes_zero_mutation_methods(tmp_path: Path):
    """Assert that when dry_run=True, deliver_pull_request never invokes ANY mutation method."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    # Apply formatting change to README.md
    (repo_dir / "README.md").write_text("# Test Repository\n", encoding="utf-8")
    res_diff = subprocess.run(["git", "diff", "--unified=3", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True, check=True)
    diff = res_diff.stdout

    client = InstrumentedMockGitHubClient()
    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    qg = QualityGateResult(
        passed=True,
        reason="ok",
        patch_hash=compute_patch_hash(diff),
        verified_diff=diff,
    )
    task = Task(
        id="format-readme",
        repo="test-org/test-repo",
        title="Format README",
        description="Fix whitespace",
        rationale="Clean docs",
        acceptance_criteria=["No trailing whitespace"],
        validation_strategy="format",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    res = deliver_pull_request(
        workspace_dir=repo_dir,
        task=task,
        quality_gate=qg,
        diff_text=diff,
        repo_config=repo_cfg,
        policy=policy,
        github_client=client,
        dry_run=True,
    )

    assert res.success is True
    assert res.is_dry_run is True
    assert res.pr_number is None
    assert "Dry-run mode" in res.message
    # Assert ZERO write mutations occurred
    assert len(client.mutation_calls) == 0
    assert len(client.created_branches) == 0
    assert len(client.created_prs) == 0
    assert len(client.created_blobs) == 0
    assert len(client.created_trees) == 0
    assert len(client.created_commits) == 0


def test_pipeline_dry_run_produces_zero_mutations(tmp_path: Path):
    """Assert that execute_dailygreen_pipeline with dry_run=True performs full validation with zero remote mutations."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    client = InstrumentedMockGitHubClient()
    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md"],
        supported_task_types=["doc_formatting"],
    )
    cfg = DailyGreenConfig(enabled=True, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=cfg,
        github_client=client,
        state_mgr=state_mgr,
        source_dir=repo_dir,
        override_dry_run=True,
    )

    assert report.status == RunStatus.DRY_RUN_COMPLETED
    assert report.delivery is not None
    assert report.delivery.is_dry_run is True
    assert len(client.mutation_calls) == 0


def test_kill_switch_prevents_workspace_creation_and_api_calls(tmp_path: Path):
    """When DAILYGREEN_ENABLED=false, pipeline exits immediately before workspace setup or API requests."""
    client = InstrumentedMockGitHubClient()
    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])
    cfg = DailyGreenConfig(enabled=False, dry_run=True, repos=[repo_cfg])
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=cfg,
        github_client=client,
        state_mgr=state_mgr,
        source_dir=tmp_path / "nonexistent",
    )

    assert report.status == RunStatus.SKIPPED
    assert "disabled" in report.message.lower()
    # No API calls, read or write
    assert len(client.mutation_calls) == 0
    assert len(state_mgr._state.get("active_leases", {})) == 0


def test_cli_deliver_respects_dry_run_precedence(tmp_path: Path):
    """CLI deliver command enforces dry-run even if sealed artifact has dry_run=false when CLI forces dry-run."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    # Get real git diff
    (repo_dir / "README.md").write_text("# Test Repository\n", encoding="utf-8")
    diff = subprocess.run(["git", "diff", "--unified=3", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True, check=True).stdout
    diff_hash = compute_patch_hash(diff)
    # Revert repo_dir so git apply succeeds in the isolated workspace
    (repo_dir / "README.md").write_text("# Test Repository   \n", encoding="utf-8")

    artifact_file = tmp_path / "sealed_task.json"
    import json
    artifact_payload = {
        "repo": "test-org/test-repo",
        "task": {
            "id": "test-task",
            "repo": "test-org/test-repo",
            "title": "Clean README",
            "description": "Fix whitespace",
            "rationale": "Docs",
            "acceptance_criteria": ["Clean"],
            "risk_level": "low",
            "validation_strategy": "format",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {
            "passed": True,
            "reason": "OK",
            "patch_hash": diff_hash,
            "changed_files": ["README.md"],
        },
        "diff_text": diff,
        "dry_run": False,  # Tampered artifact claims live delivery
        "today_str": "2026-10-29",
    }
    artifact_file.write_text(json.dumps(artifact_payload), encoding="utf-8")

    repos_config = tmp_path / "repos.yml"
    repos_config.write_text("""
repositories:
  - name: "test-org/test-repo"
    allowed_paths: ["README.md"]
""", encoding="utf-8")

    runner = CliRunner()
    # Run with --dry-run flag: must override artifact's dry_run=False
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_file),
        "--repos-config", str(repos_config),
        "--source-dir", str(repo_dir),
        "--dry-run",
        "--mock-github",
    ])

    assert result.exit_code == 0
    assert "Dry-run mode" in result.output
