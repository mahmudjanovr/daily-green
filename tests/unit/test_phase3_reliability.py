"""Unit and integration tests for Phase 3.2 reliability remediations:
- AI adapter timeouts and error conversion
- Subprocess timeouts and child process reaping
- Workspace ownership guard and protection of unmanaged/user repositories
- Sealed patch baseline verification and stale patch rejection
- State isolation regression test
"""

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailygreen.ai.base import AIAdapterTimeoutError
from dailygreen.ai.gemini import GeminiAIAdapter
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import AIConfig, DailyGreenConfig, ExecutionConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import DeliveryError, deliver_pull_request, verify_patch_and_tree_integrity
from dailygreen.execution_engine import ExecutionEngine
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import FailureClassification, QualityGateResult, RiskLevel, RunStatus, Task, TaskCategory, TaskSource, TaskStatus
from dailygreen.quality_gate import compute_patch_hash, evaluate_quality_gate
from dailygreen.repository_manager import (
    MARKER_FILENAME,
    IsolatedWorkspace,
    verify_managed_workspace_ownership,
    write_managed_workspace_marker,
)
from dailygreen.retry import classify_failure, evaluate_retry_eligibility
from dailygreen.state import StateManager
from dailygreen.task_queue import TaskQueue
from dailygreen.worker import run_command_in_workspace


# ---------------------------------------------------------------------------
# 1. AI Adapter Timeout Tests
# ---------------------------------------------------------------------------

def test_gemini_ai_adapter_timeout_raises_adapter_timeout_error():
    """Verify GeminiAIAdapter converts httpx.TimeoutException into AIAdapterTimeoutError."""
    cfg = AIConfig(provider="gemini", model="gemini-1.5-flash", timeout_seconds=5)
    adapter = GeminiAIAdapter(cfg)
    adapter.api_key = "dummy_test_key"

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Connection timed out")):
        with pytest.raises(AIAdapterTimeoutError) as exc_info:
            adapter._call_gemini("Test prompt")
        assert "timed out after 5s" in str(exc_info.value)


def test_mock_ai_adapter_timeout_raises_adapter_timeout_error():
    """Verify MockAIAdapter raises AIAdapterTimeoutError when should_timeout=True."""
    adapter = MockAIAdapter(should_timeout=True)
    with pytest.raises(AIAdapterTimeoutError):
        adapter.propose_tasks({"repo_name": "test/repo"})

    dummy_task = Task(
        id="t1", repo="test/repo", title="Title", description="Desc",
        rationale="Rat", acceptance_criteria=["AC"], risk_level=RiskLevel.LOW,
        validation_strategy="strat", source=TaskSource.AI, target_files=["README.md"]
    )
    with pytest.raises(AIAdapterTimeoutError):
        adapter.implement_task(dummy_task, {})


def test_ai_timeout_failure_is_not_retried_as_execution_timeout():
    """Verify task-level execution timeouts are classified as permanent, preventing unsafe retries."""
    msg = "Task 'ai-task' exceeded execution timeout (300s) during stage 'pre_implementation'"
    classification = classify_failure(msg)
    assert classification == FailureClassification.PERMANENT

    task = Task(
        id="ai-task", repo="test/repo", title="Title", description="Desc",
        rationale="Rat", acceptance_criteria=["AC"], risk_level=RiskLevel.LOW,
        validation_strategy="strat", source=TaskSource.AI, target_files=["README.md"]
    )
    eligible, reason, cls_type, _ = evaluate_retry_eligibility(task, msg, max_retries=2)
    assert not eligible
    assert cls_type == FailureClassification.PERMANENT


# ---------------------------------------------------------------------------
# 2. Subprocess Timeout Tests
# ---------------------------------------------------------------------------

def test_subprocess_timeout_in_workspace(tmp_path: Path):
    """Verify run_command_in_workspace enforces timeout and reaps child process."""
    # Run a command that takes 10 seconds with a 1 second timeout
    cmd = ["python", "-c", "import time; time.sleep(10)"]
    res = run_command_in_workspace(cmd, tmp_path, timeout_seconds=1)
    assert res.timed_out is True
    assert res.exit_code == -1
    assert "timed out after 1s" in res.stderr


# ---------------------------------------------------------------------------
# 3. Workspace Ownership Guard Tests (DG3-08)
# ---------------------------------------------------------------------------

def test_unmanaged_workspace_refuses_destructive_cleanup(tmp_path: Path):
    """Verify ExecutionEngine refuses any Git cleanup on an unmanaged repository."""
    # Create an unmanaged user repository without DailyGreen ownership marker
    user_repo = tmp_path / "user_project"
    user_repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=user_repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "User"], cwd=user_repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "user@example.com"], cwd=user_repo, capture_output=True, check=True)

    user_file = user_repo / "important.txt"
    user_file.write_text("User work in progress\n", encoding="utf-8")

    # Verification must fail closed
    assert verify_managed_workspace_ownership(user_repo, "test-org/test-repo") is False

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["important.txt"])
    config = DailyGreenConfig(enabled=True, dry_run=True, execution=ExecutionConfig(max_workers=1))
    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=StateManager(state_dir=tmp_path / "state"),
        ai_adapter=MockAIAdapter(),
        workspace_path=user_repo,
    )

    task = Task(
        id="t1", repo="test-org/test-repo", title="Title", description="Desc",
        rationale="Rat", acceptance_criteria=["AC"], risk_level=RiskLevel.LOW,
        validation_strategy="strat", source=TaskSource.DETERMINISTIC, target_files=["important.txt"]
    )

    # Calling _safe_task_cleanup must refuse destructive operations
    engine._safe_task_cleanup(task)

    # User's uncommitted file must be completely untouched
    assert user_file.exists()
    assert user_file.read_text(encoding="utf-8") == "User work in progress\n"


def test_managed_workspace_ownership_verification_succeeds(tmp_path: Path):
    """Verify managed workspace ownership succeeds when valid marker is present."""
    ws_dir = tmp_path / "managed_ws"
    ws_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=ws_dir, capture_output=True, check=True)

    write_managed_workspace_marker(ws_dir, "test-org/test-repo")
    assert verify_managed_workspace_ownership(ws_dir, "test-org/test-repo") is True
    # Fails if repository name does not match
    assert verify_managed_workspace_ownership(ws_dir, "other-org/other-repo") is False


def test_symlink_or_traversal_cannot_bypass_ownership_guard(tmp_path: Path):
    """Verify symlinks or path traversal in ownership marker are strictly rejected."""
    ws_dir = tmp_path / "fake_ws"
    ws_dir.mkdir()

    # Target directory with real marker
    real_ws = tmp_path / "real_ws"
    real_ws.mkdir()
    write_managed_workspace_marker(real_ws, "test-org/test-repo")

    # Symlink marker from fake_ws to real_ws
    fake_marker = ws_dir / MARKER_FILENAME
    try:
        os.symlink(real_ws / MARKER_FILENAME, fake_marker)
        # Must fail because marker is a symlink and recorded path does not match ws_dir
        assert verify_managed_workspace_ownership(ws_dir, "test-org/test-repo") is False
    except OSError:
        # On Windows without symlink privileges, test path mismatch directly
        marker_data = json.loads((real_ws / MARKER_FILENAME).read_text(encoding="utf-8"))
        marker_data["workspace_path"] = str(real_ws)
        (ws_dir / MARKER_FILENAME).write_text(json.dumps(marker_data), encoding="utf-8")
        assert verify_managed_workspace_ownership(ws_dir, "test-org/test-repo") is False


def test_safe_task_cleanup_preserves_unrelated_untracked_files(tmp_path: Path):
    """Verify cleanup only reverts the task's target_files and preserves untracked files."""
    repo_dir = tmp_path / "managed_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=repo_dir, capture_output=True, check=True)

    tracked_file = repo_dir / "README.md"
    tracked_file.write_text("# Original README\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_dir, capture_output=True, check=True)

    # Mark as managed
    write_managed_workspace_marker(repo_dir, "test-org/test-repo")

    # Task modifies README.md and someone creates an untracked unrelated file
    tracked_file.write_text("# Modified README by Task\n", encoding="utf-8")
    unrelated_file = repo_dir / "unrelated_user_notes.txt"
    unrelated_file.write_text("Do not delete these notes!\n", encoding="utf-8")

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])
    config = DailyGreenConfig(enabled=True, dry_run=True, execution=ExecutionConfig(max_workers=1))
    engine = ExecutionEngine(
        repo_config=repo_cfg,
        config=config,
        github_client=MockGitHubClient(),
        state_mgr=StateManager(state_dir=tmp_path / "state"),
        ai_adapter=MockAIAdapter(),
        workspace_path=repo_dir,
    )

    task = Task(
        id="t1", repo="test-org/test-repo", title="Title", description="Desc",
        rationale="Rat", acceptance_criteria=["AC"], risk_level=RiskLevel.LOW,
        validation_strategy="strat", source=TaskSource.DETERMINISTIC, target_files=["README.md"]
    )

    # Execute safe cleanup
    engine._safe_task_cleanup(task)

    # Tracked file must be restored to original commit
    assert tracked_file.read_text(encoding="utf-8") == "# Original README\n"
    # Unrelated untracked file must NOT be deleted by blanket clean
    assert unrelated_file.exists()
    assert unrelated_file.read_text(encoding="utf-8") == "Do not delete these notes!\n"


# ---------------------------------------------------------------------------
# 4. Sealed Patch Correctness & Stale Base Rejection Tests (DG3-08)
# ---------------------------------------------------------------------------

def test_stale_base_sha_rejected_in_delivery(tmp_path: Path):
    """Verify delivery strictly rejects sealed artifacts with mismatched base commit SHA."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=repo_dir, capture_output=True, check=True)

    (repo_dir / "README.md").write_text("# Hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_dir, capture_output=True, check=True)

    head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    task = Task(
        id="t1", repo="test-org/test-repo", title="Title", description="Desc",
        rationale="Rat", acceptance_criteria=["AC"], risk_level=RiskLevel.LOW,
        validation_strategy="strat", source=TaskSource.DETERMINISTIC, target_files=["README.md"]
    )

    # Sealed artifact with an outdated base_commit_sha
    stale_base_sha = "0000000000000000000000000000000000000000"
    qg = QualityGateResult(
        passed=True,
        reason="OK",
        base_commit_sha=stale_base_sha,
        tree_sha="1111111111111111111111111111111111111111",
        patch_hash=compute_patch_hash("diff"),
        changed_files=["README.md"],
    )

    repo_cfg = RepoConfig(name="test-org/test-repo", allowed_paths=["README.md"])

    with pytest.raises(DeliveryError) as exc_info:
        deliver_pull_request(
            workspace_dir=repo_dir,
            task=task,
            quality_gate=qg,
            diff_text="diff",
            repo_config=repo_cfg,
            policy=SecurityPolicyConfig(),
            github_client=MockGitHubClient(),
            dry_run=True,
        )
    assert "Base commit mismatch" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. State Isolation Regression Test (Requirement 4)
# ---------------------------------------------------------------------------

def test_regression_real_state_file_never_modified_by_default(tmp_path: Path, monkeypatch):
    """
    Regression test: verify that StateManager and DailyGreen operations never fall back
    to or modify the real workspace root .dailygreen/state.json.
    """
    real_state = Path(".dailygreen") / "state.json"
    initial_content = real_state.read_text(encoding="utf-8") if real_state.exists() else None

    # Explicit isolated directory
    isolated_dir = tmp_path / "isolated_state"
    state_mgr = StateManager(state_dir=isolated_dir)
    state_mgr.record_task_completion("test-org/test-repo", "isolated-task")

    assert (isolated_dir / "state.json").exists()

    # Verify real state file content remains completely unchanged
    if real_state.exists():
        assert real_state.read_text(encoding="utf-8") == initial_content
