"""Unit tests for cryptographic patch and tree integrity verification."""

import subprocess
import pytest
from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import DeliveryError, deliver_pull_request
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash, evaluate_quality_gate
from dailygreen.security import safe_git_command


def _setup_git_repo(path: Path) -> str:
    """Initialize a git repo with a tracked README.md and return initial commit SHA."""
    subprocess.run(safe_git_command(["git", "init", "-b", "main"]), cwd=str(path), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.name", "Tester"]), cwd=str(path), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.email", "test@test.com"]), cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("# Project\nLine 1\n", encoding="utf-8")
    subprocess.run(safe_git_command(["git", "add", "README.md"]), cwd=str(path), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "commit", "-m", "init"]), cwd=str(path), capture_output=True, check=True)
    res = subprocess.run(safe_git_command(["git", "rev-parse", "HEAD"]), cwd=str(path), capture_output=True, text=True, check=True)
    return res.stdout.strip()


def test_integrity_detects_post_validation_file_modification(tmp_path: Path):
    """If a file is altered after quality gate evaluation, delivery must fail."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    # Apply change
    (repo_dir / "README.md").write_text("# Project\nLine 1\nLine 2 added.\n", encoding="utf-8")
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="add-line",
        repo="org/repo",
        title="Add line",
        description="Desc",
        rationale="Rat",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    # Evaluate quality gate
    qg = evaluate_quality_gate(repo_dir, task, "", repo_cfg, policy)
    assert qg.passed is True
    assert qg.tree_sha is not None

    # TAMPER: Alter file content after quality gate approval
    (repo_dir / "README.md").write_text("# Project\nTAMPERED CONTENT\n", encoding="utf-8")

    # Delivery must detect the tampered working tree and fail
    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=qg,
            diff_text=qg.verified_diff or "",
            repo_config=repo_cfg,
            policy=policy,
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Working tree integrity violation" in str(exc.value)


def test_integrity_detects_post_validation_file_addition(tmp_path: Path):
    """If an unauthorized untracked file is created after quality gate, delivery must fail."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    (repo_dir / "README.md").write_text("# Project\nLine 1\nLine 2\n", encoding="utf-8")
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md", "sneaky.txt"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-1",
        repo="org/repo",
        title="T",
        description="D",
        rationale="R",
        validation_strategy="V",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    qg = evaluate_quality_gate(repo_dir, task, "", repo_cfg, policy)
    assert qg.passed is True

    # TAMPER: Add an unauthorized extra file
    (repo_dir / "sneaky.txt").write_text("malicious payload", encoding="utf-8")

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=qg,
            diff_text=qg.verified_diff or "",
            repo_config=repo_cfg,
            policy=policy,
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Working tree integrity violation" in str(exc.value)


def test_integrity_detects_post_validation_file_removal(tmp_path: Path):
    """If a file is removed after quality gate evaluation, delivery must fail."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    (repo_dir / "README.md").write_text("# Project\nLine 1\nLine 2\n", encoding="utf-8")
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-1",
        repo="org/repo",
        title="T",
        description="D",
        rationale="R",
        validation_strategy="V",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    qg = evaluate_quality_gate(repo_dir, task, "", repo_cfg, policy)
    assert qg.passed is True

    # TAMPER: Delete file
    (repo_dir / "README.md").unlink()

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=qg,
            diff_text=qg.verified_diff or "",
            repo_config=repo_cfg,
            policy=policy,
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Working tree integrity violation" in str(exc.value)


def test_integrity_detects_changed_base_commit(tmp_path: Path):
    """If base commit changed underneath the task, delivery must fail."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    initial_sha = _setup_git_repo(repo_dir)

    (repo_dir / "README.md").write_text("# Project\nLine 1\nLine 2\n", encoding="utf-8")
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-1",
        repo="org/repo",
        title="T",
        description="D",
        rationale="R",
        validation_strategy="V",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    qg = evaluate_quality_gate(repo_dir, task, "", repo_cfg, policy)
    assert qg.passed is True

    # Tamper base commit SHA in gate seal to simulate diverged base
    tampered_qg = qg.model_copy(update={"base_commit_sha": "0000000000000000000000000000000000000000"})

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=tampered_qg,
            diff_text=qg.verified_diff or "",
            repo_config=repo_cfg,
            policy=policy,
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Base commit mismatch" in str(exc.value)


def test_integrity_detects_git_mode_change(tmp_path: Path):
    """If git executable mode is toggled, tree SHA changes and delivery must fail."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    (repo_dir / "README.md").write_text("# Project\nLine 1\nLine 2\n", encoding="utf-8")
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-1",
        repo="org/repo",
        title="T",
        description="D",
        rationale="R",
        validation_strategy="V",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    qg = evaluate_quality_gate(repo_dir, task, "", repo_cfg, policy)
    assert qg.passed is True

    # Tamper mode via git update-index (make executable 100755)
    subprocess.run(
        safe_git_command(["git", "update-index", "--chmod=+x", "README.md"]),
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )

    with pytest.raises(DeliveryError) as exc:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=qg,
            diff_text=qg.verified_diff or "",
            repo_config=repo_cfg,
            policy=policy,
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Working tree integrity violation" in str(exc.value)
