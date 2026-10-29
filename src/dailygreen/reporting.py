"""Structured JSON logging and GitHub Step Summary reporting."""

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
    Format a GitHub Actions Job Step Summary in GitHub Flavored Markdown.
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

### Details
{report.message}

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
