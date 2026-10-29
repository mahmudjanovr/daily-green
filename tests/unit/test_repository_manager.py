"""Unit tests for IsolatedWorkspace, remote clone header configuration, credential isolation, and workspace cleanup."""

import base64
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from dailygreen.config import RepoConfig
from dailygreen.repository_manager import IsolatedWorkspace, RepositoryManagerError


def test_remote_clone_header_formatting_and_environment(monkeypatch, tmp_path: Path):
    """Verify that remote cloning formats HTTP Basic Auth for GitHub and passes credentials via environment."""
    captured_calls = []

    def mock_run(cmd, cwd=None, env=None, capture_output=None, check=None):
        captured_calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        # Simulate successful clone by creating .git directory in target
        (Path(cwd) / ".git").mkdir()
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    repo_cfg = RepoConfig(name="test-org/test-repo", default_branch="main", allowed_paths=["README.md"])
    token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

    with IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url="https://github.com/test-org/test-repo.git",
        token=token,
    ) as workspace_path:
        assert workspace_path.exists()

    assert len(captured_calls) == 1
    call = captured_calls[0]
    cmd = call["cmd"]
    env = call["env"]

    # 1. Command argument verification
    assert cmd[0] == "git"
    assert cmd[1] == "-c"
    assert cmd[2] == "core.hooksPath="
    assert cmd[3] == "clone"
    assert cmd[4] == "--depth"
    assert cmd[5] == "1"
    assert cmd[6] == "--branch"
    assert cmd[7] == "main"
    assert cmd[8] == "https://github.com/test-org/test-repo.git"
    assert cmd[9] == "."

    # Token must NEVER appear in command line arguments
    assert token not in " ".join(cmd)
    assert "http.extraheader" not in " ".join(cmd)

    # 2. Environment variable verification
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraheader"

    expected_auth_b64 = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    assert env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {expected_auth_b64}"

    assert env["GIT_CONFIG_KEY_1"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_1"] == ""
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_remote_clone_without_token_disables_credential_helper(monkeypatch, tmp_path: Path):
    """When cloning without a token, credential.helper is disabled and prompt is suppressed."""
    captured_calls = []

    def mock_run(cmd, cwd=None, env=None, capture_output=None, check=None):
        captured_calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        (Path(cwd) / ".git").mkdir()
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    repo_cfg = RepoConfig(name="test-org/public-repo", default_branch="main", allowed_paths=["README.md"])

    with IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url="https://github.com/test-org/public-repo.git",
        token="",
    ):
        pass

    assert len(captured_calls) == 1
    env = captured_calls[0]["env"]
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_CONFIG_KEY_1" not in env


def test_remote_clone_does_not_persist_token_in_workspace_git_config(tmp_path: Path):
    """Verify that cloning via GIT_CONFIG_COUNT does not serialize credentials into .git/config."""
    # Create local source git repo
    source_dir = tmp_path / "source_remote"
    source_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(source_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(source_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(source_dir), capture_output=True, check=True)
    (source_dir / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(source_dir), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(source_dir), capture_output=True, check=True)

    repo_cfg = RepoConfig(name="test-org/local-repo", default_branch="main", allowed_paths=["README.md"])
    dummy_token = "ghp_TestSecretToken1234567890abcdef123"

    with IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url=str(source_dir.resolve()),
        token=dummy_token,
    ) as ws:
        git_config_path = ws / ".git" / "config"
        assert git_config_path.exists()
        git_config_text = git_config_path.read_text(encoding="utf-8")

        # Credentials and extraheader must NOT be stored in .git/config
        assert dummy_token not in git_config_text
        assert "extraheader" not in git_config_text
        assert "x-access-token" not in git_config_text
        assert "AUTHORIZATION" not in git_config_text


def test_remote_clone_failure_cleans_up_workspace(monkeypatch, tmp_path: Path):
    """Verify that a clone failure cleans up the temporary directory and raises RepositoryManagerError."""
    def mock_run_fail(cmd, cwd=None, env=None, capture_output=None, check=None):
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=cmd,
            stderr=b"fatal: repository 'https://github.com/test-org/fail.git' not found",
        )

    monkeypatch.setattr(subprocess, "run", mock_run_fail)

    repo_cfg = RepoConfig(name="test-org/fail-repo", default_branch="main", allowed_paths=["README.md"])
    ws = IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url="https://github.com/test-org/fail.git",
        token="ghp_dummy",
    )

    with pytest.raises(RepositoryManagerError, match="Failed to clone remote repository"):
        ws.__enter__()

    # Directory must be cleaned up and reference cleared
    assert ws.workspace_path is None
    assert ws._temp_dir is None


def test_remote_clone_redacts_token_in_error_message(monkeypatch, tmp_path: Path):
    """Verify that sensitive token or basic auth strings appearing in stderr are scrubbed in the exception."""
    token = "ghp_VerySensitiveLiveToken1234567890abcdef"
    token_b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()

    def mock_run_fail_with_token(cmd, cwd=None, env=None, capture_output=None, check=None):
        raw_stderr = f"fatal: unable to access url: AUTHORIZATION: basic {token_b64} token: {token}".encode("utf-8")
        raise subprocess.CalledProcessError(returncode=128, cmd=cmd, stderr=raw_stderr)

    monkeypatch.setattr(subprocess, "run", mock_run_fail_with_token)

    repo_cfg = RepoConfig(name="test-org/sensitive-repo", default_branch="main", allowed_paths=["README.md"])
    ws = IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url="https://github.com/test-org/sensitive-repo.git",
        token=token,
    )

    with pytest.raises(RepositoryManagerError) as exc_info:
        ws.__enter__()

    err_msg = str(exc_info.value)
    # The actual token string must NEVER appear in the error message
    assert token not in err_msg
    assert token_b64 not in err_msg
    assert "***REDACTED" in err_msg


def test_isolated_workspace_success_cleanup(tmp_path: Path):
    """Verify that upon clean exit from context manager, temporary directory is deleted."""
    repo_cfg = RepoConfig(name="test-org/clean-repo", default_branch="main", allowed_paths=["README.md"])
    ws_created_path = None

    with IsolatedWorkspace(repo_config=repo_cfg) as ws:
        ws_created_path = ws
        assert ws_created_path.exists()
        (ws_created_path / "test.txt").write_text("hello")

    assert ws_created_path is not None
    assert not ws_created_path.exists()
