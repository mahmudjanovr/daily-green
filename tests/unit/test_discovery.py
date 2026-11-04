"""Unit tests for rules-first task discovery, deterministic detection, and deduplication."""

from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RiskLevel, TaskSource
from dailygreen.state import StateManager
from dailygreen.task_discovery import (
    discover_backlog_tasks,
    discover_deterministic_formatting_tasks,
    discover_deterministic_link_tasks,
    discover_deterministic_typo_tasks,
    discover_issue_tasks,
    discover_next_task,
)


def test_discover_issue_task(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    github_client = MockGitHubClient(
        labeled_issues={
            "org/repo": [
                {
                    "number": 42,
                    "title": "Fix typo in README",
                    "body": "Please update README.md to fix typos.",
                    "html_url": "https://github.com/org/repo/issues/42",
                }
            ]
        }
    )

    tasks = discover_issue_tasks(repo, policy, github_client, state_mgr)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == TaskSource.ISSUE
    assert task.id == "issue-42"
    assert "README.md" in task.target_files


def test_discover_backlog_task(tmp_path: Path):
    repo = RepoConfig(
        name="org/repo",
        allowed_paths=["docs/**"],
        curated_tasks=[
            {
                "id": "backlog-1",
                "title": "Update installation docs",
                "description": "Add pip install instructions",
                "acceptance_criteria": ["Installation steps are clear"],
                "risk_level": "low",
                "validation_strategy": "verify_docs",
                "target_files": ["docs/install.md"],
            }
        ],
    )
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    tasks = discover_backlog_tasks(repo, policy, state_mgr)
    assert len(tasks) == 1
    assert tasks[0].id == "backlog-1"
    assert tasks[0].source == TaskSource.BACKLOG


def test_discover_deterministic_broken_link(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    md_file = docs_dir / "guide.md"
    # Link pointing to non-existent file
    md_file.write_text("Check out the [architecture](architecture_missing.md) guide.", encoding="utf-8")

    tasks = discover_deterministic_link_tasks(tmp_path, repo, policy, state_mgr)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == TaskSource.DETERMINISTIC
    assert "architecture_missing.md" in task.metadata["broken_target"]


def test_discover_deterministic_formatting(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    md_file = docs_dir / "style.md"
    # Trailing whitespace on line
    md_file.write_text("# Heading   \nLine 1\n", encoding="utf-8")

    tasks = discover_deterministic_formatting_tasks(tmp_path, repo, policy, state_mgr)
    assert len(tasks) == 1
    assert tasks[0].source == TaskSource.DETERMINISTIC


def test_discover_deterministic_typo(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    md_file = docs_dir / "index.md"
    md_file.write_text("This is teh main entry point.", encoding="utf-8")

    tasks = discover_deterministic_typo_tasks(tmp_path, repo, policy, state_mgr)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == TaskSource.DETERMINISTIC
    assert task.metadata["typo"] == "teh"


def test_discover_priority_order(tmp_path: Path):
    """Verify that Issue has higher priority than Backlog, which has higher priority than Deterministic."""
    repo = RepoConfig(
        name="org/repo",
        allowed_paths=["docs/**", "README.md"],
        curated_tasks=[
            {
                "id": "backlog-task",
                "title": "Backlog item",
                "target_files": ["README.md"],
            }
        ],
    )
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    # Put a typo in docs to create a deterministic task
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("This is teh documentation.", encoding="utf-8")

    # Issue present on GitHub
    github_client = MockGitHubClient(
        labeled_issues={
            "org/repo": [
                {
                    "number": 99,
                    "title": "Issue task",
                    "body": "README.md",
                }
            ]
        }
    )

    # 1. Issue wins over backlog and deterministic
    t1 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t1 is not None
    assert t1.id == "issue-99"

    # Mark issue done
    state_mgr.record_task_completion("org/repo", "issue-99")

    # 2. Backlog wins over deterministic
    t2 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t2 is not None
    assert t2.id == "backlog-task"

    # Mark backlog done
    state_mgr.record_task_completion("org/repo", "backlog-task")

    # 3. Deterministic wins
    t3 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t3 is not None
    assert t3.source == TaskSource.DETERMINISTIC


def test_discover_no_task_returns_none(tmp_path: Path):
    """When workspace is clean and no backlog/issues exist, returns None."""
    repo = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")
    github_client = MockGitHubClient()

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Clean Documentation\nClean content.\n", encoding="utf-8")

    task = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert task is None


def test_discover_realistic_repo_fixture(tmp_path: Path):
    """Realistic repository with multiple files, verifying stable task IDs and sequential completion."""
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md", "docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")
    github_client = MockGitHubClient()

    # Create realistic repo structure
    (tmp_path / "README.md").write_text("# Main Project\nClean content.\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Docs\nSee [setup](setup.md).\n", encoding="utf-8")
    # File with typo
    (docs_dir / "setup.md").write_text("# Setup\nYou will recieve instructions here.\n", encoding="utf-8")
    # File with trailing space formatting
    (docs_dir / "faq.md").write_text("# FAQ   \nCommon questions.\n", encoding="utf-8")

    # 1. Discover first task (formatting or typo based on priority)
    t1 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t1 is not None
    assert t1.id in ("format-docs-faq.md", "typo-recieve-docs-setup.md")

    # Task ID must be strictly stable across repeated discovery calls
    t1_again = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t1_again is not None
    assert t1_again.id == t1.id

    # Complete task 1
    state_mgr.record_task_completion("org/repo", t1.id)

    # 2. Discover remaining task
    t2 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t2 is not None
    assert t2.id != t1.id

    # Complete task 2
    state_mgr.record_task_completion("org/repo", t2.id)

    # 3. Everything is done -> NO_TASK
    t3 = discover_next_task(tmp_path, repo, policy, github_client, state_mgr)
    assert t3 is None
