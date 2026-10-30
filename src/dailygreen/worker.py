"""Isolated workspace execution worker for running tests and commands safely."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from dailygreen.config import RepoConfig
from dailygreen.models import CommandResult
from dailygreen.security import redact_secrets, safe_git_command, sanitize_environment


class WorkerExecutionError(Exception):
    """Raised when command execution encounters a critical worker error."""
    pass


def kill_process_tree(pid: int) -> None:
    """
    Safely and forcefully terminate an entire process tree given a root PID.
    Prevents orphaned child processes on Windows (e.g. node.exe spawned by npm.cmd)
    and POSIX systems.
    """
    if os.name == "nt":
        try:
            # taskkill /F /T kills the specified process and any child processes started by it
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except Exception:
            pass
    else:
        import signal
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def run_command_in_workspace(
    cmd_args: list[str],
    workspace_dir: Path,
    timeout_seconds: int = 120,
    max_output_bytes: int = 50000,
) -> CommandResult:
    """
    Execute a configured command in the isolated workspace with:
    - shell=False
    - sanitized environment stripped of secrets/tokens
    - strict timeout and complete descendant process tree termination
    - output size truncation
    """
    if not cmd_args:
        raise WorkerExecutionError("Cannot execute empty command list")

    effective_cmd = safe_git_command(cmd_args)
    # On Windows/cross-platform, resolve command executable via shutil.which for shell=False compatibility
    if effective_cmd:
        resolved_bin = shutil.which(effective_cmd[0])
        if resolved_bin:
            effective_cmd = [resolved_bin] + effective_cmd[1:]

    sanitized_env = sanitize_environment()
    start_time = time.time()

    creationflags = 0
    preexec_fn = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        preexec_fn = os.setsid

    try:
        proc = subprocess.Popen(
            effective_cmd,
            cwd=str(workspace_dir),
            env=sanitized_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            preexec_fn=preexec_fn,
            shell=False,
        )
        try:
            raw_stdout, raw_stderr = proc.communicate(timeout=timeout_seconds)
            duration = time.time() - start_time
            stdout = redact_secrets((raw_stdout or "")[:max_output_bytes])
            stderr = redact_secrets((raw_stderr or "")[:max_output_bytes])
            return CommandResult(
                command=cmd_args,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 2),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            kill_process_tree(proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
            try:
                out_drain, err_drain = proc.communicate(timeout=5)
            except Exception:
                out_drain, err_drain = "", ""
            stdout = redact_secrets((out_drain or "")[:max_output_bytes])
            stderr = redact_secrets((err_drain or "")[:max_output_bytes])
            return CommandResult(
                command=cmd_args,
                exit_code=-1,
                stdout=stdout,
                stderr=f"Command timed out after {timeout_seconds}s. {stderr}".strip(),
                duration_seconds=round(duration, 2),
                timed_out=True,
            )
    except Exception as e:
        duration = time.time() - start_time
        return CommandResult(
            command=cmd_args,
            exit_code=-1,
            stdout="",
            stderr=redact_secrets(f"Failed to execute command {cmd_args}: {e}"),
            duration_seconds=round(duration, 2),
            timed_out=False,
        )


def run_baseline_checks(workspace_dir: Path, repo_config: RepoConfig) -> Optional[CommandResult]:
    """
    Run configured baseline command BEFORE applying any changes.
    Uses validation_timeout_seconds if configured, falling back to timeout_seconds.
    Returns None if no baseline command configured, or CommandResult.
    """
    if not repo_config.baseline_command:
        return None
    timeout = repo_config.validation_timeout_seconds or repo_config.timeout_seconds
    return run_command_in_workspace(
        repo_config.baseline_command,
        workspace_dir,
        timeout_seconds=timeout,
    )


def run_validation_checks(workspace_dir: Path, repo_config: RepoConfig) -> tuple[list[CommandResult], list[CommandResult]]:
    """
    Run configured test and lint commands AFTER applying changes.
    Uses validation_timeout_seconds if configured, falling back to timeout_seconds.
    Returns (test_results, lint_results).
    """
    test_results: list[CommandResult] = []
    lint_results: list[CommandResult] = []
    timeout = repo_config.validation_timeout_seconds or repo_config.timeout_seconds

    for test_cmd in repo_config.test_commands:
        res = run_command_in_workspace(test_cmd, workspace_dir, timeout_seconds=timeout)
        test_results.append(res)
        if not res.passed:
            # Stop early on test failure
            break

    for lint_cmd in repo_config.lint_commands:
        res = run_command_in_workspace(lint_cmd, workspace_dir, timeout_seconds=timeout)
        lint_results.append(res)
        if not res.passed:
            break

    return test_results, lint_results
