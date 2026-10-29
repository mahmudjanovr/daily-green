"""Isolated workspace execution worker for running tests and commands safely."""

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
    - strict timeout
    - output size truncation
    """
    if not cmd_args:
        raise WorkerExecutionError("Cannot execute empty command list")

    effective_cmd = safe_git_command(cmd_args)
    sanitized_env = sanitize_environment()
    start_time = time.time()
    timed_out = False

    try:
        proc = subprocess.run(
            effective_cmd,
            cwd=str(workspace_dir),
            env=sanitized_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        duration = time.time() - start_time
        stdout = redact_secrets(proc.stdout[:max_output_bytes])
        stderr = redact_secrets(proc.stderr[:max_output_bytes])
        return CommandResult(
            command=cmd_args,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 2),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        duration = time.time() - start_time
        raw_stdout = (e.stdout or "")[:max_output_bytes] if isinstance(e.stdout, str) else ""
        raw_stderr = (e.stderr or "")[:max_output_bytes] if isinstance(e.stderr, str) else ""
        stdout = redact_secrets(raw_stdout)
        stderr = redact_secrets(raw_stderr)
        return CommandResult(
            command=cmd_args,
            exit_code=-1,
            stdout=stdout,
            stderr=f"Command timed out after {timeout_seconds}s. {stderr}",
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
    Returns None if no baseline command configured, or CommandResult.
    """
    if not repo_config.baseline_command:
        return None
    return run_command_in_workspace(
        repo_config.baseline_command,
        workspace_dir,
        timeout_seconds=repo_config.timeout_seconds,
    )


def run_validation_checks(workspace_dir: Path, repo_config: RepoConfig) -> tuple[list[CommandResult], list[CommandResult]]:
    """
    Run configured test and lint commands AFTER applying changes.
    Returns (test_results, lint_results).
    """
    test_results: list[CommandResult] = []
    lint_results: list[CommandResult] = []

    for test_cmd in repo_config.test_commands:
        res = run_command_in_workspace(test_cmd, workspace_dir, timeout_seconds=repo_config.timeout_seconds)
        test_results.append(res)
        if not res.passed:
            # Stop early on test failure
            break

    for lint_cmd in repo_config.lint_commands:
        res = run_command_in_workspace(lint_cmd, workspace_dir, timeout_seconds=repo_config.timeout_seconds)
        lint_results.append(res)
        if not res.passed:
            break

    return test_results, lint_results
