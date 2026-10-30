"""Configuration loading and validation for DailyGreen."""

import os
import re
from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigurationError(Exception):
    """Raised when configuration is missing, malformed, or violates security policy."""
    pass


class RepoConfig(BaseModel):
    """Configuration for an explicitly authorized repository."""
    name: str = Field(..., description="Target repository in 'owner/repo' format")
    default_branch: str = Field(default="main", description="Default branch name")
    enabled: bool = Field(default=True, description="Whether this repository is active")
    allowed_paths: list[str] = Field(
        default_factory=lambda: ["docs/**", "*.md"],
        description="Glob patterns of file paths permitted to be modified"
    )
    denied_paths: list[str] = Field(
        default_factory=list,
        description="Glob patterns of file paths strictly denied (merged with global policy)"
    )
    max_diff_lines: int = Field(default=150, ge=1, le=500, description="Max changed lines per task")
    timeout_seconds: int = Field(default=300, ge=10, le=1800, description="Per-run execution timeout")
    validation_timeout_seconds: Optional[int] = Field(
        default=None,
        ge=5,
        le=1800,
        description="Per-command validation timeout for test and lint commands (overrides timeout_seconds)",
    )
    supported_task_types: list[str] = Field(
        default_factory=lambda: [
            "doc_links",
            "doc_formatting",
            "doc_typos",
            "curated_backlog",
            "issue_task",
        ],
        description="Task types enabled for this repository"
    )
    allow_ai_tasks: bool = Field(default=False, description="Whether AI-assisted proposals are allowed")
    baseline_command: Optional[list[str]] = Field(
        default=None,
        description="Command array to verify the repository is clean before changes (e.g. ['pytest'])"
    )
    test_commands: list[list[str]] = Field(
        default_factory=list,
        description="List of command arrays to run after applying changes"
    )
    lint_commands: list[list[str]] = Field(
        default_factory=list,
        description="List of linter command arrays to run after applying changes"
    )
    curated_tasks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Curated local backlog items for this repository"
    )
    max_tasks_per_run: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Per-repo maximum tasks to process per run"
    )

    @field_validator("name")
    @classmethod
    def validate_repo_name(cls, v: str) -> str:
        pattern = r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$"
        if not re.match(pattern, v):
            raise ValueError(f"Repository name '{v}' must be in 'owner/repo' format.")
        return v

    @field_validator("allowed_paths")
    @classmethod
    def validate_allowed_paths(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Repository must explicitly configure at least one allowed path.")
        for p in v:
            if not p or not isinstance(p, str) or ".." in p or p.startswith("/") or p.startswith("\\"):
                raise ValueError(f"Unsafe path pattern '{p}' in allowed_paths.")
        return v

    @field_validator("supported_task_types")
    @classmethod
    def validate_task_types(cls, v: list[str]) -> list[str]:
        valid_types = {"doc_links", "doc_formatting", "doc_typos", "curated_backlog", "issue_task"}
        for t in v:
            if t not in valid_types:
                raise ValueError(f"Unsupported task type '{t}'. Must be one of: {sorted(valid_types)}")
        return v


class AIConfig(BaseModel):
    """Configuration for the AI engine adapter."""
    provider: str = Field(default="mock", description="AI provider: 'mock' or 'gemini'")
    model: str = Field(default="gemini-1.5-flash", description="Model identifier")
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, ge=64, le=8192)
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    max_requests_per_run: int = Field(default=2, ge=1, le=10)


class ExecutionConfig(BaseModel):
    """Configuration for autonomous execution engine."""
    max_tasks_per_run: int = Field(default=1, ge=1, le=50, description="Maximum tasks to execute per run")
    max_workers: int = Field(default=1, ge=1, le=1, description="Maximum concurrent worker threads (strictly 1 in shared workspace)")
    max_retries: int = Field(default=2, ge=0, le=5, description="Maximum retries for transient failures")
    retry_backoff_factor: float = Field(default=1.0, ge=0.1, le=60.0, description="Exponential backoff factor in seconds")
    task_timeout_seconds: int = Field(default=300, ge=10, le=1800, description="Per-task execution timeout")

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        if v != 1:
            raise ValueError(
                f"Parallel worker execution is not supported in shared workspaces (max_workers={v}). "
                "max_workers must be strictly 1."
            )
        return v


class SecurityPolicyConfig(BaseModel):
    """Global security policy for all DailyGreen operations."""
    max_diff_lines: int = Field(default=150, ge=1, le=500)
    max_tasks_per_run: int = Field(default=10, ge=1, le=50)
    block_workflows: bool = Field(default=True, description="Strictly forbid editing .github/workflows")
    block_lockfiles: bool = Field(default=True, description="Strictly forbid editing package lockfiles")
    require_secret_scan: bool = Field(default=True, description="Must scan diff and changes for secrets")
    denied_paths: list[str] = Field(
        default_factory=lambda: [
            ".env*",
            "*.env",
            "*.key",
            "*.pem",
            "*.pfx",
            "*.cert",
            "*.p12",
            ".github/workflows/**",
            "package-lock.json",
            "poetry.lock",
            "Pipfile.lock",
            "pnpm-lock.yaml",
            "yarn.lock",
            "composer.lock",
            "Cargo.lock",
            "*.sh",
            "*.bat",
            "*.cmd",
            "*.exe",
            "*.bin",
            ".dailygreen/**",
            ".git/**",
        ]
    )
    disallowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".exe", ".dll", ".so", ".sh", ".bat", ".cmd", ".bin", ".key", ".pem"
        ]
    )


class DailyGreenConfig(BaseModel):
    """Root configuration for DailyGreen."""
    enabled: bool = Field(default=True, description="Global kill switch")
    dry_run: bool = Field(default=True, description="Default dry-run mode (safe)")
    allow_live_mutations: bool = Field(default=False, description="Explicit opt-in required for live remote mutations")
    repos: list[RepoConfig] = Field(default_factory=list)
    policy: SecurityPolicyConfig = Field(default_factory=SecurityPolicyConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    state_dir: str = Field(default=".dailygreen")

    def get_repo(self, repo_name: str) -> Optional[RepoConfig]:
        """Retrieve repository config if explicitly authorized and enabled."""
        for r in self.repos:
            if r.name.lower() == repo_name.lower():
                return r
        return None

    def is_repo_authorized(self, repo_name: str) -> bool:
        """Check if repository is authorized and enabled."""
        repo = self.get_repo(repo_name)
        return repo is not None and repo.enabled


def load_config(
    repos_path: Optional[str | Path] = None,
    policy_path: Optional[str | Path] = None,
    override_dry_run: Optional[bool] = None,
    override_allow_live_mutations: Optional[bool] = None,
    override_max_tasks: Optional[int] = None,
    override_max_workers: Optional[int] = None,
    override_max_retries: Optional[int] = None,
    override_state_dir: Optional[str | Path] = None,
) -> DailyGreenConfig:
    """
    Load configuration from YAML files and environment variables.
    Fails closed if configuration is invalid or missing when explicitly requested.
    """
    # 1. Check global kill switch via environment variable (fail-closed if unknown or empty)
    raw_env_enabled = os.getenv("DAILYGREEN_ENABLED")
    if raw_env_enabled is None:
        enabled = True
    else:
        cleaned_enabled = raw_env_enabled.strip().lower()
        if cleaned_enabled in ("1", "true", "yes", "on"):
            enabled = True
        else:
            # Empty, explicit false ("0", "false", "no", "off"), or unrecognized values fail closed (disabled)
            enabled = False

    # 2. Check dry-run setting (defaults to True, fails safe)
    if override_dry_run is not None:
        dry_run = override_dry_run
    else:
        raw_env_dry_run = os.getenv("DRY_RUN")
        if raw_env_dry_run is None:
            dry_run = True
        else:
            cleaned_dry_run = raw_env_dry_run.strip().lower()
            if not cleaned_dry_run:
                # Empty or whitespace-only resolves to True (fail-safe)
                dry_run = True
            elif cleaned_dry_run in ("0", "false", "no", "off"):
                # Only explicit false values disable dry-run
                dry_run = False
            else:
                # Any unrecognized, ambiguous, or true-like value resolves to True (fail-safe)
                dry_run = True

    # 2b. Check independent live mutations safety gate (defaults to False, fails closed)
    if override_allow_live_mutations is not None:
        allow_live_mutations = override_allow_live_mutations
    else:
        raw_env_live = os.getenv("ALLOW_LIVE_MUTATIONS")
        if raw_env_live is None:
            allow_live_mutations = False
        else:
            cleaned_live = raw_env_live.strip().lower()
            if cleaned_live in ("1", "true", "yes", "on"):
                allow_live_mutations = True
            else:
                # Missing, empty, unrecognized, or explicit false values fail closed (disallowed)
                allow_live_mutations = False

    # 3. Locate policy file
    policy_cfg = SecurityPolicyConfig()
    effective_policy_path = policy_path or os.getenv("DAILYGREEN_POLICY_CONFIG")
    if effective_policy_path:
        p_path = Path(effective_policy_path)
        if not p_path.exists():
            raise ConfigurationError(f"Security policy file not found: {effective_policy_path}")
        try:
            with open(p_path, "r", encoding="utf-8") as f:
                raw_policy = yaml.safe_load(f) or {}
                policy_cfg = SecurityPolicyConfig(**raw_policy)
        except Exception as e:
            raise ConfigurationError(f"Failed to parse security policy file '{effective_policy_path}': {e}") from e
    else:
        default_policy_file = Path("config/policy.yml")
        if default_policy_file.exists():
            try:
                with open(default_policy_file, "r", encoding="utf-8") as f:
                    raw_policy = yaml.safe_load(f) or {}
                    policy_cfg = SecurityPolicyConfig(**raw_policy)
            except Exception as e:
                raise ConfigurationError(f"Failed to parse default policy file '{default_policy_file}': {e}") from e

    # 4. Locate repos configuration file
    effective_repos_path = repos_path or os.getenv("DAILYGREEN_REPOS_CONFIG")
    repos_list: list[RepoConfig] = []

    if effective_repos_path:
        r_path = Path(effective_repos_path)
        if not r_path.exists():
            raise ConfigurationError(f"Repositories configuration file not found: {effective_repos_path}")
        try:
            with open(r_path, "r", encoding="utf-8") as f:
                raw_repos = yaml.safe_load(f) or {}
                raw_list = raw_repos.get("repositories", [])
                for item in raw_list:
                    repos_list.append(RepoConfig(**item))
        except Exception as e:
            raise ConfigurationError(f"Failed to parse repos config file '{effective_repos_path}': {e}") from e
    else:
        # Check standard default location if exists
        default_repos_file = Path("config/repos.yml")
        if default_repos_file.exists():
            try:
                with open(default_repos_file, "r", encoding="utf-8") as f:
                    raw_repos = yaml.safe_load(f) or {}
                    raw_list = raw_repos.get("repositories", [])
                    for item in raw_list:
                        repos_list.append(RepoConfig(**item))
            except Exception as e:
                raise ConfigurationError(f"Failed to parse default repos file '{default_repos_file}': {e}") from e

    # Validate repositories against global policy and ensure uniqueness
    seen_names = set()
    for r in repos_list:
        r_lower = r.name.lower()
        if r_lower in seen_names:
            raise ConfigurationError(f"Duplicate repository definition in configuration: '{r.name}'")
        seen_names.add(r_lower)

        if r.max_diff_lines > policy_cfg.max_diff_lines:
            raise ConfigurationError(
                f"Repository '{r.name}' max_diff_lines ({r.max_diff_lines}) exceeds "
                f"global security policy limit ({policy_cfg.max_diff_lines})."
            )

    # 5. AI Configuration
    ai_provider = os.getenv("DAILYGREEN_AI_PROVIDER", "mock")
    ai_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    raw_ai_timeout = 30
    if os.getenv("DAILYGREEN_AI_TIMEOUT"):
        try:
            raw_ai_timeout = int(os.getenv("DAILYGREEN_AI_TIMEOUT", "30"))
        except ValueError:
            raw_ai_timeout = 30
    ai_cfg = AIConfig(
        provider=ai_provider,
        model=ai_model,
        timeout_seconds=max(5, min(120, raw_ai_timeout)),
    )

    # 6. Execution Configuration
    raw_max_tasks = override_max_tasks
    if raw_max_tasks is None and os.getenv("DAILYGREEN_MAX_TASKS_PER_RUN"):
        try:
            raw_max_tasks = int(os.getenv("DAILYGREEN_MAX_TASKS_PER_RUN", "1"))
        except ValueError:
            raw_max_tasks = 1
    max_tasks = raw_max_tasks if raw_max_tasks is not None else policy_cfg.max_tasks_per_run
    # Bound to policy limit
    max_tasks = min(max_tasks, policy_cfg.max_tasks_per_run)

    raw_max_workers = override_max_workers
    if raw_max_workers is None and os.getenv("DAILYGREEN_MAX_WORKERS"):
        try:
            raw_max_workers = int(os.getenv("DAILYGREEN_MAX_WORKERS", "1"))
        except ValueError:
            raw_max_workers = 1
    max_workers = raw_max_workers if raw_max_workers is not None else 1

    raw_max_retries = override_max_retries
    if raw_max_retries is None and os.getenv("DAILYGREEN_MAX_RETRIES"):
        try:
            raw_max_retries = int(os.getenv("DAILYGREEN_MAX_RETRIES", "2"))
        except ValueError:
            raw_max_retries = 2
    max_retries = raw_max_retries if raw_max_retries is not None else 2

    raw_backoff = 1.0
    if os.getenv("DAILYGREEN_RETRY_BACKOFF"):
        try:
            raw_backoff = float(os.getenv("DAILYGREEN_RETRY_BACKOFF", "1.0"))
        except ValueError:
            raw_backoff = 1.0

    raw_timeout = 300
    if os.getenv("DAILYGREEN_TASK_TIMEOUT"):
        try:
            raw_timeout = int(os.getenv("DAILYGREEN_TASK_TIMEOUT", "300"))
        except ValueError:
            raw_timeout = 300

    effective_state_dir = str(override_state_dir or os.getenv("DAILYGREEN_STATE_DIR") or ".dailygreen")

    try:
        exec_cfg = ExecutionConfig(
            max_tasks_per_run=max(1, max_tasks),
            max_workers=max_workers,
            max_retries=max(0, min(5, max_retries)),
            retry_backoff_factor=max(0.1, min(60.0, raw_backoff)),
            task_timeout_seconds=max(10, min(1800, raw_timeout)),
        )

        return DailyGreenConfig(
            enabled=enabled,
            dry_run=dry_run,
            allow_live_mutations=allow_live_mutations,
            repos=repos_list,
            policy=policy_cfg,
            ai=ai_cfg,
            execution=exec_cfg,
            state_dir=effective_state_dir,
        )
    except ValidationError as e:
        raise ConfigurationError(f"Invalid execution configuration: {e}") from e
