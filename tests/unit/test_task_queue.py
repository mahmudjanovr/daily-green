"""Unit tests for Phase 3 TaskQueue: lifecycle, deduplication, dependencies, cycles, and persistence."""

from pathlib import Path
from dailygreen.models import RiskLevel, Task, TaskCategory, TaskSource, TaskStatus
from dailygreen.state import StateManager
from dailygreen.task_queue import TaskQueue


def _make_task(task_id: str, deps: list[str] = None, source: TaskSource = TaskSource.DETERMINISTIC, target_files: list[str] = None) -> Task:
    return Task(
        id=task_id,
        repo="test-owner/test-repo",
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        rationale=f"Rationale for {task_id}",
        acceptance_criteria=[f"Verify {task_id}"],
        risk_level=RiskLevel.LOW,
        validation_strategy="verify",
        source=source,
        category=TaskCategory.MAINTENANCE,
        target_files=target_files or [f"{task_id}.md"],
        dependencies=deps or [],
    )


def test_queue_enqueue_and_capacity_bounding():
    """Verify task queue bounds capacity to max_tasks."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=2)
    t1 = _make_task("task-1")
    t2 = _make_task("task-2")
    t3 = _make_task("task-3")

    assert queue.enqueue(t1) is True
    assert queue.enqueue(t2) is True
    assert queue.enqueue(t3) is False  # Capacity reached
    assert len(queue) == 2


def test_queue_deduplication():
    """Verify task queue deduplicates tasks with the same ID."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    t1 = _make_task("task-1")
    t1_dup = _make_task("task-1")

    assert queue.enqueue(t1) is True
    assert queue.enqueue(t1_dup) is False  # Duplicate ID
    assert len(queue) == 1


def test_queue_deterministic_priority_ordering():
    """Verify ready tasks are ordered by deterministic priority: ISSUE > BACKLOG > DETERMINISTIC > AI."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=10)
    t_ai = _make_task("task-ai", source=TaskSource.AI_SUGGESTED)
    t_det = _make_task("task-det", source=TaskSource.DETERMINISTIC)
    t_issue = _make_task("task-issue", source=TaskSource.ISSUE)
    t_backlog = _make_task("task-backlog", source=TaskSource.BACKLOG)

    queue.enqueue(t_ai)
    queue.enqueue(t_det)
    queue.enqueue(t_issue)
    queue.enqueue(t_backlog)

    queue.resolve_dependencies()
    ready = queue.get_ready_tasks()
    ready_ids = [t.id for t in ready]

    assert ready_ids == ["task-issue", "task-backlog", "task-det", "task-ai"]


def test_queue_dependencies_ordering():
    """Verify task with uncompleted dependencies is not ready until dependencies complete."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    t1 = _make_task("task-1")
    t2 = _make_task("task-2", deps=["task-1"])

    queue.enqueue(t1)
    queue.enqueue(t2)

    queue.resolve_dependencies()
    ready = queue.get_ready_tasks()
    assert [t.id for t in ready] == ["task-1"]

    # Mark task-1 as completed
    queue.mark_running("task-1", worker_id="worker-1")
    queue.mark_completed("task-1", duration=1.5)

    queue.resolve_dependencies()
    ready_after = queue.get_ready_tasks()
    assert [t.id for t in ready_after] == ["task-2"]


def test_queue_cycle_detection():
    """Verify dependency cycle detection marks participating tasks as SKIPPED and sets cycle_detected flag."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    t1 = _make_task("task-1", deps=["task-2"])
    t2 = _make_task("task-2", deps=["task-1"])
    t3 = _make_task("task-3")

    queue.enqueue(t1)
    queue.enqueue(t2)
    queue.enqueue(t3)

    queue.resolve_dependencies()

    task1 = queue.get_task("task-1")
    task2 = queue.get_task("task-2")
    task3 = queue.get_task("task-3")

    assert task1.status == TaskStatus.SKIPPED
    assert "Dependency cycle detected" in (task1.last_failure_reason or "")
    assert task2.status == TaskStatus.SKIPPED
    assert task3.status == TaskStatus.QUEUED

    ready = queue.get_ready_tasks()
    assert [t.id for t in ready] == ["task-3"]

    summary = queue.summary()
    assert summary.cycle_detected is True
    assert summary.skipped_count == 2


def test_queue_cascading_skips():
    """Verify task depending on a failed task is automatically skipped."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    t1 = _make_task("task-1")
    t2 = _make_task("task-2", deps=["task-1"])

    queue.enqueue(t1)
    queue.enqueue(t2)

    queue.resolve_dependencies()
    queue.mark_running("task-1", worker_id="worker-1")
    queue.mark_failed("task-1", "Permanent failure in task 1", is_transient=False)

    queue.resolve_dependencies()

    task2 = queue.get_task("task-2")
    assert task2.status == TaskStatus.SKIPPED
    assert "prerequisite" in (task2.last_failure_reason or "").lower()

    summary = queue.summary()
    assert summary.failed_count == 1
    assert summary.skipped_count == 1


def test_queue_overlapping_files_conflict():
    """Verify get_ready_tasks prevents concurrent execution on overlapping target files."""
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    t1 = _make_task("task-1", target_files=["docs/guide.md", "README.md"])
    t2 = _make_task("task-2", target_files=["README.md"])
    t3 = _make_task("task-3", target_files=["docs/faq.md"])

    queue.enqueue(t1)
    queue.enqueue(t2)
    queue.enqueue(t3)

    queue.resolve_dependencies()

    # Suppose task-1 is currently running
    queue.mark_running("task-1", worker_id="worker-1")
    running_t1 = queue.get_task("task-1")

    ready = queue.get_ready_tasks(running_tasks=[running_t1])
    # task-2 touches README.md (conflict), so only task-3 should be ready
    assert [t.id for t in ready] == ["task-3"]


def test_queue_persistence_and_recovery(tmp_path: Path):
    """Verify queue persists state to disk and recovers interrupted RUNNING tasks safely."""
    queue_file = tmp_path / "queue_state.json"
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5, state_file=queue_file)

    t1 = _make_task("task-1")
    t2 = _make_task("task-2")
    queue.enqueue(t1)
    queue.enqueue(t2)

    queue.resolve_dependencies()
    queue.mark_running("task-1", worker_id="worker-1")
    queue.mark_completed("task-1", duration=2.0)
    queue.mark_running("task-2", worker_id="worker-1")

    # Simulate interruption while task-2 is RUNNING
    queue.persist()
    assert queue_file.exists()

    # Recover in a new queue instance
    recovered_queue = TaskQueue.recover(queue_file, max_tasks=5)
    assert recovered_queue is not None
    assert len(recovered_queue) == 2

    rec_t1 = recovered_queue.get_task("task-1")
    rec_t2 = recovered_queue.get_task("task-2")

    # Completed task remains completed
    assert rec_t1.status == TaskStatus.COMPLETED
    # Interrupted running task is reset to QUEUED for safe retry
    assert rec_t2.status == TaskStatus.QUEUED
    assert "task recovered" in (rec_t2.last_failure_reason or "").lower()


def test_historical_dependency_resolution(tmp_path: Path):
    """Verify get_ready_tasks recognizes historical completions from StateManager (DG3-05)."""
    state_dir = tmp_path / "state"
    state_mgr = StateManager(state_dir=state_dir)

    # Record historical task-0 as already completed in previous run
    state_mgr.record_task_completion("test-owner/test-repo", "task-0", details={"branch": "main"})

    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5)
    # Task 1 depends on historically completed task-0
    t1 = _make_task("task-1", deps=["task-0"])
    # Task 2 depends on task-1 (transitive dependency)
    t2 = _make_task("task-2", deps=["task-1"])
    # Task 3 depends on non-existent task-999
    t3 = _make_task("task-3", deps=["task-999"])

    queue.enqueue(t1)
    queue.enqueue(t2)
    queue.enqueue(t3)

    queue.resolve_dependencies(state_mgr=state_mgr)

    # Task 3 should be skipped due to missing prerequisite
    assert queue.get_task("task-3").status == TaskStatus.SKIPPED

    # Task 1 should be ready because task-0 was done in state_mgr!
    ready = queue.get_ready_tasks(state_mgr=state_mgr)
    assert [t.id for t in ready] == ["task-1"]

    # Now complete task 1
    queue.mark_running("task-1", worker_id="worker-1")
    queue.mark_completed("task-1", duration=1.0)
    queue.resolve_dependencies(state_mgr=state_mgr)

    # Now task 2 should be ready (transitive dependency satisfied)
    ready_after = queue.get_ready_tasks(state_mgr=state_mgr)
    assert [t.id for t in ready_after] == ["task-2"]


def test_atomic_queue_persistence_failure_resilience(tmp_path: Path):
    """Verify persistence writes atomically via temp file and preserves state on failure (DG3-06)."""
    import os
    from unittest.mock import patch

    queue_file = tmp_path / "queue_state.json"
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5, state_file=queue_file)

    t1 = _make_task("task-1")
    queue.enqueue(t1)
    assert queue_file.exists()

    valid_content = queue_file.read_text(encoding="utf-8")
    assert "task-1" in valid_content

    # Simulate write failure during atomic persist (e.g. permission or disk error during write)
    t2 = _make_task("task-2")
    queue._tasks["task-2"] = t2

    def mock_bad_replace(src, dst):
        raise OSError("Simulated disk error during replace")

    with patch("os.replace", side_effect=mock_bad_replace):
        queue.persist()

    # Verify previous queue file was NOT destroyed or truncated
    assert queue_file.exists()
    assert queue_file.read_text(encoding="utf-8") == valid_content

    # Verify any leftover temp files were cleaned up
    tmp_files = list(tmp_path.glob("*.tmp.*"))
    assert len(tmp_files) == 0


def test_queue_recovery_idempotency_and_preservation(tmp_path: Path):
    """Verify recovery is strictly idempotent and preserves attempt counts and state (DG3-03)."""
    queue_file = tmp_path / "queue_state.json"
    queue = TaskQueue(repo="test-owner/test-repo", max_tasks=5, state_file=queue_file)

    t1 = _make_task("task-1")
    t2 = _make_task("task-2")
    queue.enqueue(t1)
    queue.enqueue(t2)

    queue.mark_running("task-1", worker_id="worker-1")
    queue.mark_completed("task-1", duration=2.5)

    queue.mark_running("task-2", worker_id="worker-1")
    t2_running = queue.get_task("task-2")
    t2_running.attempt_count = 1
    t2_running.next_retry_time = 1234567.0
    queue.persist()

    # First recovery
    recovered_queue = TaskQueue.recover(queue_file, max_tasks=5)
    assert len(recovered_queue) == 2
    rec_t1 = recovered_queue.get_task("task-1")
    rec_t2 = recovered_queue.get_task("task-2")

    assert rec_t1.status == TaskStatus.COMPLETED
    assert rec_t2.status == TaskStatus.QUEUED
    assert rec_t2.attempt_count == 1
    assert rec_t2.next_retry_time == 1234567.0

    # Second recovery (idempotent call)
    recovered_queue.recover()
    rec_t1_again = recovered_queue.get_task("task-1")
    rec_t2_again = recovered_queue.get_task("task-2")

    assert rec_t1_again.status == TaskStatus.COMPLETED
    assert rec_t2_again.status == TaskStatus.QUEUED
    assert rec_t2_again.attempt_count == 1
    assert rec_t2_again.next_retry_time == 1234567.0
