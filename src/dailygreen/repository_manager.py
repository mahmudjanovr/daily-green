"""Workspace isolation and repository staging manager."""

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator, Optional
from dailygreen.config import RepoConfig
from dailygreen.security import redact_secrets, safe_git_command


class RepositoryManagerError(Exception):
    """Raised when repository preparation or isolation fails."""
    pass


class IsolatedWorkspace:
    """Context manager for preparing and safely tearing down an isolated git workspace."""

    def __init__(
        self,
        repo_config: RepoConfig,
        source_dir: Optional[Path | str] = None,
        clone_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.repo_config = repo_config
        self.source_dir = Path(source_dir) if source_dir else None
        self.clone_url = clone_url
        self.token = token or os.getenv("GITHUB_TOKEN", "").strip()
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self.workspace_path: Optional[Path] = None

    def __enter__(self) -> Path:
        self._temp_dir = tempfile.TemporaryDirectory(prefix=f"dailygreen_{self.repo_config.name.replace('/', '_')}_")
        self.workspace_path = Path(self._temp_dir.name).resolve()

        if self.source_dir and self.source_dir.exists():
            # Clone or copy from local source repository
            try:
                # If source is a git repository, clone it into workspace
                if (self.source_dir / ".git").exists():
                    subprocess.run(
                        safe_git_command(["git", "clone", "--depth", "1", str(self.source_dir.resolve()), "."]),
                        cwd=str(self.workspace_path),
                        capture_output=True,
                        check=True,
                    )
                else:
                    # Copy tree
                    shutil.copytree(self.source_dir, self.workspace_path, dirs_exist_ok=True)
                    # Initialize git in workspace
                    subprocess.run(safe_git_command(["git", "init", "-b", self.repo_config.default_branch]), cwd=str(self.workspace_path), capture_output=True, check=True)
                    subprocess.run(safe_git_command(["git", "config", "user.name", "DailyGreen Bot"]), cwd=str(self.workspace_path), capture_output=True, check=True)
                    subprocess.run(safe_git_command(["git", "config", "user.email", "dailygreen@users.noreply.github.com"]), cwd=str(self.workspace_path), capture_output=True, check=True)
                    subprocess.run(safe_git_command(["git", "add", "."]), cwd=str(self.workspace_path), capture_output=True, check=True)
                    subprocess.run(safe_git_command(["git", "commit", "-m", "Initial commit"]), cwd=str(self.workspace_path), capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                self.cleanup()
                err_text = redact_secrets(e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr))
                raise RepositoryManagerError(f"Failed to initialize workspace from source: {err_text}") from e
        elif self.clone_url:
            # Shallow clone remote using transient environment configuration
            try:
                cmd = ["git", "clone", "--depth", "1", "--branch", self.repo_config.default_branch, self.clone_url, "."]
                clone_env = os.environ.copy()
                clone_env["GIT_TERMINAL_PROMPT"] = "0"

                if self.token:
                    auth_bytes = f"x-access-token:{self.token}".encode("utf-8")
                    auth_b64 = base64.b64encode(auth_bytes).decode("ascii")
                    clone_env["GIT_CONFIG_COUNT"] = "2"
                    clone_env["GIT_CONFIG_KEY_0"] = "http.extraheader"
                    clone_env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {auth_b64}"
                    clone_env["GIT_CONFIG_KEY_1"] = "credential.helper"
                    clone_env["GIT_CONFIG_VALUE_1"] = ""
                else:
                    clone_env["GIT_CONFIG_COUNT"] = "1"
                    clone_env["GIT_CONFIG_KEY_0"] = "credential.helper"
                    clone_env["GIT_CONFIG_VALUE_0"] = ""

                subprocess.run(
                    safe_git_command(cmd),
                    cwd=str(self.workspace_path),
                    env=clone_env,
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                self.cleanup()
                err_text = redact_secrets(
                    e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr),
                    extra_secrets=[self.token] if self.token else None,
                )
                raise RepositoryManagerError(f"Failed to clone remote repository {self.clone_url}: {err_text}") from e
        else:
            # Initialize empty clean git repo
            subprocess.run(safe_git_command(["git", "init", "-b", self.repo_config.default_branch]), cwd=str(self.workspace_path), capture_output=True, check=True)
            subprocess.run(safe_git_command(["git", "config", "user.name", "DailyGreen Bot"]), cwd=str(self.workspace_path), capture_output=True, check=True)
            subprocess.run(safe_git_command(["git", "config", "user.email", "dailygreen@users.noreply.github.com"]), cwd=str(self.workspace_path), capture_output=True, check=True)

        return self.workspace_path

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._temp_dir:
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            self._temp_dir = None
            self.workspace_path = None
