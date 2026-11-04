"""Unit tests for Phase 2 structured task evaluation engine."""

from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.evaluation import EVALUATION_PASSING_THRESHOLD, evaluate_task
from dailygreen.models import RiskLevel, Task, TaskCategory, TaskSource
from dailygreen.repo_analyzer import RepoContext


def test_evaluate_valid_task(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("# Project\nClean.\n", encoding="utf-8")

    task = Task(
        id="task-valid",
        repo="org/repo",
        title="Clarify README setup section",
        description="Add clear instructions to README.md for new contributors.",
        rationale="Improves onboarding developer experience.",
        acceptance_criteria=["README.md contains explicit setup steps"],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs_verification",
        source=TaskSource.ISSUE,
        category=TaskCategory.DOCUMENTATION,
        target_files=["README.md"],
    )

    ctx = RepoContext(repo_name="org/repo", default_branch="main")
    eval_res = evaluate_task(task, tmp_path, ctx, repo_cfg, policy)

    assert eval_res.passed is True
    assert eval_res.overall_score >= EVALUATION_PASSING_THRESHOLD
    assert eval_res.rejection_reason is None
    assert eval_res.relevance.score > 0
    assert eval_res.clarity_completeness.score > 0
    assert eval_res.technical_feasibility.score > 0
    assert eval_res.expected_impact.score > 0
    assert eval_res.risk_assessment.score > 0
    assert eval_res.estimated_complexity.score > 0
    assert eval_res.permissions_and_dependencies.score > 0


def test_evaluate_task_rejects_disallowed_path(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-forbidden",
        repo="org/repo",
        title="Update secret key",
        description="Edit .env file with token",
        rationale="Update secrets",
        acceptance_criteria=["key updated"],
        validation_strategy="test",
        source=TaskSource.ISSUE,
        target_files=[".env"],
    )

    ctx = RepoContext(repo_name="org/repo", default_branch="main")
    eval_res = evaluate_task(task, tmp_path, ctx, repo_cfg, policy)

    assert eval_res.passed is False
    assert "security policy" in eval_res.rejection_reason.lower()


def test_evaluate_task_rejects_missing_target_file_for_deterministic(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-missing",
        repo="org/repo",
        title="Fix typo in missing.md",
        description="Correct spelling",
        rationale="Quality",
        acceptance_criteria=["typo fixed"],
        validation_strategy="typo_verification",
        source=TaskSource.DETERMINISTIC,
        target_files=["docs/non_existent.md"],
    )

    ctx = RepoContext(repo_name="org/repo", default_branch="main")
    eval_res = evaluate_task(task, tmp_path, ctx, repo_cfg, policy)

    assert eval_res.passed is False
    assert "missing file" in eval_res.rejection_reason.lower()


def test_evaluate_task_rejects_too_broad_scope(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()

    task = Task(
        id="task-too-broad",
        repo="org/repo",
        title="Massive refactor",
        description="Change everything",
        rationale="Refactor",
        acceptance_criteria=["all files changed"],
        validation_strategy="test",
        source=TaskSource.ISSUE,
        target_files=[f"docs/file_{i}.md" for i in range(15)],
    )

    ctx = RepoContext(repo_name="org/repo", default_branch="main")
    eval_res = evaluate_task(task, tmp_path, ctx, repo_cfg, policy)

    assert eval_res.passed is False
    assert "too broad" in eval_res.rejection_reason.lower()


def test_evaluate_task_rejects_ambiguous_task(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("content", encoding="utf-8")

    task = Task(
        id="task-vague",
        repo="org/repo",
        title="vague",
        description="do",
        rationale="",
        acceptance_criteria=[],
        validation_strategy="test",
        source=TaskSource.ISSUE,
        target_files=["README.md"],
    )

    ctx = RepoContext(repo_name="org/repo", default_branch="main")
    eval_res = evaluate_task(task, tmp_path, ctx, repo_cfg, policy)

    assert eval_res.passed is False
    assert "ambiguous" in eval_res.rejection_reason.lower()
