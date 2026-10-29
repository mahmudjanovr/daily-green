"""Unit tests for the isolated worker, command execution, timeouts, and baseline tests."""

import sys
from pathlib import Path
from dailygreen.config import RepoConfig
from dailygreen.worker import (
    run_baseline_checks,
    run_command_in_workspace,
    run_validation_checks,
)


def test_run_command_success(tmp_path: Path):
    cmd = [sys.executable, "-c", "print('hello world')"]
    res = run_command_in_workspace(cmd, tmp_path)
    assert res.passed is True
    assert res.exit_code == 0
    assert "hello world" in res.stdout


def test_run_command_failure(tmp_path: Path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(2)"]
    res = run_command_in_workspace(cmd, tmp_path)
    assert res.passed is False
    assert res.exit_code == 2


def test_run_command_timeout(tmp_path: Path):
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    res = run_command_in_workspace(cmd, tmp_path, timeout_seconds=1)
    assert res.passed is False
    assert res.timed_out is True
    assert "timed out after 1s" in res.stderr


def test_run_command_sanitized_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "super_secret_write_token")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_secret")

    # Command tests whether GITHUB_TOKEN is present in env
    cmd = [sys.executable, "-c", "import os; assert 'GITHUB_TOKEN' not in os.environ"]
    res = run_command_in_workspace(cmd, tmp_path)
    assert res.passed is True


def test_run_baseline_checks_failure(tmp_path: Path):
    repo = RepoConfig(
        name="org/repo",
        baseline_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
    )
    res = run_baseline_checks(tmp_path, repo)
    assert res is not None
    assert res.passed is False


def test_run_validation_checks(tmp_path: Path):
    repo = RepoConfig(
        name="org/repo",
        test_commands=[[sys.executable, "-c", "print('test ok')"]],
        lint_commands=[[sys.executable, "-c", "print('lint ok')"]],
    )
    tests, lints = run_validation_checks(tmp_path, repo)
    assert len(tests) == 1
    assert tests[0].passed is True
    assert len(lints) == 1
    assert lints[0].passed is True
