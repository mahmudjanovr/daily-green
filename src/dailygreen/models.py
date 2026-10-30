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
    AI_SUGGESTED = "ai"


class TaskCategory(str, Enum):
    """Classification of maintenance tasks."""
    DOCUMENTATION = "documentation"
    BUG_FIX = "bug_fix"
    REFACTORING = "refactoring"
    MAINTENANCE = "maintenance"
    DEPENDENCY_UPDATE = "dependency_update"


class RiskLevel(str, Enum):
    """Risk tier of a task."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, Enum):
    """Lifecycle status of a task in the autonomous execution queue."""
    DISCOVERED = "discovered"
    EVALUATED = "evaluated"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY_SCHEDULED = "retry_scheduled"
    # Preserved lifecycle aliases for backward compatibility
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    REJECTED = "rejected"


class FailureClassification(str, Enum):
    """Classification of a task failure to control retry eligibility."""
    TRANSIENT = "transient"
    PERMANENT = "permanent"


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


class IssueStatus(str, Enum):
    """Status classification of GitHub issues during intelligent analysis."""
    ACTIONABLE = "actionable"
    DUPLICATE = "duplicate"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"
    ALREADY_RESOLVED = "already_resolved"
    UNSUPPORTED = "unsupported"


class IssueAnalysis(BaseModel):
    """Detailed analysis of a GitHub issue."""
    issue_number: int
    title: str
    status: IssueStatus
    category: TaskCategory
    reason: str
    confidence: float = 1.0
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class ScoreDetail(BaseModel):
    """Transparent score and rationale for an evaluation dimension."""
    score: float = Field(..., ge=0.0, le=10.0, description="Normalized score 0.0 to 10.0")
    rationale: str = Field(..., description="Explanation of the score")


class TaskEvaluation(BaseModel):
    """Structured evaluation of a candidate task."""
    overall_score: float = Field(..., ge=0.0, le=10.0, description="Weighted composite score 0.0 - 10.0")
    passed: bool = Field(..., description="Whether task meets threshold and passes all hard gates")
    rejection_reason: Optional[str] = Field(default=None, description="Detailed reason if rejected or deferred")
    relevance: ScoreDetail
    clarity_completeness: ScoreDetail
    technical_feasibility: ScoreDetail
    expected_impact: ScoreDetail
    risk_assessment: ScoreDetail
    estimated_complexity: ScoreDetail
    permissions_and_dependencies: ScoreDetail
    explanation: str
    evaluated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class TaskPlan(BaseModel):
    """Machine-readable plan for task implementation."""
    task_id: str
    problem_statement: str
    evidence_and_affected_files: list[str] = Field(default_factory=list)
    proposed_solution: str
    implementation_steps: list[str] = Field(default_factory=list)
    expected_behavior: str
    tests_required: list[str] = Field(default_factory=list)
    risk_assessment: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    change_explanations: dict[str, str] = Field(
        default_factory=dict,
        description="Explanation for why each proposed change is necessary"
    )
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class DiscoverySummary(BaseModel):
    """Summary of the intelligent task discovery process."""
    candidates_found: int = 0
    issues_analyzed: list[IssueAnalysis] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)
    selected_task_id: Optional[str] = None
    selected_task_ids: list[str] = Field(default_factory=list)
    strategy: str = "intelligent_multi_criteria"


class ExecutionRecord(BaseModel):
    """Detailed execution record of a single task in the queue."""
    task_id: str
    repo: str
    status: TaskStatus
    worker_id: Optional[str] = None
    attempt_count: int = 1
    duration_seconds: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    is_transient: bool = False
    target_files: list[str] = Field(default_factory=list)
    validation_passed: Optional[bool] = None


class QueueSummary(BaseModel):
    """Summary of multi-task queue execution monitoring."""
    total_discovered: int = 0
    total_evaluated: int = 0
    total_queued: int = 0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    retried_count: int = 0
    cycle_detected: bool = False
    recovered_interrupted_count: int = 0
    records: list[ExecutionRecord] = Field(default_factory=list)


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
    unrelated_files_detected: list[str] = Field(
        default_factory=list,
        description="Files touched that were not in planned target files"
    )
    acceptance_criteria_verified: bool = Field(
        default=True,
        description="Whether acceptance criteria were explicitly verified"
    )
    validation_details: list[str] = Field(
        default_factory=list,
        description="Individual validation step outcomes and messages"
    )


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


class Task(BaseModel):
    """A bounded, legitimate maintenance task with autonomous execution lifecycle."""
    id: str = Field(..., description="Unique stable identifier or slug")
    repo: str = Field(..., description="Target repository in owner/repo format")
    title: str = Field(..., description="Concise title")
    description: str = Field(..., description="Full task description")
    rationale: str = Field(..., description="Reason why this task is worthwhile")
    acceptance_criteria: list[str] = Field(default_factory=list, description="Measurable criteria")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    validation_strategy: str = Field(..., description="How this task is validated")
    source: TaskSource = Field(..., description="Origin of the task")
    category: TaskCategory = Field(default=TaskCategory.MAINTENANCE, description="Task category")
    target_files: list[str] = Field(default_factory=list, description="Relative paths to target files")
    patch: Optional[str] = Field(default=None, description="Proposed git diff or unified patch if known")
    plan: Optional[TaskPlan] = Field(default=None, description="Structured execution plan")
    evaluation: Optional[TaskEvaluation] = Field(default=None, description="Evaluation score and rationale")
    evidence: list[str] = Field(default_factory=list, description="Concrete evidence justifying this task")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Phase 3 Autonomous Queue & Lifecycle Fields
    status: TaskStatus = Field(default=TaskStatus.DISCOVERED, description="Current lifecycle state")
    dependencies: list[str] = Field(default_factory=list, description="Prerequisite task IDs")
    attempt_count: int = Field(default=0, description="Total execution attempts so far")
    max_retries: int = Field(default=2, description="Maximum transient failure retries allowed")
    last_failure_reason: Optional[str] = Field(default=None, description="Last recorded failure reason")
    last_failure_transient: bool = Field(default=False, description="Whether last failure was transient")
    next_retry_time: Optional[float] = Field(default=None, description="Timestamp when retry is eligible")
    worker_id: Optional[str] = Field(default=None, description="Worker identifier assigned to task")
    started_at: Optional[str] = Field(default=None, description="Execution start timestamp")
    completed_at: Optional[str] = Field(default=None, description="Execution completion timestamp")
    duration_seconds: float = Field(default=0.0, description="Execution duration in seconds")
    quality_gate: Optional[QualityGateResult] = Field(default=None, description="Quality gate verification outcome")
    delivery: Optional[DeliveryResult] = Field(default=None, description="Delivery or PR outcome")


class RunReport(BaseModel):
    """Structured report of a DailyGreen run."""
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    repo: str
    status: RunStatus
    task: Optional[Task] = None
    tasks: list[Task] = Field(default_factory=list, description="All tasks executed in this run")
    queue_summary: Optional[QueueSummary] = Field(default=None, description="Execution queue monitoring summary")
    quality_gate: Optional[QualityGateResult] = None
    delivery: Optional[DeliveryResult] = None
    evaluation: Optional[TaskEvaluation] = Field(default=None, description="Structured task evaluation")
    plan: Optional[TaskPlan] = Field(default=None, description="Structured task plan")
    discovery_summary: Optional[DiscoverySummary] = Field(default=None, description="Task discovery details")
    files_analyzed: list[str] = Field(default_factory=list, description="Files inspected during discovery and planning")
    files_modified: list[str] = Field(default_factory=list, description="Files modified by the applied task")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if task or run was rejected")
    execution_duration_seconds: float = Field(default=0.0, description="Total execution duration in seconds")
    message: str = ""
    is_backup_run: bool = False
