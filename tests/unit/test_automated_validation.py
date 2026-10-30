"""Unit tests for Phase 2 automated validation and unrelated file detection."""

import subprocess
from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import CommandResult, RiskLevel, Task, TaskPlan, TaskSource
from dailygreen.quality_gate import evaluate_quality_gate, verify_acceptance_criteria


def test_verify_acceptance_criteria_typo_eliminated(tmp_path: Path):
    target_file = tmp_path / "README.md"
    target_file.write_text("This text has the corrected word.\n", encoding="utf-8")

    task = Task(
        id="t-typo",
        repo="org/repo",
        title="Fix typo",
        description="Fix typo",
        rationale="Spelling",
        validation_strategy="typo",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
        metadata={"typo": "teh", "replacement": "the"},
    )

    passed, details = verify_acceptance_criteria(tmp_path, task)
    assert passed is True
    assert any("eliminated" in d for d in details)


def test_verify_acceptance_criteria_fails_if_typo_still_present(tmp_path: Path):
    target_file = tmp_path / "README.md"
    target_file.write_text("This text still contains teh word.\n", encoding="utf-8")

    task = Task(
        id="t-typo",
        repo="org/repo",
        title="Fix typo",
        description="Fix typo",
        rationale="Spelling",
        validation_strategy="typo",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
        metadata={"typo": "teh", "replacement": "the"},
    )

    passed, details = verify_acceptance_criteria(tmp_path, task)
    assert passed is False
    assert any("still present" in d for d in details)


def test_quality_gate_detects_unrelated_files_in_git(tmp_path: Path):
    # Initialize a real git repo in tmp_path to test git tree inspection
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "bot@dailygreen.local"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DailyGreen Bot"], cwd=str(tmp_path), capture_output=True, check=True)

    # Initial commit
    readme = tmp_path / "README.md"
    readme.write_text("Initial text\n", encoding="utf-8")
    extra = tmp_path / "extra.md"
    extra.write_text("Initial extra\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Modify both README.md and extra.md
    readme.write_text("Updated text\n", encoding="utf-8")
    extra.write_text("Unrelated modification\n", encoding="utf-8")

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md", "extra.md"])
    policy = SecurityPolicyConfig()

    # Task only planned to touch README.md
    task = Task(
        id="task-readme-only",
        repo="org/repo",
        title="Update README",
        description="Only update readme",
        rationale="Readme",
        validation_strategy="verify",
        source=TaskSource.ISSUE,
        target_files=["README.md"],
        plan=TaskPlan(
            task_id="task-readme-only",
            problem_statement="Update README",
            evidence_and_affected_files=["README.md"],
            proposed_solution="Update text",
            implementation_steps=["1. Edit README.md"],
            expected_behavior="Updated README",
            tests_required=[],
            risk_assessment="low",
            acceptance_criteria=["README updated"],
        ),
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=task,
        diff_text="placeholder",
        repo_config=repo_cfg,
        policy=policy,
    )

    assert gate.passed is False
    assert "Unrelated file modification(s) detected" in gate.reason
    assert "extra.md" in gate.unrelated_files_detected


def test_quality_gate_includes_detailed_validation_records(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("Clean text.\n", encoding="utf-8")

    task = Task(
        id="task-1",
        repo="org/repo",
        title="Update docs",
        description="Docs",
        rationale="Rat",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
    )

    cmd_passed = CommandResult(command=["pytest"], exit_code=0, stdout="OK", stderr="", duration_seconds=0.5)

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=task,
        diff_text="@@ -1,1 +1,2 @@\n+line\n",
        repo_config=repo_cfg,
        policy=policy,
        baseline_result=cmd_passed,
        post_change_tests=[cmd_passed],
    )

    assert gate.passed is True
    assert len(gate.validation_details) >= 4
    details_str = " ".join(gate.validation_details)
    assert "Baseline test check" in details_str
    assert "Diff emptiness check" in details_str
    assert "Security scan" in details_str
    assert "Acceptance criteria verification" in details_str
