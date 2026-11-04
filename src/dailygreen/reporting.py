"""Structured JSON logging and GitHub Step Summary reporting with Phase 2 observability."""

import json
import logging
import os
import sys
from typing import Any, Optional
from dailygreen.models import RunReport, RunStatus
from dailygreen.security import redact_secrets


class StructuredJSONFormatter(logging.Formatter):
    """Format logs as single-line JSON objects with automatic secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        raw_msg = record.getMessage()
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(raw_msg),
        }
        if record.exc_info:
            log_obj["exception"] = redact_secrets(self.formatException(record.exc_info))
        if hasattr(record, "extra_fields"):
            redacted_extras = {
                k: redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in getattr(record, "extra_fields", {}).items()
            }
            log_obj.update(redacted_extras)
        return json.dumps(log_obj)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure structured JSON logging for DailyGreen."""
    logger = logging.getLogger("dailygreen")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJSONFormatter())
        logger.addHandler(handler)

    return logger


def format_markdown_summary(report: RunReport) -> str:
    """
    Format a comprehensive GitHub Actions Job Step Summary in GitHub Flavored Markdown
    including evaluation scorecards, structured plan, validation results, and duration.
    """
    status_icon = "🟢" if report.status in (RunStatus.TASK_COMPLETED, RunStatus.PULL_REQUEST_CREATED, RunStatus.DRY_RUN_COMPLETED) else ("⚪" if report.status in (RunStatus.NO_TASK, RunStatus.SKIPPED) else "🔴")

    task_title = report.task.title if report.task else "None"
    task_id = report.task.id if report.task else "N/A"
    pr_link = report.delivery.pr_url if report.delivery and report.delivery.pr_url else "N/A"
    branch_name = report.delivery.branch_name if report.delivery and report.delivery.branch_name else "N/A"
    dry_run_text = "YES (simulation only)" if (report.delivery and report.delivery.is_dry_run) else "NO (remote published)"

    summary = f"""# DailyGreen Run Summary {status_icon}

| Field | Value |
| :--- | :--- |
| **Run ID** | `{report.run_id}` |
| **Timestamp** | `{report.timestamp}` |
| **Repository** | `{report.repo}` |
| **Overall Status** | **`{report.status.value.upper()}`** |
| **Dry Run Mode** | {dry_run_text} |
| **Task ID** | `{task_id}` |
| **Task Title** | {task_title} |
| **Branch** | `{branch_name}` |
| **Pull Request** | {pr_link} |
| **Execution Duration** | `{report.execution_duration_seconds}s` |

### Details
{report.message}
"""

    # Multi-Task Queue Execution Summary
    if report.queue_summary or (report.tasks and len(report.tasks) > 1):
        qs = report.queue_summary
        counts_line = f"**Queue Summary**: Queued: {qs.total_queued} | Completed: {qs.completed_count} | Failed: {qs.failed_count} | Skipped: {qs.skipped_count} | Retried: {qs.retried_count}" if qs else ""
        summary += f"\n### Multi-Task Execution Queue\n{counts_line}\n\n"
        summary += "| Task ID | Status | Worker | Attempts | Duration | Details / Failure |\n"
        summary += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        for t in report.tasks:
            t_status = t.status.value.upper()
            w_id = t.worker_id or "—"
            att = str(t.attempt_count)
            dur = f"{t.duration_seconds:.2f}s" if t.duration_seconds else "0.0s"
            fail = t.last_failure_reason or ("Passed" if t_status == "COMPLETED" else "—")
            summary += f"| `{t.id}` | `{t_status}` | `{w_id}` | {att} | {dur} | {fail} |\n"

    # Rejection Reason
    if report.rejection_reason:
        summary += f"\n### Rejection Reason\n> {report.rejection_reason}\n"

    # Evaluation Breakdown
    if report.evaluation:
        ev = report.evaluation
        ev_status = "PASSED" if ev.passed else "REJECTED"
        summary += f"""
### Intelligent Evaluation Scorecard (Score: {ev.overall_score}/10.0 - {ev_status})
| Evaluation Dimension | Score | Rationale |
| :--- | :--- | :--- |
| **Relevance** | {ev.relevance.score}/10 | {ev.relevance.rationale} |
| **Clarity & Completeness** | {ev.clarity_completeness.score}/10 | {ev.clarity_completeness.rationale} |
| **Technical Feasibility** | {ev.technical_feasibility.score}/10 | {ev.technical_feasibility.rationale} |
| **Expected Impact** | {ev.expected_impact.score}/10 | {ev.expected_impact.rationale} |
| **Safety & Risk Tier** | {ev.risk_assessment.score}/10 | {ev.risk_assessment.rationale} |
| **Complexity Boundedness** | {ev.estimated_complexity.score}/10 | {ev.estimated_complexity.rationale} |
| **Permissions & Dependencies** | {ev.permissions_and_dependencies.score}/10 | {ev.permissions_and_dependencies.rationale} |
"""

    # Structured Task Plan
    if report.plan:
        pl = report.plan
        steps_list = "\n".join(f"- {s}" for s in pl.implementation_steps)
        summary += f"""
### Structured Task Plan
- **Problem Statement**: {pl.problem_statement}
- **Proposed Solution**: {pl.proposed_solution}
- **Expected Behavior**: {pl.expected_behavior}
- **Implementation Steps**:
{steps_list}
"""

    # Files Analyzed and Modified
    if report.files_analyzed or report.files_modified:
        summary += "\n### Files Scope\n"
        if report.files_analyzed:
            summary += f"- **Analyzed**: {', '.join(f'`{f}`' for f in report.files_analyzed)}\n"
        if report.files_modified:
            summary += f"- **Modified**: {', '.join(f'`{f}`' for f in report.files_modified)}\n"

    # Validation Results
    if report.quality_gate and report.quality_gate.validation_details:
        val_list = "\n".join(f"- {d}" for d in report.quality_gate.validation_details)
        summary += f"\n### Validation Gate Outcomes\n{val_list}\n"

    summary += """
### GitHub Contribution Policy Notice
- **Commit Contribution Eligibility**: GitHub counts commits towards the contribution graph only when they are merged into the repository's default branch (`main`) or `gh-pages`, and when the commit author's email matches a verified GitHub account email.
- **Pull Request Eligibility**: Opening a PR will count towards your contribution profile only if PR activity tracking is enabled in your GitHub profile settings.
- **Integrity Guarantee**: DailyGreen never commits empty changes, fabricates activity, or automatically merges pull requests.
"""
    return summary


def write_github_step_summary(report: RunReport) -> None:
    """Write summary markdown to $GITHUB_STEP_SUMMARY if running in GitHub Actions."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    content = format_markdown_summary(report)
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(content + "\n\n")
    except Exception:
        pass
