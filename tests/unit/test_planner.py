"""Unit tests for Phase 2 structured task planner."""

from pathlib import Path
from dailygreen.config import RepoConfig
from dailygreen.models import RiskLevel, Task, TaskSource
from dailygreen.planner import create_task_plan


def test_create_plan_for_broken_link():
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"], baseline_command=["pytest"])
    task = Task(
        id="fix-broken-link-docs-guide.md",
        repo="org/repo",
        title="Fix broken relative link in docs/guide.md",
        description="Documentation file contains broken target 'setup_old.md'",
        rationale="Fix navigation",
        acceptance_criteria=["Link target is corrected"],
        risk_level=RiskLevel.LOW,
        validation_strategy="markdown_link_verification",
        source=TaskSource.DETERMINISTIC,
        target_files=["docs/guide.md"],
        metadata={"broken_target": "setup_old.md", "source_file": "docs/guide.md"},
    )

    plan = create_task_plan(task, Path("."), repo)
    assert plan.task_id == task.id
    assert "setup_old.md" in plan.problem_statement
    assert "setup_old.md" in plan.proposed_solution
    assert len(plan.implementation_steps) >= 3
    assert "docs/guide.md" in plan.change_explanations
    assert any("Baseline: pytest" in t for t in plan.tests_required)


def test_create_plan_for_typo():
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    task = Task(
        id="typo-recieve-README.md",
        repo="org/repo",
        title="Correct common typo 'recieve' -> 'receive' in README.md",
        description="README contains typo",
        rationale="Spelling fix",
        acceptance_criteria=["Typo corrected"],
        risk_level=RiskLevel.LOW,
        validation_strategy="typo_verification",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
        metadata={"typo": "recieve", "replacement": "receive"},
    )

    plan = create_task_plan(task, Path("."), repo)
    assert "recieve" in plan.problem_statement
    assert "receive" in plan.proposed_solution
    assert "README.md" in plan.change_explanations


def test_create_plan_for_formatting():
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    task = Task(
        id="format-docs-index.md",
        repo="org/repo",
        title="Standardize documentation formatting in docs/index.md",
        description="Remove trailing whitespace",
        rationale="Clean formatting",
        acceptance_criteria=["No trailing whitespace"],
        risk_level=RiskLevel.LOW,
        validation_strategy="formatting_verification",
        source=TaskSource.DETERMINISTIC,
        target_files=["docs/index.md"],
        metadata={"format_type": "whitespace_and_eof"},
    )

    plan = create_task_plan(task, Path("."), repo)
    assert "trailing whitespace" in plan.problem_statement
    assert "clean line endings" in plan.expected_behavior.lower()
