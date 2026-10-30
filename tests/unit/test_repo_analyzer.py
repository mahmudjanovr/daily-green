"""Unit tests for Phase 2 repository context analyzer and issue intelligence."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import IssueStatus, TaskCategory
from dailygreen.repo_analyzer import (
    analyze_github_issue,
    analyze_repository_context,
    categorize_issue_content,
    detect_project_type,
    scan_maintenance_signals,
)
from dailygreen.state import StateManager


def test_detect_project_type(tmp_path: Path):
    assert detect_project_type(tmp_path) == "generic"

    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    assert detect_project_type(tmp_path) == "python"

    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert detect_project_type(tmp_path) == "node"

    (tmp_path / "package.json").unlink()
    (tmp_path / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
    assert detect_project_type(tmp_path) == "rust"


def test_categorize_issue_content():
    assert categorize_issue_content("Bump fastapi from 0.100 to 0.101", "") == TaskCategory.DEPENDENCY_UPDATE
    assert categorize_issue_content("Fix typo in setup instructions", "The word recieve is misspelled") == TaskCategory.DOCUMENTATION
    assert categorize_issue_content("NullPointerException in payment parser", "System crashes on empty payload") == TaskCategory.BUG_FIX
    assert categorize_issue_content("Refactor auth token handler", "Clean up monolithic function") == TaskCategory.REFACTORING
    assert categorize_issue_content("Periodic chore", "Routine maintenance") == TaskCategory.MAINTENANCE


def test_scan_maintenance_signals(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f1 = docs / "guide.md"
    f1.write_text("Read [details](missing_file.md) and note that you will recieve updates.   \n", encoding="utf-8")

    signals = scan_maintenance_signals(tmp_path, ["docs/guide.md"])
    types = [s["type"] for s in signals]
    assert "broken_link" in types
    assert "typo" in types
    assert "formatting" in types


def test_analyze_repository_context(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md", "docs/**"])
    policy = SecurityPolicyConfig()

    (tmp_path / "README.md").write_text("# Project\nOverview.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='proj'\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("Content.\n", encoding="utf-8")

    context = analyze_repository_context(tmp_path, repo_cfg, policy)
    assert context.repo_name == "org/repo"
    assert context.project_type == "python"
    assert context.readme_path == "README.md"
    assert "README.md" in context.allowed_files
    assert "docs/index.md" in context.allowed_files
    assert "pyproject.toml" in context.key_files


def test_analyze_github_issue_actionable(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "api.md").write_text("API documentation with typo teh in line 1.", encoding="utf-8")

    issue = {
        "number": 101,
        "title": "Fix typo in docs/api.md",
        "body": "There is a typo 'teh' in `docs/api.md`. Please fix it.\n- [ ] Correct teh to the",
        "labels": ["dailygreen"],
    }

    analysis = analyze_github_issue(issue, tmp_path, repo_cfg, policy, state_mgr)
    assert analysis.status == IssueStatus.ACTIONABLE
    assert analysis.category == TaskCategory.DOCUMENTATION
    assert "docs/api.md" in analysis.target_files
    assert len(analysis.acceptance_criteria) >= 1


def test_analyze_github_issue_detects_stale(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    # Stale by label
    issue_labeled = {
        "number": 10,
        "title": "Old task",
        "body": "README.md update needed",
        "labels": ["stale"],
    }
    res1 = analyze_github_issue(issue_labeled, tmp_path, repo_cfg, policy, state_mgr)
    assert res1.status == IssueStatus.STALE

    # Stale by age (> 180 days)
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    issue_old = {
        "number": 11,
        "title": "Ancient issue",
        "body": "README.md update needed",
        "created_at": old_date,
        "updated_at": old_date,
        "labels": [],
    }
    res2 = analyze_github_issue(issue_old, tmp_path, repo_cfg, policy, state_mgr)
    assert res2.status == IssueStatus.STALE


def test_analyze_github_issue_detects_duplicate(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    issue_1 = {"number": 20, "title": "Update README docs", "body": "README.md details"}
    issue_2 = {"number": 21, "title": "Update README docs", "body": "README.md details duplicate"}

    res = analyze_github_issue(issue_2, tmp_path, repo_cfg, policy, state_mgr, other_issues=[issue_1, issue_2])
    assert res.status == IssueStatus.DUPLICATE
    assert "older issue #20" in res.reason


def test_analyze_github_issue_detects_ambiguous(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["README.md"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    vague_issue = {
        "number": 30,
        "title": "fix it",
        "body": "please fix",
    }
    res = analyze_github_issue(vague_issue, tmp_path, repo_cfg, policy, state_mgr)
    assert res.status == IssueStatus.AMBIGUOUS


def test_analyze_github_issue_detects_already_resolved(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    docs = tmp_path / "docs"
    docs.mkdir()
    # File already has correct spelling "the", not "teh"
    (docs / "clean.md").write_text("This has the correct spelling.\n", encoding="utf-8")

    issue = {
        "number": 40,
        "title": "Fix typo in docs/clean.md",
        "body": "Found typo 'teh' in `docs/clean.md`",
    }
    res = analyze_github_issue(issue, tmp_path, repo_cfg, policy, state_mgr)
    assert res.status == IssueStatus.ALREADY_RESOLVED
    assert "already resolved" in res.reason.lower()


def test_analyze_github_issue_detects_unsupported(tmp_path: Path):
    repo_cfg = RepoConfig(name="org/repo", allowed_paths=["docs/**"])
    policy = SecurityPolicyConfig()
    state_mgr = StateManager(state_dir=tmp_path / ".dailygreen")

    # Mentions file outside allowed_paths
    issue = {
        "number": 50,
        "title": "Modify github workflow",
        "body": "Please edit `.github/workflows/deploy.yml` with updates.",
    }
    res = analyze_github_issue(issue, tmp_path, repo_cfg, policy, state_mgr)
    assert res.status == IssueStatus.UNSUPPORTED
