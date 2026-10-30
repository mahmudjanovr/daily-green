"""Unit test for Windows and cross-platform process tree termination upon timeout."""

import os
import sys
import time
from pathlib import Path
import pytest
from dailygreen.worker import run_command_in_workspace


def is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is still alive."""
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


def test_process_tree_termination_on_timeout(tmp_path: Path):
    """
    Verify that when run_command_in_workspace times out:
    1. The parent process is terminated.
    2. Any descendant child processes (e.g. Node under npm) are also terminated.
    3. No orphaned background processes linger.
    """
    child_script = tmp_path / "child.py"
    parent_script = tmp_path / "parent.py"
    child_pid_file = tmp_path / "child_pid.txt"
    parent_pid_file = tmp_path / "parent_pid.txt"

    # Child writes its PID and sleeps
    child_script.write_text(
        f"import time, os\n"
        f"with open(r'{child_pid_file}', 'w') as f:\n"
        f"    f.write(str(os.getpid()))\n"
        f"time.sleep(60)\n",
        encoding="utf-8",
    )

    # Parent writes its PID, spawns child, waits until child PID file exists, then sleeps
    parent_script.write_text(
        f"import subprocess, time, sys, os\n"
        f"with open(r'{parent_pid_file}', 'w') as f:\n"
        f"    f.write(str(os.getpid()))\n"
        f"child = subprocess.Popen([sys.executable, r'{child_script}'])\n"
        f"for _ in range(50):\n"
        f"    if os.path.exists(r'{child_pid_file}'):\n"
        f"        break\n"
        f"    time.sleep(0.05)\n"
        f"time.sleep(60)\n",
        encoding="utf-8",
    )

    # Run with a 3-second timeout
    result = run_command_in_workspace(
        [sys.executable, str(parent_script)],
        workspace_dir=tmp_path,
        timeout_seconds=3,
    )

    assert result.timed_out is True
    assert result.exit_code == -1
    assert "timed out after 3s" in result.stderr

    # Both parent and child must have written their PIDs
    assert parent_pid_file.exists()
    assert child_pid_file.exists()

    parent_pid = int(parent_pid_file.read_text().strip())
    child_pid = int(child_pid_file.read_text().strip())

    # Allow up to 3 seconds for OS cleanup
    deadline = time.time() + 3
    while (is_pid_alive(parent_pid) or is_pid_alive(child_pid)) and time.time() < deadline:
        time.sleep(0.2)

    # Assert BOTH parent and child processes are completely terminated
    assert not is_pid_alive(parent_pid), f"Parent process PID {parent_pid} was not terminated"
    assert not is_pid_alive(child_pid), f"Child process PID {child_pid} became an orphaned process"
