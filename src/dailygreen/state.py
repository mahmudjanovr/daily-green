"""State management, idempotency tracking, and circuit breaker for DailyGreen."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def is_process_alive(pid: int) -> bool:
    """Check if process with given PID is currently active in the OS."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h_proc)
        return exit_code.value == STILL_ACTIVE
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


class StateManager:
    """Manages persistent state across DailyGreen runs to guarantee idempotency."""

    def __init__(self, state_dir: str | Path = ".dailygreen", failure_threshold: int = 3):
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.failure_threshold = failure_threshold
        self._state: dict[str, Any] = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        default_state = {
            "completed_tasks": {},
            "consecutive_failures": {},
            "circuit_tripped": {},
            "active_leases": {},
            "runs": [],
        }
        if not self.state_file.exists():
            return default_state
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if not isinstance(loaded, dict):
                    return default_state
                # Validate and repair fields
                for k, default_val in default_state.items():
                    if k not in loaded or type(loaded[k]) is not type(default_val):
                        loaded[k] = default_val

                # Expire stale leases older than 30 minutes
                now = time.time()
                active = dict(loaded.get("active_leases", {}))
                for repo_k, lease in list(active.items()):
                    if not isinstance(lease, dict) or (now - lease.get("timestamp", 0) > 1800):
                        active.pop(repo_k, None)
                loaded["active_leases"] = active
                return loaded
        except Exception:
            # If corrupted, start with clean state to prevent crash
            return default_state

    def acquire_run_lease(self, repo: str, run_id: str, lease_timeout_seconds: int = 1800) -> bool:
        """
        Attempt to acquire an active execution lease for a repository.
        Prevents concurrent runs from colliding or duplicating work.
        Reclaims orphaned leases if holding process has terminated.
        """
        repo_key = repo.lower()
        now = time.time()
        if "active_leases" not in self._state:
            self._state["active_leases"] = {}

        current_lease = self._state["active_leases"].get(repo_key)
        if current_lease and isinstance(current_lease, dict):
            # Check if lease is active and held by a DIFFERENT run
            lease_time = current_lease.get("timestamp", 0)
            holding_run = current_lease.get("run_id")
            holding_pid = current_lease.get("pid")
            if (now - lease_time < lease_timeout_seconds) and holding_run != run_id:
                # If holding PID is known and the holding process is dead, safely reclaim orphaned lease
                if holding_pid and not is_process_alive(holding_pid):
                    pass
                else:
                    # Active lease held by another living run
                    return False

        # Acquire or renew lease
        self._state["active_leases"][repo_key] = {
            "run_id": run_id,
            "pid": os.getpid(),
            "timestamp": now,
            "iso": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
        return True

    def release_run_lease(self, repo: str, run_id: str) -> None:
        """Release the active execution lease for a repository."""
        repo_key = repo.lower()
        if "active_leases" in self._state:
            current_lease = self._state["active_leases"].get(repo_key)
            if current_lease and current_lease.get("run_id") == run_id:
                self._state["active_leases"].pop(repo_key, None)
                self._save_state()

    def _save_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp_file = self.state_dir / f"state_{int(time.time() * 1000)}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)
        temp_file.replace(self.state_file)

    def get_idempotency_key(self, repo: str, task_id: str, date_str: Optional[str] = None) -> str:
        d = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{d}:{repo.lower()}:{task_id}"

    def is_task_already_done(self, repo: str, task_id: str, date_str: Optional[str] = None) -> bool:
        key = self.get_idempotency_key(repo, task_id, date_str)
        return key in self._state.get("completed_tasks", {})

    def record_task_completion(
        self,
        repo: str,
        task_id: str,
        details: Optional[dict[str, Any]] = None,
        date_str: Optional[str] = None,
    ) -> None:
        key = self.get_idempotency_key(repo, task_id, date_str)
        if "completed_tasks" not in self._state:
            self._state["completed_tasks"] = {}
        self._state["completed_tasks"][key] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "repo": repo,
            "task_id": task_id,
            "details": details or {},
        }
        # Reset consecutive failures on success
        self.reset_failure_count(repo)
        self._save_state()

    def is_circuit_tripped(self, repo: str) -> bool:
        """Check if circuit breaker has tripped for this repository."""
        tripped = self._state.get("circuit_tripped", {}).get(repo.lower(), False)
        failures = self._state.get("consecutive_failures", {}).get(repo.lower(), 0)
        return tripped or (failures >= self.failure_threshold)

    def record_failure(self, repo: str, error_message: str) -> None:
        """Record a run failure, increment failure counter, and trip circuit breaker if threshold reached."""
        repo_key = repo.lower()
        if "consecutive_failures" not in self._state:
            self._state["consecutive_failures"] = {}
        if "circuit_tripped" not in self._state:
            self._state["circuit_tripped"] = {}

        current = self._state["consecutive_failures"].get(repo_key, 0) + 1
        self._state["consecutive_failures"][repo_key] = current

        if current >= self.failure_threshold:
            self._state["circuit_tripped"][repo_key] = True

        self._save_state()

    def reset_failure_count(self, repo: str) -> None:
        """Reset consecutive failures for a repository after a successful run or manual reset."""
        repo_key = repo.lower()
        if "consecutive_failures" in self._state:
            self._state["consecutive_failures"][repo_key] = 0
        if "circuit_tripped" in self._state:
            self._state["circuit_tripped"][repo_key] = False
        self._save_state()

    def record_run(self, run_report_dict: dict[str, Any]) -> None:
        """Record run report in history."""
        if "runs" not in self._state:
            self._state["runs"] = []
        self._state["runs"].append(run_report_dict)
        # Keep last 50 runs
        if len(self._state["runs"]) > 50:
            self._state["runs"] = self._state["runs"][-50:]
        self._save_state()
