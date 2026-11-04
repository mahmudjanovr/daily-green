"""Unit tests for Phase 3 Retry Engine: failure classification, backoff, and retry eligibility."""

from dailygreen.models import FailureClassification, RiskLevel, Task, TaskCategory, TaskSource
from dailygreen.retry import calculate_backoff, classify_failure, evaluate_retry_eligibility


def _make_task(task_id: str, attempt_count: int = 0, max_retries: int = 2) -> Task:
    return Task(
        id=task_id,
        repo="test-owner/test-repo",
        title=f"Task {task_id}",
        description=f"Description for {task_id}",
        rationale=f"Rationale for {task_id}",
        acceptance_criteria=[f"Verify {task_id}"],
        risk_level=RiskLevel.LOW,
        validation_strategy="verify",
        source=TaskSource.DETERMINISTIC,
        category=TaskCategory.MAINTENANCE,
        target_files=["README.md"],
        attempt_count=attempt_count,
        max_retries=max_retries,
    )


def test_classify_permanent_safety_failures():
    """Verify security, policy, and safety failures are strictly classified as PERMANENT."""
    permanent_errors = [
        "Potential secrets detected in proposed change: API_KEY_SECRET",
        "Security violation: path traversal detected: ../../etc/passwd",
        "Diff line count (250) exceeds maximum limit (150)",
        "Modified file 'src/critical.py' is outside authorized allowlist",
        "Git tree hash mismatch: validated tree 123 does not match current workspace tree 456",
        "Acceptance criteria verification failed: expected link target not found",
        "Live mutations rejected because ALLOW_LIVE_MUTATIONS is not enabled",
    ]

    for err in permanent_errors:
        classification = classify_failure(err)
        assert classification == FailureClassification.PERMANENT, f"Error '{err}' should be PERMANENT but was {classification}"


def test_classify_transient_failures():
    """Verify timeouts, rate limits, and connection drops are classified as TRANSIENT."""
    transient_errors = [
        "GitHub API error: HTTP 429 Too Many Requests (Rate limit exceeded)",
        "Connection reset by peer during HTTPS fetch",
        "Command timed out after 300 seconds",
        "GitHub API 503 Service Unavailable: High load",
        "Lock contention: could not acquire git index lock within timeout",
        "Temporary DNS resolution failure for api.github.com",
    ]

    for err in transient_errors:
        classification = classify_failure(err)
        assert classification == FailureClassification.TRANSIENT, f"Error '{err}' should be TRANSIENT but was {classification}"


def test_calculate_exponential_backoff():
    """Verify exponential backoff grows predictably with attempts and respects cap."""
    factor = 1.5
    b1 = calculate_backoff(attempt=1, backoff_factor=factor)
    b2 = calculate_backoff(attempt=2, backoff_factor=factor)
    b3 = calculate_backoff(attempt=3, backoff_factor=factor)
    b10 = calculate_backoff(attempt=10, backoff_factor=factor)

    assert b1 == 1.5  # 1.5 * 2^0
    assert b2 == 3.0  # 1.5 * 2^1
    assert b3 == 6.0  # 1.5 * 2^2
    assert b10 == 60.0  # Capped at 60.0s


def test_evaluate_retry_eligibility_transient_within_limit():
    """Verify transient failure with attempts remaining is eligible for retry."""
    task = _make_task("task-1", attempt_count=1, max_retries=2)
    eligible, reason, classification, backoff = evaluate_retry_eligibility(
        task=task,
        error_msg="Connection timed out while querying GitHub API",
        max_retries=2,
        backoff_factor=1.0,
    )

    assert eligible is True
    assert classification == FailureClassification.TRANSIENT
    assert backoff == 1.0


def test_evaluate_retry_eligibility_exhausted():
    """Verify transient failure with zero attempts remaining is not eligible for retry."""
    task = _make_task("task-1", attempt_count=2, max_retries=2)
    eligible, reason, classification, backoff = evaluate_retry_eligibility(
        task=task,
        error_msg="Connection timed out while querying GitHub API",
        max_retries=2,
        backoff_factor=1.0,
    )

    assert eligible is False
    assert classification == FailureClassification.TRANSIENT
    assert "exhausted" in reason.lower()
    assert backoff == 0.0


def test_evaluate_retry_eligibility_permanent_failure_never_retried():
    """Verify permanent failure is never eligible for retry, even on attempt 1."""
    task = _make_task("task-1", attempt_count=1, max_retries=5)
    eligible, reason, classification, backoff = evaluate_retry_eligibility(
        task=task,
        error_msg="Security violation: Secret detected in unified diff",
        max_retries=5,
        backoff_factor=1.0,
    )

    assert eligible is False
    assert classification == FailureClassification.PERMANENT
    assert backoff == 0.0
