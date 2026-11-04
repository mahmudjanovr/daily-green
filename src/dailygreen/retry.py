"""Retry engine, transient failure classification, and exponential backoff for DailyGreen."""

import re
from typing import Optional
from dailygreen.models import FailureClassification, Task


# Strict patterns that MUST NEVER be retried under any circumstances
PERMANENT_FAILURE_PATTERNS: list[str] = [
    "security policy",
    "path policy",
    "denied path",
    "disallowed extension",
    "secret",
    "path traversal",
    "symlink escape",
    "max lines",
    "diff lines",
    "exceeds global security policy",
    "unrelated file",
    "tamper",
    "hash mismatch",
    "mode change",
    "empty diff",
    "broken link could not be safely replaced",
    "not permitted",
    "unsupported task",
    "dependency cycle detected",
    "prerequisite task",
    "already resolved",
    "ambiguous",
    "hard gate failure",
    "unauthorized repository",
    "live delivery rejected",
    "allow_live_mutations is not explicitly enabled",
    "task timeout",
    "execution timeout",
    "exceeded execution timeout",
    "task exceeded",
    "operation may still be active",
    "unreaped process",
    "tasktimeouterror",
]

# Patterns that indicate temporary/transient environmental disruptions
TRANSIENT_FAILURE_PATTERNS: list[str] = [
    "timeout",
    "timed out",
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection error",
    "connection reset",
    "connecterror",
    "network error",
    "network",
    "dns",
    "socket",
    "temporarily unavailable",
    "lock contention",
    "lease",
    "interrupted",
    "temporary failure in name resolution",
    "service unavailable",
]


def classify_failure(error_msg: str, exception: Optional[Exception] = None) -> FailureClassification:
    """
    Classify a task or worker failure as transient (eligible for retry) or permanent (never retried).
    Fails closed: if any permanent pattern is found, or if unknown, classifies as permanent.
    """
    combined = f"{error_msg} {str(exception) if exception else ''}".lower()

    # 1. Check permanent patterns first (highest priority)
    for pattern in PERMANENT_FAILURE_PATTERNS:
        if pattern in combined:
            return FailureClassification.PERMANENT

    # 2. Check transient patterns
    for pattern in TRANSIENT_FAILURE_PATTERNS:
        if pattern in combined:
            return FailureClassification.TRANSIENT

    # 3. Default to permanent (conservative fail-safe)
    return FailureClassification.PERMANENT


def calculate_backoff(
    attempt: int,
    backoff_factor: float = 1.0,
    max_backoff: float = 60.0,
) -> float:
    """
    Calculate deterministic exponential backoff delay in seconds:
    delay = min(max_backoff, backoff_factor * (2 ** (attempt - 1)))
    """
    attempt_index = max(0, attempt - 1)
    delay = backoff_factor * (2 ** attempt_index)
    return round(min(max_backoff, delay), 2)


def evaluate_retry_eligibility(
    task: Task,
    error_msg: str,
    max_retries: int,
    backoff_factor: float = 1.0,
) -> tuple[bool, str, FailureClassification, float]:
    """
    Determine if a task failure can be retried.
    Returns (eligible, reason, classification, backoff_delay).
    """
    classification = classify_failure(error_msg)

    if classification == FailureClassification.PERMANENT:
        return (
            False,
            f"Permanent safety failure: not eligible for retry ({error_msg})",
            FailureClassification.PERMANENT,
            0.0,
        )

    effective_limit = min(task.max_retries, max_retries)
    if task.attempt_count >= effective_limit:
        return (
            False,
            f"Transient failure retry limit exhausted ({task.attempt_count}/{effective_limit}): {error_msg}",
            FailureClassification.TRANSIENT,
            0.0,
        )

    # Eligible for transient retry
    delay = calculate_backoff(task.attempt_count, backoff_factor=backoff_factor)
    return (
        True,
        f"Transient failure: retry scheduled in {delay}s (attempt {task.attempt_count + 1}/{effective_limit})",
        FailureClassification.TRANSIENT,
        delay,
    )
