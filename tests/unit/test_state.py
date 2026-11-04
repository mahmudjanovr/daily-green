"""Unit tests for state management, idempotency tracking, and circuit breaker."""

from pathlib import Path
from dailygreen.state import StateManager


def test_state_idempotency(tmp_path: Path):
    state_mgr = StateManager(state_dir=tmp_path, failure_threshold=3)

    assert state_mgr.is_task_already_done("org/repo", "task-1", date_str="2026-10-29") is False

    state_mgr.record_task_completion("org/repo", "task-1", date_str="2026-10-29")

    assert state_mgr.is_task_already_done("org/repo", "task-1", date_str="2026-10-29") is True
    # Different date is not considered done
    assert state_mgr.is_task_already_done("org/repo", "task-1", date_str="2026-10-30") is False


def test_circuit_breaker(tmp_path: Path):
    state_mgr = StateManager(state_dir=tmp_path, failure_threshold=3)

    assert state_mgr.is_circuit_tripped("org/repo") is False

    # Failures 1 and 2: not tripped yet
    state_mgr.record_failure("org/repo", "fail 1")
    assert state_mgr.is_circuit_tripped("org/repo") is False

    state_mgr.record_failure("org/repo", "fail 2")
    assert state_mgr.is_circuit_tripped("org/repo") is False

    # Failure 3: trips circuit breaker
    state_mgr.record_failure("org/repo", "fail 3")
    assert state_mgr.is_circuit_tripped("org/repo") is True

    # Reset
    state_mgr.reset_failure_count("org/repo")
    assert state_mgr.is_circuit_tripped("org/repo") is False


def test_corrupted_state_recovery(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{invalid json", encoding="utf-8")

    state_mgr = StateManager(state_dir=tmp_path)
    # Should not crash and should initialize clean state
    assert state_mgr.is_task_already_done("org/repo", "task-x") is False
