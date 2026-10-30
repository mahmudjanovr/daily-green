"""Unit tests for Phase 2 context-aware AI file selection, planning, and execution."""

from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.models import RiskLevel, Task, TaskPlan, TaskSource


def test_select_relevant_files_bounds_context():
    adapter = MockAIAdapter()
    candidate_files = [
        "docs/faq.md",
        "docs/setup.md",
        "docs/api.md",
        "docs/deploy.md",
        "docs/architecture.md",
        "docs/troubleshooting.md",
        "README.md",
    ]

    task = Task(
        id="t-setup",
        repo="org/repo",
        title="Clarify setup instructions and prerequisites",
        description="Improve setup guide for new developers",
        rationale="Better onboarding",
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["docs/setup.md"],
    )

    selected = adapter.select_relevant_files(task, candidate_files, max_files=3)
    assert len(selected) <= 3
    assert "docs/setup.md" in selected  # Must prioritize target file!


def test_mock_adapter_custom_plan_and_explanations():
    custom_plan = TaskPlan(
        task_id="t-plan",
        problem_statement="Problem statement",
        evidence_and_affected_files=["README.md"],
        proposed_solution="Proposed solution",
        implementation_steps=["Step 1"],
        expected_behavior="Expected behavior",
        tests_required=["pytest"],
        risk_assessment="low",
        acceptance_criteria=["Done"],
    )

    adapter = MockAIAdapter(custom_plan=custom_plan)
    task = Task(
        id="t-plan",
        repo="org/repo",
        title="Title",
        description="Desc",
        rationale="Rat",
        validation_strategy="val",
        source=TaskSource.AI,
        target_files=["README.md"],
    )

    plan = adapter.create_plan(task, {})
    assert plan is not None
    assert plan.task_id == "t-plan"

    explanations = adapter.explain_changes({"README.md": "content"}, task)
    assert "README.md" in explanations
    assert "t-plan" in explanations["README.md"]


def test_implement_task_with_plan_returns_explanations():
    adapter = MockAIAdapter()
    task = Task(
        id="t-impl",
        repo="org/repo",
        title="Update docs",
        description="Desc",
        rationale="Rat",
        validation_strategy="val",
        source=TaskSource.AI,
        target_files=["README.md"],
    )

    files, explanations = adapter.implement_task_with_plan(task, None, {"existing_files": {"README.md": "# Doc\n"}})
    assert "README.md" in files
    assert "README.md" in explanations
