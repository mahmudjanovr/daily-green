"""Tests verifying delivery artifact validation, cross-repo substitution prevention, and input sanitization."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from dailygreen.cli import main
from dailygreen.quality_gate import compute_patch_hash


def _write_artifact(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_repos_config(path: Path) -> None:
    path.write_text("""
repositories:
  - name: "authorized-org/good-repo"
    allowed_paths: ["docs/**", "README.md"]
    max_diff_lines: 50
""", encoding="utf-8")


def test_artifact_unauthorized_repository_rejected(tmp_path: Path):
    """Deliver command rejects sealed artifacts referencing repositories not in allowlist."""
    artifact_path = tmp_path / "sealed_task.json"
    _write_artifact(artifact_path, {
        "repo": "unauthorized-org/rogue-repo",
        "task": {
            "id": "task-1",
            "repo": "unauthorized-org/rogue-repo",
            "title": "Title",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": "dummy"},
        "diff_text": "diff",
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "not authorized in allowlist" in result.output.lower() or "not authorized" in result.output.lower()


def test_artifact_malformed_task_id_rejected(tmp_path: Path):
    """Deliver command rejects artifacts with task IDs containing shell metachars or directory traversal."""
    artifact_path = tmp_path / "sealed_task.json"
    diff = "@@ -1,1 +1,1 @@\n"
    _write_artifact(artifact_path, {
        "repo": "authorized-org/good-repo",
        "task": {
            "id": "task-1; rm -rf /",  # Malicious ID
            "repo": "authorized-org/good-repo",
            "title": "Title",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": compute_patch_hash(diff)},
        "diff_text": diff,
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "malformed or unsafe task id" in result.output.lower()


def test_artifact_forbidden_target_path_rejected(tmp_path: Path):
    """Deliver command rejects artifacts attempting to target CI workflows or secrets."""
    artifact_path = tmp_path / "sealed_task.json"
    diff = "@@ -1,1 +1,1 @@\n"
    _write_artifact(artifact_path, {
        "repo": "authorized-org/good-repo",
        "task": {
            "id": "poison-workflow",
            "repo": "authorized-org/good-repo",
            "title": "Poison CI",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": [".github/workflows/deploy.yml"],  # Forbidden path!
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": compute_patch_hash(diff)},
        "diff_text": diff,
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "is forbidden" in result.output.lower()


def test_artifact_tampered_diff_hash_rejected(tmp_path: Path):
    """Deliver command rejects artifacts where diff_text was modified after quality gate."""
    artifact_path = tmp_path / "sealed_task.json"
    diff = "@@ -1,1 +1,1 @@\n"
    _write_artifact(artifact_path, {
        "repo": "authorized-org/good-repo",
        "task": {
            "id": "tampered-patch",
            "repo": "authorized-org/good-repo",
            "title": "Tampered",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": "original_valid_hash_abcdef"},
        "diff_text": "@@ -1,1 +1,2 @@\n+tampered malicious line\n",
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "does not match quality gate seal" in result.output.lower()


def test_artifact_diff_size_limit_exceeded_rejected(tmp_path: Path):
    """Deliver command rejects artifacts exceeding allowed max_diff_lines."""
    # Generate 60 lines diff (limit is 50 in _write_repos_config)
    lines = "\n".join(f"+line {i}" for i in range(60))
    diff = f"@@ -0,0 +1,60 @@\n{lines}\n"
    artifact_path = tmp_path / "sealed_task.json"
    _write_artifact(artifact_path, {
        "repo": "authorized-org/good-repo",
        "task": {
            "id": "oversized-task",
            "repo": "authorized-org/good-repo",
            "title": "Oversized",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": compute_patch_hash(diff)},
        "diff_text": diff,
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "exceed limit" in result.output.lower()


def test_artifact_secret_detected_rejected(tmp_path: Path):
    """Deliver command rejects artifacts containing detected secrets in diff."""
    secret_diff = "@@ -1,1 +1,2 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"
    artifact_path = tmp_path / "sealed_task.json"
    _write_artifact(artifact_path, {
        "repo": "authorized-org/good-repo",
        "task": {
            "id": "leaked-secret-task",
            "repo": "authorized-org/good-repo",
            "title": "Leaked Secret",
            "description": "Desc",
            "rationale": "Rat",
            "acceptance_criteria": ["AC"],
            "risk_level": "low",
            "validation_strategy": "strat",
            "source": "deterministic",
            "target_files": ["README.md"],
        },
        "quality_gate": {"passed": True, "reason": "OK", "patch_hash": compute_patch_hash(secret_diff)},
        "diff_text": secret_diff,
    })

    repos_config = tmp_path / "repos.yml"
    _write_repos_config(repos_config)

    runner = CliRunner()
    result = runner.invoke(main, [
        "deliver",
        "--sealed-artifact", str(artifact_path),
        "--repos-config", str(repos_config),
        "--mock-github",
    ])
    assert result.exit_code == 1
    assert "secrets detected" in result.output.lower()
