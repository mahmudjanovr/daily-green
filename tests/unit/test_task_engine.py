"""Unit tests for task implementation engine, deterministic transforms, and diff generation."""

import subprocess
import pytest
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.models import RiskLevel, Task, TaskSource
from dailygreen.task_engine import (
    TaskEngineError,
    apply_deterministic_formatting,
    apply_deterministic_link_fix,
    apply_deterministic_typo_fix,
    get_git_diff,
    implement_task,
)


def _init_git_repo(path: Path):
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)


def test_apply_deterministic_formatting(tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text("Line 1   \nLine 2\t\nLine 3", encoding="utf-8")
    apply_deterministic_formatting(tmp_path, "doc.md")

    content = doc.read_text(encoding="utf-8")
    assert content == "Line 1\nLine 2\nLine 3\n"


def test_apply_deterministic_typo_fix(tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text("Please read teh manual and Teh guide.", encoding="utf-8")
    apply_deterministic_typo_fix(tmp_path, "doc.md", typo="teh", replacement="the")

    content = doc.read_text(encoding="utf-8")
    assert content == "Please read the manual and The guide.\n" or content == "Please read the manual and The guide."


def test_apply_deterministic_link_fix(tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text("See [Architecture](missing_arch.md) for details.", encoding="utf-8")
    apply_deterministic_link_fix(tmp_path, "doc.md", broken_target="missing_arch.md")

    content = doc.read_text(encoding="utf-8")
    assert "`Architecture`" in content


def test_implement_task_deterministic_e2e(tmp_path: Path):
    doc = tmp_path / "README.md"
    doc.write_text("Title   \nContent\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    task = Task(
        id="format-readme",
        repo="org/repo",
        title="Format README",
        description="Clean trailing space",
        rationale="Clean docs",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
        metadata={"format_type": "whitespace_and_eof"},
    )

    diff = implement_task(tmp_path, task)
    assert "-Title   " in diff
    assert "+Title" in diff


def test_implement_task_empty_diff_rejected(tmp_path: Path):
    doc = tmp_path / "README.md"
    doc.write_text("Already clean.\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    task = Task(
        id="format-readme",
        repo="org/repo",
        title="Format README",
        description="Clean trailing space",
        rationale="Clean docs",
        validation_strategy="docs",
        source=TaskSource.DETERMINISTIC,
        target_files=["README.md"],
        metadata={"format_type": "whitespace_and_eof"},
    )

    with pytest.raises(TaskEngineError) as exc:
        implement_task(tmp_path, task)
    assert "empty diff" in str(exc.value).lower()
