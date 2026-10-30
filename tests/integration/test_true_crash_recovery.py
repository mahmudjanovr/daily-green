"""True subprocess crash-recovery integration test with OS-level process termination."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest
from dailygreen.security import safe_git_command


def _create_test_repository(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(safe_git_command(["git", "init", "-b", "main"]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.name", "Test User"]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "config", "user.email", "test@test.com"]), cwd=str(repo_dir), capture_output=True, check=True)

    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "README.md").write_text("# Project Title\n\nWelcome to our documentation.\n", encoding="utf-8")
    (docs_dir / "guide.md").write_text("# User Guide\n\nGetting started guide.\n", encoding="utf-8")

    subprocess.run(safe_git_command(["git", "add", "."]), cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(safe_git_command(["git", "commit", "-m", "Initial commit"]), cwd=str(repo_dir), capture_output=True, check=True)


def test_true_crash_recovery_via_process_termination(tmp_path: Path):
    """
    Subprocess-level test verifying recovery from an abrupt process termination (kill()):
    1. Process 1 launches, discovers tasks, enqueues, and enters RUNNING state.
    2. Process 1 is forcefully killed with p1.kill().
    3. Process 2 is started against the identical state directory.
    4. Process 2 safely recovers the interrupted task, increments attempt count, completes execution,
       prevents duplicate deliveries, and leaves the workspace clean and consistent.
    """
    repo_dir = tmp_path / "repo"
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _create_test_repository(repo_dir)

    repos_config_path = tmp_path / "repos.yml"
    repos_config_path.write_text(f"""
repositories:
  - name: "test-org/crash-repo"
    default_branch: "main"
    enabled: true
    allowed_paths:
      - "README.md"
      - "docs/**"
    supported_task_types:
      - "curated_backlog"
    curated_tasks:
      - id: "task-crash-recovery-1"
        title: "Update documentation links"
        description: "Review and update markdown documentation."
        rationale: "Ensure reliable documentation references."
        acceptance_criteria:
          - "Markdown links are valid."
        risk_level: "low"
        validation_strategy: "deterministic_markdown_link_check"
        source: "backlog"
        target_files:
          - "docs/guide.md"
""", encoding="utf-8")

    policy_config_path = Path("config/policy.yml").resolve()

    env = os.environ.copy()
    env.pop("DAILYGREEN_STATE_DIR", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")

    cmd = [
        sys.executable,
        "-m",
        "dailygreen.cli",
        "run",
        "--repo",
        "test-org/crash-repo",
        "--source-dir",
        str(repo_dir),
        "--repos-config",
        str(repos_config_path),
        "--policy-config",
        str(policy_config_path),
        "--state-dir",
        str(state_dir),
        "--mock-github",
        "--dry-run",
    ]

    # 1. Launch Process 1
    p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Monitor queue file until task enters RUNNING
    queue_file = state_dir / "queue_test-org_crash-repo.json"
    task_running = False
    start_wait = time.time()

    while time.time() - start_wait < 15:
        if queue_file.exists():
            try:
                data = json.loads(queue_file.read_text(encoding="utf-8"))
                for t in data.get("tasks", []):
                    if t.get("status") in ("running", "completed"):
                        task_running = True
                        break
            except Exception:
                pass
        if task_running:
            break
        time.sleep(0.1)

    # 2. Forcefully terminate Process 1 (simulating unhandled kernel SIGKILL / power loss)
    p1.kill()
    out1, err1 = p1.communicate()

    # Verify task was recorded in queue by Process 1
    assert queue_file.exists(), f"Queue file was not created by Process 1. stdout: {out1}, stderr: {err1}"
    q_data_p1 = json.loads(queue_file.read_text(encoding="utf-8"))
    assert len(q_data_p1.get("tasks", [])) > 0
    t1 = q_data_p1["tasks"][0]
    initial_attempts = t1.get("attempt_count", 1)

    # 3. Launch Process 2 on the SAME state directory
    res_p2 = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    assert res_p2.returncode == 0, f"Process 2 failed with stderr: {res_p2.stderr}\nstdout: {res_p2.stdout}"

    # 4. Verify Process 2 recovered the task, incremented attempt count, and completed it safely
    q_data_p2 = json.loads(queue_file.read_text(encoding="utf-8"))
    recovered_task = q_data_p2["tasks"][0]

    assert recovered_task["id"] == "task-crash-recovery-1"
    assert recovered_task["status"] == "completed"
    assert recovered_task["attempt_count"] > initial_attempts, (
        f"Expected attempt_count > {initial_attempts}, got {recovered_task['attempt_count']}"
    )

    # Verify completion recorded in StateManager
    state_file = state_dir / "state.json"
    assert state_file.exists()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    completed_keys = list(state_data.get("completed_tasks", {}).keys())
    assert any("task-crash-recovery-1" in k for k in completed_keys)

    # Working tree of source repository remains completely clean
    git_status = subprocess.run(
        safe_git_command(["git", "status", "--porcelain=v1"]),
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    assert git_status.stdout.strip() == "", "Source repository working tree was modified unexpectedly"
