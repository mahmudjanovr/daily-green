"""
Adversarial AI output tests for the Quality Gate and Task Engine.
Verifies that rogue, malformed, out-of-scope, or deceptive AI outputs are strictly rejected.
"""

import subprocess
from pathlib import Path
from typing import Any, Optional
import pytest

from dailygreen.ai.base import AIAdapter, AIAdapterError
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import RiskLevel, Task, TaskCategory, TaskSource
from dailygreen.quality_gate import evaluate_quality_gate, validate_semantic_diff
from dailygreen.task_engine import TaskEngineError, implement_task


class AdversarialMockAdapter(AIAdapter):
    """
    Test-only adversarial AI adapter simulating rogue, hallucinated, or deceptive AI behaviors.
    Strictly isolated to tests/ and never used in production.
    """

    def __init__(self, mode: str, custom_payload: Optional[str] = None):
        self.mode = mode
        self.custom_payload = custom_payload

    def propose_tasks(self, repo_context: dict[str, Any]) -> list[Task]:
        return []

    def implement_task(self, task: Task, repo_context: dict[str, Any]) -> dict[str, str]:
        target = task.target_files[0] if task.target_files else "README.md"
        existing = repo_context.get("existing_files", {}).get(target, "# Title\n\nExisting documentation content.\n")
        files: dict[str, str] = {}

        if self.mode == "self_link":
            # Links file to itself: e.g. [Documentation Guide](README.md) inside README.md
            files[target] = existing.rstrip() + f"\n\nSee [Documentation Guide]({Path(target).name}) for details.\n"
        elif self.mode == "unrelated_link":
            # Adds unrelated link to administrative file (LICENSE)
            files[target] = existing.rstrip() + "\n\nSee [Project License](LICENSE) for details.\n"
        elif self.mode == "prose_only_link":
            # Modifies prose only without adding or fixing any markdown links
            files[target] = existing.rstrip() + "\n\nWe updated the prose explanation here without any links.\n"
        elif self.mode == "outside_file":
            # Modifies a file outside target_files and outside allowed_paths
            files["unauthorized_secret.py"] = "SECRET_TOKEN = 'exposed'\n"
        elif self.mode == "diff_over_max_lines":
            # Exceeds max_diff_lines limit (> 50 lines)
            extra_lines = "\n".join(f"Line {i}: excessive machine generated content." for i in range(65))
            files[target] = existing.rstrip() + f"\n\n{extra_lines}\n"
        elif self.mode == "secret_token":
            # Emits classic GitHub personal access token pattern
            files[target] = existing.rstrip() + "\ngithub_token = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'\n"
        elif self.mode == "code_fence_change":
            # Changes code inside a fenced code block during a formatting task
            files[target] = existing.replace("return 1", "return 999_ADVERSARIAL")
        elif self.mode == "comment_html":
            files[target] = existing.rstrip() + "\n\n<!-- Deceptive comment only -->\n"
        elif self.mode == "comment_hash":
            files[target] = existing.rstrip() + "\n\n# Deceptive comment only\n"
        elif self.mode == "comment_slash":
            files[target] = existing.rstrip() + "\n\n// Deceptive comment only\n"
        elif self.mode == "empty_output":
            return {}
        elif self.mode == "malformed_output":
            raise AIAdapterError("AI response was malformed JSON or failed schema validation: unexpected EOF")
        elif self.mode == "mass_deletion":
            # Deletes over 90% of a multi-line file
            files[target] = "# Truncated\n"
        elif self.mode == "whitespace_only_typo":
            # Pointless whitespace change without fixing typo
            files[target] = existing.replace("intro teh typo", "intro  teh  typo")
        elif self.mode == "whitespace_only_link":
            # Pointless whitespace change without fixing link
            files[target] = existing.replace("[Guide](missing.md)", "[Guide]  (missing.md)")
        else:
            files[target] = existing + "\nSafe modification.\n"

        return files

    def explain_diff(self, diff: str) -> str:
        return "Adversarial PR explanation."


def _setup_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(path), capture_output=True, check=True)


def test_reject_self_link(tmp_path: Path):
    """Assert rejection of a link task where the diff links a file to itself."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nIntro documentation.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="test-doc-links",
        repo="org/repo",
        title="Fix broken relative links",
        description="Verify and repair documentation links in README.",
        rationale="Improve doc navigation.",
        acceptance_criteria=["Relative Markdown links point to existing files."],
        risk_level=RiskLevel.LOW,
        validation_strategy="deterministic_markdown_link_check",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="self_link")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "self" in gate.reason.lower()


def test_reject_unrelated_license_link(tmp_path: Path):
    """Assert rejection of a link task that links to an unrelated file (LICENSE)."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nIntro documentation.\n", encoding="utf-8")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT License\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="test-doc-links",
        repo="org/repo",
        title="Fix documentation link references",
        description="Verify and update broken links in README.",
        rationale="Ensure reader navigation works.",
        acceptance_criteria=["Markdown links resolve correctly."],
        risk_level=RiskLevel.LOW,
        validation_strategy="deterministic_markdown_link_check",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="unrelated_link")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md", "LICENSE"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "unrelated link target" in gate.reason.lower()


def test_reject_prose_only_link_task(tmp_path: Path):
    """Assert rejection when a link task produces diff with prose changes but zero link changes."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nIntro documentation.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="test-doc-links",
        repo="org/repo",
        title="Check documentation links",
        description="Ensure documentation links resolve.",
        rationale="Documentation reliability.",
        acceptance_criteria=["Relative Markdown links point to existing files."],
        risk_level=RiskLevel.LOW,
        validation_strategy="deterministic_markdown_link_check",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="prose_only_link")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "no link-related changes" in gate.reason.lower()


def test_reject_file_outside_allowed_paths_and_target_files(tmp_path: Path):
    """Assert rejection when AI touches a file outside allowed_paths or outside target_files."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nContent.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-task",
        repo="org/repo",
        title="Update docs",
        description="Update readme.",
        rationale="Clarity.",
        acceptance_criteria=["Content updated."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="outside_file")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "unrelated file modification" in gate.reason.lower() or "not permitted" in gate.reason.lower()


def test_reject_diff_over_max_diff_lines(tmp_path: Path):
    """Assert rejection when proposed diff exceeds configured max_diff_lines limit."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nContent.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-task",
        repo="org/repo",
        title="Update docs",
        description="Update readme.",
        rationale="Clarity.",
        acceptance_criteria=["Content updated."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="diff_over_max_lines")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"], max_diff_lines=50)
    policy = SecurityPolicyConfig(max_diff_lines=50)
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "exceeds maximum limit" in gate.reason.lower()


def test_reject_diff_containing_secret_token(tmp_path: Path):
    """Assert rejection when proposed diff embeds secret-like token pattern."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nContent.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-task",
        repo="org/repo",
        title="Update docs",
        description="Update readme.",
        rationale="Clarity.",
        acceptance_criteria=["Content updated."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="secret_token")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "secrets detected" in gate.reason.lower() or "github classic token" in gate.reason.lower()


def test_reject_code_fence_modification_in_formatting_task(tmp_path: Path):
    """Assert rejection when a formatting task modifies code inside a fenced code block."""
    _setup_git_repo(tmp_path)
    doc = tmp_path / "GUIDE.md"
    initial_content = (
        "# Guide\n\n"
        "Here is code:\n\n"
        "```python\n"
        "def compute():\n"
        "    return 1\n"
        "```\n"
    )
    doc.write_text(initial_content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="format-guide-docs",
        repo="org/repo",
        title="Format markdown documentation",
        description="Clean trailing whitespace and format Markdown.",
        rationale="Formatting consistency.",
        acceptance_criteria=["Trailing whitespace cleaned."],
        risk_level=RiskLevel.LOW,
        validation_strategy="formatting",
        source=TaskSource.AI,
        target_files=["GUIDE.md"],
        metadata={"format_type": "whitespace_and_eof"},
    )
    adapter = AdversarialMockAdapter(mode="code_fence_change")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["GUIDE.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "fenced code block" in gate.reason.lower()


@pytest.mark.parametrize("comment_mode", ["comment_html", "comment_hash", "comment_slash"])
def test_reject_comment_only_diffs(tmp_path: Path, comment_mode: str):
    """Assert rejection of HTML, hash, and slash comment-only diffs for functional/doc tasks."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nContent.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-clarity",
        repo="org/repo",
        title="Improve documentation clarity",
        description="Substantive documentation improvement.",
        rationale="Better readability.",
        acceptance_criteria=["Documentation is improved."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode=comment_mode)
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "comment-only" in gate.reason.lower()


def test_reject_empty_and_malformed_output(tmp_path: Path):
    """Assert rejection of empty and malformed AI outputs."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nContent.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-task",
        repo="org/repo",
        title="Improve docs",
        description="Docs improvement.",
        rationale="Clarity.",
        acceptance_criteria=["Done."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )

    # Empty output
    adapter_empty = AdversarialMockAdapter(mode="empty_output")
    with pytest.raises(TaskEngineError) as exc_empty:
        implement_task(tmp_path, task, adapter_empty)
    assert "no file modifications" in str(exc_empty.value).lower()

    # Malformed output
    adapter_malformed = AdversarialMockAdapter(mode="malformed_output")
    with pytest.raises(TaskEngineError) as exc_malformed:
        implement_task(tmp_path, task, adapter_malformed)
    assert "malformed" in str(exc_malformed.value).lower() or "schema validation" in str(exc_malformed.value).lower()


def test_reject_mass_deletion_output(tmp_path: Path):
    """Assert rejection when AI deletes most of the target file without explicit deletion intent."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    # Create 30 lines of documentation
    doc_lines = "\n".join(f"Paragraph {i}: This is detailed documentation content." for i in range(30))
    readme.write_text(f"# Project\n\n{doc_lines}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    task = Task(
        id="doc-improvement",
        repo="org/repo",
        title="Improve documentation wording",
        description="Refine documentation clarity.",
        rationale="Clarity.",
        acceptance_criteria=["Documentation refined."],
        risk_level=RiskLevel.LOW,
        validation_strategy="docs",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter = AdversarialMockAdapter(mode="mass_deletion")
    diff = implement_task(tmp_path, task, adapter)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    gate = evaluate_quality_gate(tmp_path, task, diff, repo_cfg, policy)

    assert gate.passed is False
    assert "deletes most of the file" in gate.reason.lower()


def test_reject_pointless_whitespace_only_in_typo_and_link_tasks(tmp_path: Path):
    """Assert rejection of cosmetic whitespace-only changes in typo or link tasks."""
    _setup_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nHere is an intro teh typo.\nSee [Guide](missing.md).\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()

    # 1. Typo task with whitespace-only edit
    typo_task = Task(
        id="fix-typo-teh",
        repo="org/repo",
        title="Fix typo in README",
        description="Correct typo 'teh' to 'the'.",
        rationale="Typo fix.",
        acceptance_criteria=["Typo corrected."],
        risk_level=RiskLevel.LOW,
        validation_strategy="typo",
        source=TaskSource.AI,
        target_files=["README.md"],
        metadata={"typo": "teh", "replacement": "the"},
    )
    adapter_typo = AdversarialMockAdapter(mode="whitespace_only_typo")
    diff_typo = implement_task(tmp_path, typo_task, adapter_typo)
    gate_typo = evaluate_quality_gate(tmp_path, typo_task, diff_typo, repo_cfg, policy)

    assert gate_typo.passed is False
    assert (
        "cosmetic whitespace" in gate_typo.reason.lower()
        or "does not modify that typo" in gate_typo.reason.lower()
    )

    # 2. Link task with whitespace-only edit
    link_task = Task(
        id="fix-link-guide",
        repo="org/repo",
        title="Fix broken link",
        description="Fix broken link reference.",
        rationale="Link navigation.",
        acceptance_criteria=["Links work."],
        risk_level=RiskLevel.LOW,
        validation_strategy="deterministic_markdown_link_check",
        source=TaskSource.AI,
        target_files=["README.md"],
    )
    adapter_link = AdversarialMockAdapter(mode="whitespace_only_link")
    diff_link = implement_task(tmp_path, link_task, adapter_link)
    gate_link = evaluate_quality_gate(tmp_path, link_task, diff_link, repo_cfg, policy)

    assert gate_link.passed is False
    assert (
        "cosmetic whitespace" in gate_link.reason.lower()
        or "contains no link-related changes" in gate_link.reason.lower()
    )
