"""Autonomous multi-task execution queue with dependency resolution, deduplication, and lifecycle tracking."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dailygreen.models import (
    ExecutionRecord,
    FailureClassification,
    QueueSummary,
    Task,
    TaskSource,
    TaskStatus,
)
from dailygreen.state import StateManager


SOURCE_PRIORITY: dict[TaskSource, int] = {
    TaskSource.ISSUE: 1,
    TaskSource.BACKLOG: 2,
    TaskSource.DETERMINISTIC: 3,
    TaskSource.AI: 4,
}


class _RecoverDispatcher:
    def __get__(self, instance, owner):
        if instance is None:
            def _class_recover(queue_file: str | Path, max_tasks: int = 1, state_mgr: Optional[StateManager] = None) -> "TaskQueue":
                return owner.recover_from_file(queue_file, max_tasks=max_tasks, state_mgr=state_mgr)
            return _class_recover
        else:
            def _instance_recover(state_mgr: Optional[StateManager] = None) -> int:
                return instance._recover_internal(state_mgr)
            return _instance_recover


class TaskQueue:
    """
    Persistent, dependency-aware multi-task execution queue for DailyGreen.
    Enforces deterministic ordering, dependency topological resolution, cycle detection,
    and safe recovery of interrupted tasks.
    """

    recover = _RecoverDispatcher()

    def __init__(
        self,
        repo: str,
        max_tasks: int = 1,
        state_dir: str | Path = ".dailygreen",
        state_file: Optional[str | Path] = None,
    ):
        self.repo = repo
        self.max_tasks = max(1, max_tasks)
        if state_file:
            self.queue_file = Path(state_file)
            self.state_dir = self.queue_file.parent
        else:
            self.state_dir = Path(state_dir)
            self.queue_file = self.state_dir / f"queue_{self._sanitize_repo(repo)}.json"
        self._tasks: dict[str, Task] = {}  # task_id -> Task
        self.total_discovered: int = 0
        self.total_evaluated: int = 0
        self.cycle_detected: bool = False
        self.recovered_interrupted_count: int = 0

    @staticmethod
    def _sanitize_repo(repo: str) -> str:
        return repo.lower().replace("/", "_").replace("\\", "_")

    def __len__(self) -> int:
        return len(self._tasks)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def enqueue(self, task: Task) -> bool:
        """
        Enqueue a candidate task.
        Deduplicates by stable task.id and repository (DG3-03).
        Enforces max_tasks capacity limit across active and queued tasks.
        Returns True if enqueued, False if duplicate or capacity exceeded.
        """
        if task.id in self._tasks:
            # Duplicate task in active queue
            return False

        active_states = {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRY_SCHEDULED}
        active_count = sum(1 for t in self._tasks.values() if t.status in active_states)
        if active_count >= self.max_tasks:
            # Capacity reached
            return False

        task.status = TaskStatus.QUEUED
        self._tasks[task.id] = task
        self.persist()
        return True

    def enqueue_batch(self, tasks: list[Task]) -> int:
        """Enqueue multiple tasks respecting capacity and deduplication. Returns count added."""
        added = 0
        for t in tasks:
            if self.enqueue(t):
                added += 1
            if len(self._tasks) >= self.max_tasks:
                break
        return added

    def resolve_dependencies(self, state_mgr: Optional[StateManager] = None) -> None:
        """
        Inspect task dependency graph:
        1. Detect dependency cycles using DFS cycle detection.
        2. Mark tasks involved in cycles as FAILED safely.
        3. Cascade skips: mark tasks depending on failed/skipped tasks as SKIPPED.
        """
        # Build dependency graph
        # graph[u] = list of tasks that u depends on
        graph: dict[str, list[str]] = {tid: list(task.dependencies) for tid, task in self._tasks.items()}

        # 1. Cycle Detection (WHITE=0, GRAY=1, BLACK=2)
        color: dict[str, int] = {tid: 0 for tid in self._tasks}
        cycle_tasks: set[str] = set()

        def dfs(node: str, path: list[str]) -> bool:
            color[node] = 1  # visiting
            for dep in graph.get(node, []):
                if dep in self._tasks:
                    if color.get(dep, 0) == 1:
                        # Cycle found!
                        cycle_tasks.add(node)
                        cycle_tasks.add(dep)
                        for p in path:
                            if p in graph.get(dep, []) or dep in graph.get(p, []):
                                cycle_tasks.add(p)
                        return True
                    elif color.get(dep, 0) == 0:
                        if dfs(dep, path + [dep]):
                            cycle_tasks.add(node)
                            return True
            color[node] = 2  # visited
            return False

        for tid in list(self._tasks.keys()):
            if color[tid] == 0:
                if dfs(tid, [tid]):
                    self.cycle_detected = True

        for tid in cycle_tasks:
            task = self._tasks[tid]
            if task.status in (TaskStatus.QUEUED, TaskStatus.DISCOVERED, TaskStatus.EVALUATED):
                task.status = TaskStatus.SKIPPED
                task.last_failure_reason = f"Dependency cycle detected involving task '{tid}'"
                task.last_failure_transient = False

        # 2. Check for missing or failed prerequisites
        for tid, task in self._tasks.items():
            if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                continue

            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                dep_done = False
                if state_mgr and state_mgr.is_task_already_done(self.repo, dep_id):
                    dep_done = True
                elif dep_task and dep_task.status == TaskStatus.COMPLETED:
                    dep_done = True

                if not dep_done:
                    if dep_task and dep_task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                        task.status = TaskStatus.SKIPPED
                        task.last_failure_reason = f"Prerequisite task '{dep_id}' was {dep_task.status.value}"
                        break
                    elif not dep_task and not dep_done:
                        task.status = TaskStatus.SKIPPED
                        task.last_failure_reason = f"Missing prerequisite task '{dep_id}' not found in queue or completed state"
                        break

        self.persist()

    def get_ready_tasks(
        self,
        running_tasks: Optional[list[Task]] = None,
        state_mgr: Optional[StateManager] = None,
    ) -> list[Task]:
        """
        Return tasks ready for execution:
        - In QUEUED or RETRY_SCHEDULED state.
        - All dependencies are COMPLETED (either in active queue or in state_mgr) (DG3-05).
        - If RETRY_SCHEDULED, next_retry_time has elapsed.
        - target_files do not overlap with any currently running task.
        - Deterministically sorted by source hierarchy, then stable task.id.
        """
        running = running_tasks or []
        running_files: set[str] = set()
        for r in running:
            running_files.update(r.target_files)

        now = time.time()
        ready: list[Task] = []

        for task in self._tasks.values():
            if task.status not in (TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED):
                continue

            # Check retry delay
            if task.status == TaskStatus.RETRY_SCHEDULED:
                if task.next_retry_time and now < task.next_retry_time:
                    continue

            # Check dependencies completed (DG3-05)
            deps_met = True
            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                dep_done = False
                if dep_task and dep_task.status == TaskStatus.COMPLETED:
                    dep_done = True
                elif state_mgr and state_mgr.is_task_already_done(self.repo, dep_id):
                    dep_done = True

                if not dep_done:
                    deps_met = False
                    break
            if not deps_met:
                continue

            # Prevent file collision with active tasks
            if set(task.target_files) & running_files:
                continue

            ready.append(task)

        # Deterministic sorting: priority (Issue > Backlog > Deterministic > AI), then task.id
        ready.sort(key=lambda t: (SOURCE_PRIORITY.get(t.source, 99), t.id))
        return ready

    def mark_running(self, task_id: str, worker_id: str) -> Task:
        task = self._tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.worker_id = worker_id
        task.attempt_count += 1
        task.started_at = datetime.now(timezone.utc).isoformat()
        self.persist()
        return task

    def mark_completed(self, task_id: str, duration: float = 0.0) -> Task:
        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.duration_seconds = round(duration, 2)
        task.last_failure_reason = None
        task.last_failure_transient = False
        task.next_retry_time = None
        self.persist()
        return task

    def mark_failed(
        self,
        task_id: str,
        reason: str,
        is_transient: bool = False,
        duration: float = 0.0,
    ) -> Task:
        task = self._tasks[task_id]
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.duration_seconds = round(duration, 2)
        task.last_failure_reason = reason
        task.last_failure_transient = is_transient
        task.next_retry_time = None
        self.persist()
        return task

    def mark_skipped(self, task_id: str, reason: str) -> Task:
        task = self._tasks[task_id]
        task.status = TaskStatus.SKIPPED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.last_failure_reason = reason
        self.persist()
        return task

    def schedule_retry(
        self,
        task_id: str,
        reason: str,
        backoff_seconds: float,
    ) -> Task:
        task = self._tasks[task_id]
        task.status = TaskStatus.RETRY_SCHEDULED
        task.last_failure_reason = reason
        task.last_failure_transient = True
        task.next_retry_time = time.time() + backoff_seconds
        self.persist()
        return task

    def is_finished(self) -> bool:
        """Returns True if no tasks are QUEUED, RUNNING, or RETRY_SCHEDULED."""
        active_states = {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRY_SCHEDULED}
        return not any(t.status in active_states for t in self._tasks.values())

    def _recover_internal(self, state_mgr: Optional[StateManager] = None) -> int:
        """
        Recover interrupted tasks left in RUNNING state from a previous crashed run.
        If task was already completed in StateManager, mark COMPLETED.
        Otherwise, if attempts < max_retries, transition to QUEUED to retry safely;
        if exhausted, mark FAILED.
        Returns count of recovered tasks.
        """
        if not self.queue_file.exists():
            return 0

        recovered = 0
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_tasks = data.get("tasks", [])
            for item in loaded_tasks:
                task = Task(**item)
                if state_mgr and state_mgr.is_task_already_done(self.repo, task.id):
                    task.status = TaskStatus.COMPLETED
                elif task.status == TaskStatus.RUNNING:
                    # Interrupted task detected!
                    if task.attempt_count < task.max_retries:
                        task.status = TaskStatus.QUEUED
                        task.last_failure_reason = "Interrupted run: task recovered and requeued safely"
                    else:
                        task.status = TaskStatus.FAILED
                        task.last_failure_reason = "Interrupted run: maximum retry attempts exhausted"
                    recovered += 1

                self._tasks[task.id] = task

            self.recovered_interrupted_count = recovered
            if recovered > 0:
                self.persist()
        except Exception:
            pass

        return recovered

    @classmethod
    def recover_from_file(
        cls,
        queue_file: Path | str,
        max_tasks: int = 1,
        state_mgr: Optional[StateManager] = None,
    ) -> "TaskQueue":
        """Recover a queue instance directly from a persisted state file."""
        q_path = Path(queue_file)
        repo = "unknown"
        if q_path.exists():
            try:
                with open(q_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    repo = data.get("repo", "unknown")
            except Exception:
                pass
        q = cls(repo=repo, max_tasks=max_tasks, state_file=q_path)
        q._recover_internal(state_mgr=state_mgr)
        return q

    def persist(self) -> None:
        """
        Persist queue state atomically to disk (DG3-06).
        Serializes state first, writes to a temporary file in state_dir,
        flushes/syncs, closes, and atomically replaces queue_file.
        Preserves previous valid queue state if writing or serialization fails.
        """
        temp_file: Optional[Path] = None
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "repo": self.repo,
                "max_tasks": self.max_tasks,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "tasks": [t.model_dump() for t in self._tasks.values()],
            }
            # 1. Pre-serialize to string to ensure payload is valid before touching disk
            serialized = json.dumps(payload, indent=2)

            # 2. Write to temporary file in the same directory
            temp_file = self.state_dir / f"{self.queue_file.name}.tmp.{os.getpid()}_{time.time_ns()}"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            # 3. Atomic replacement
            os.replace(temp_file, self.queue_file)
            temp_file = None
        except Exception:
            pass
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink(missing_ok=True)
                except Exception:
                    pass

    def summary(self) -> QueueSummary:
        """Produce structured monitoring summary of queue execution."""
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        skipped = sum(1 for t in self._tasks.values() if t.status == TaskStatus.SKIPPED)
        retried = sum(1 for t in self._tasks.values() if t.attempt_count > 1 or t.status == TaskStatus.RETRY_SCHEDULED)

        records: list[ExecutionRecord] = []
        for t in self._tasks.values():
            records.append(
                ExecutionRecord(
                    task_id=t.id,
                    repo=t.repo,
                    status=t.status,
                    worker_id=t.worker_id,
                    attempt_count=max(1, t.attempt_count),
                    duration_seconds=t.duration_seconds,
                    started_at=t.started_at,
                    completed_at=t.completed_at,
                    error_message=t.last_failure_reason,
                    is_transient=t.last_failure_transient,
                    target_files=list(t.target_files),
                    validation_passed=(t.status == TaskStatus.COMPLETED),
                )
            )

        return QueueSummary(
            total_discovered=self.total_discovered,
            total_evaluated=self.total_evaluated,
            total_queued=len(self._tasks),
            completed_count=completed,
            failed_count=failed,
            skipped_count=skipped,
            retried_count=retried,
            cycle_detected=self.cycle_detected,
            recovered_interrupted_count=self.recovered_interrupted_count,
            records=records,
        )
