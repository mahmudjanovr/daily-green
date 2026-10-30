"""Regression tests for semantic quality gate validation, comment-only rejection, and link task verification."""

from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import CommandResult, RiskLevel, Task, TaskCategory, TaskSource
from dailygreen.quality_gate import evaluate_quality_gate, validate_semantic_diff


def _make_link_task(task_id: str = "tolkien-doc-links") -> Task:
    return Task(
        id=task_id,
        repo="mahmudjanovr/tolkin-olami",
        title="Check documentation links",
        description="Identify broken relative Markdown links in the README and documentation.",
        rationale="Keep documentation navigation reliable.",
        acceptance_criteria=["Relative Markdown links point to existing files."],
        risk_level=RiskLevel.LOW,
        validation_strategy="deterministic_markdown_link_check",
        source=TaskSource.BACKLOG,
        category=TaskCategory.MAINTENANCE,
        target_files=["README.md"],
    )


def test_quality_gate_rejects_two_line_comment_patch_for_link_task(tmp_path: Path):
    """
    Regression test for the Phase 3.4 issue:
    A two-line HTML comment appended to README.md must NOT satisfy a documentation link task.
    """
    repo = RepoConfig(name="mahmudjanovr/tolkin-olami", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    (tmp_path / "README.md").write_text("# Tolkien Olami\n\nOriginal content.\n", encoding="utf-8")

    # The exact two-line comment diff generated in Phase 3.4
    diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -10,3 +10,5 @@\n"
        " Original content.\n"
        "+\n"
        "+<!-- DailyGreen automated enhancement: documentation clarity verified -->\n"
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_make_link_task(),
        diff_text=diff,
        repo_config=repo,
        policy=policy,
    )

    assert gate.passed is False
    assert "Semantic quality gate rejected" in gate.reason
    assert (
        "comment-only" in gate.reason.lower()
        or "no link-related changes" in gate.reason.lower()
    )


def test_validate_semantic_diff_rejects_comment_only_diff():
    """Verify that comment-only additions are rejected across all documentation/functional tasks."""
    task = Task(
        id="doc-clarity-task",
        repo="org/repo",
        title="Improve documentation clarity",
        description="Refine documentation wording.",
        rationale="Improve contributor readability.",
        acceptance_criteria=["Documentation is clear."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.BACKLOG,
        category=TaskCategory.DOCUMENTATION,
        target_files=["README.md"],
    )
    comment_diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,3 @@\n"
        " # Readme\n"
        "+<!-- Just an html comment -->\n"
        "+<!-- Another comment line -->\n"
    )
    passed, reason = validate_semantic_diff(task, comment_diff, Path("."))
    assert passed is False
    assert "comment-only" in reason.lower()


def test_validate_semantic_diff_rejects_link_task_without_link_modifications():
    """Verify that a link task rejects substantive text edits that do not touch or resolve any links."""
    task = _make_link_task("tolkien-doc-links")
    non_link_diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,2 @@\n"
        " # Readme\n"
        "+This is some random text about documentation without any markdown links or references.\n"
    )
    passed, reason = validate_semantic_diff(task, non_link_diff, Path("."))
    assert passed is False
    assert "contains no link-related changes" in reason.lower()


def test_validate_semantic_diff_accepts_valid_link_modification():
    """Verify that a valid link modification is accepted."""
    task = _make_link_task("tolkien-doc-links")
    valid_link_diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,2 +1,2 @@\n"
        "-See [Dead Guide](docs/missing.md) for info.\n"
        "+See [User Guide](docs/guide.md) for info.\n"
    )
    passed, reason = validate_semantic_diff(task, valid_link_diff, Path("."))
    assert passed is True
    assert "semantically aligns" in reason.lower()


def test_quality_gate_rejects_when_broken_relative_links_remain_on_disk(tmp_path: Path):
    """Verify acceptance criteria fails when relative links in target file point to non-existent files."""
    repo = RepoConfig(name="mahmudjanovr/tolkin-olami", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    # Target README.md contains a broken relative link to docs/nonexistent.md
    (tmp_path / "README.md").write_text("# Readme\n[Broken Link](docs/nonexistent.md)\n", encoding="utf-8")

    diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,2 @@\n"
        " # Readme\n"
        "+[Broken Link](docs/nonexistent.md)\n"
    )

    gate = evaluate_quality_gate(
        workspace_dir=tmp_path,
        task=_make_link_task(),
        diff_text=diff,
        repo_config=repo,
        policy=policy,
    )

    assert gate.passed is False
    assert "relative link target 'docs/nonexistent.md'" in gate.reason.lower()
