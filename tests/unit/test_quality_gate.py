"""Unit tests for the mandatory, independent Quality Gate."""

from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import CommandResult, RiskLevel, Task, TaskSource
from dailygreen.quality_gate import compute_patch_hash, evaluate_quality_gate


def _dummy_task() -> Task:
    return Task(
        id="t1",
        repo="org/repo",
        title="Title",
        description="Desc",
        rationale="Rat",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )


def test_quality_gate_baseline_failure(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    baseline_failed = CommandResult(
        command=["pytest"],
        exit_code=1,
        stdout="",
        stderr="failed",
        duration_seconds=1.0,
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_dummy_task(),
        diff_text="diff content",
        repo_config=repo,
        policy=policy,
        baseline_result=baseline_failed,
    )
    assert gate.passed is False
    assert "Baseline tests failed" in gate.reason


def test_quality_gate_empty_diff(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_dummy_task(),
        diff_text="   \n",
        repo_config=repo,
        policy=policy,
    )
    assert gate.passed is False
    assert "Diff is empty" in gate.reason


def test_quality_gate_post_test_failure(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("clean text", encoding="utf-8")

    diff = "@@ -1,1 +1,2 @@\n+line\n"
    failed_test = CommandResult(
        command=["pytest"],
        exit_code=1,
        stdout="",
        stderr="assert failed",
        duration_seconds=2.0,
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_dummy_task(),
        diff_text=diff,
        repo_config=repo,
        policy=policy,
        post_change_tests=[failed_test],
    )
    assert gate.passed is False
    assert "failed with exit code 1" in gate.reason


def test_quality_gate_all_pass(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("clean text", encoding="utf-8")

    diff = "@@ -1,1 +1,2 @@\n+line\n"
    passed_test = CommandResult(
        command=["pytest"],
        exit_code=0,
        stdout="passed",
        stderr="",
        duration_seconds=1.0,
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_dummy_task(),
        diff_text=diff,
        repo_config=repo,
        policy=policy,
        post_change_tests=[passed_test],
    )
    assert gate.passed is True
    assert gate.patch_hash == compute_patch_hash(diff)
