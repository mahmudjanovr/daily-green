"""Core data models for DailyGreen."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class TaskSource(str, Enum):
    """Source of a discovered task."""
    ISSUE = "issue"
    BACKLOG = "backlog"
    DETERMINISTIC = "deterministic"
    AI = "ai"


class RiskLevel(str, Enum):
    """Risk tier of a task."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, Enum):
    """Lifecycle status of a task."""
    DISCOVERED = "discovered"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    REJECTED = "rejected"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunStatus(str, Enum):
    """Overall status of a DailyGreen execution run."""
    TASK_COMPLETED = "task_completed"
    TESTS_PASSED = "tests_passed"
    PULL_REQUEST_CREATED = "pull_request_created"
    PULL_REQUEST_MERGED = "pull_request_merged"
    CONTRIBUTION_VERIFIED = "contribution_verified"
    NO_TASK = "no_task"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN_COMPLETED = "dry_run_completed"


class Task(BaseModel):
    """A bounded, legitimate maintenance task."""
    id: str = Field(..., description="Unique stable identifier or slug")
    repo: str = Field(..., description="Target repository in owner/repo format")
    title: str = Field(..., description="Concise title")
    description: str = Field(..., description="Full task description")
    rationale: str = Field(..., description="Reason why this task is worthwhile")
    acceptance_criteria: list[str] = Field(default_factory=list, description="Measurable criteria")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    validation_strategy: str = Field(..., description="How this task is validated")
    source: TaskSource = Field(..., description="Origin of the task")
    target_files: list[str] = Field(default_factory=list, description="Relative paths to target files")
    patch: Optional[str] = Field(default=None, description="Proposed git diff or unified patch if known")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    """Result of running an external command in an isolated workspace."""
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SecurityCheckResult(BaseModel):
    """Result of running security checks on a proposed change."""
    passed: bool
    secrets_detected: list[str] = Field(default_factory=list)
    denied_files: list[str] = Field(default_factory=list)
    path_traversals: list[str] = Field(default_factory=list)
    lines_changed: int = 0
    max_lines_allowed: int = 150
    details: list[str] = Field(default_factory=list)


class QualityGateResult(BaseModel):
    """Comprehensive result of the quality gate evaluation."""
    passed: bool
    reason: str
    baseline_result: Optional[CommandResult] = None
    post_change_tests: list[CommandResult] = Field(default_factory=list)
    post_change_lints: list[CommandResult] = Field(default_factory=list)
    security_result: Optional[SecurityCheckResult] = None
    patch_hash: Optional[str] = Field(default=None, description="SHA256 seal of the verified patch")
    base_commit_sha: Optional[str] = Field(default=None, description="Base commit SHA prior to changes")
    tree_sha: Optional[str] = Field(default=None, description="Git tree object hash of the validated changes")
    verified_diff: Optional[str] = Field(default=None, description="Exact verified unified diff")
    changed_files: list[str] = Field(default_factory=list, description="Exact list of files touched according to git")


class DeliveryResult(BaseModel):
    """Result of creating a pull request or simulated delivery."""
    success: bool
    branch_name: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    is_dry_run: bool = False
    message: str
    contribution_status: str = "UNKNOWN"
    details: dict[str, Any] = Field(default_factory=dict)


class RunReport(BaseModel):
    """Structured report of a DailyGreen run."""
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    repo: str
    status: RunStatus
    task: Optional[Task] = None
    quality_gate: Optional[QualityGateResult] = None
    delivery: Optional[DeliveryResult] = None
    message: str = ""
    is_backup_run: bool = False
