"""Unit tests for structured logging and GitHub summary reporting."""

import json
import logging
from dailygreen.models import DeliveryResult, RunReport, RunStatus, Task, TaskSource
from dailygreen.reporting import StructuredJSONFormatter, format_markdown_summary


def test_structured_json_formatter():
    formatter = StructuredJSONFormatter()
    record = logging.LogRecord(
        name="dailygreen",
        level=logging.INFO,
        pathname="cli.py",
        lineno=10,
        msg="Pipeline started successfully",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)
    assert data["level"] == "INFO"
    assert data["message"] == "Pipeline started successfully"
    assert "timestamp" in data


def test_format_markdown_summary():
    report = RunReport(
        run_id="run-1234",
        repo="my-org/my-repo",
        status=RunStatus.DRY_RUN_COMPLETED,
        task=Task(
            id="task-format",
            repo="my-org/my-repo",
            title="Clean whitespace",
            description="Format markdown",
            rationale="Clean repo",
            validation_strategy="docs",
            source=TaskSource.DETERMINISTIC,
        ),
        delivery=DeliveryResult(
            success=True,
            branch_name="dailygreen/2026-10-29-task-format",
            is_dry_run=True,
            message="Simulated PR delivery",
        ),
        message="Dry-run completed.",
    )

    md = format_markdown_summary(report)
    assert "# DailyGreen Run Summary" in md
    assert "DRY_RUN_COMPLETED" in md
    assert "my-org/my-repo" in md
    assert "dailygreen/2026-10-29-task-format" in md
    assert "GitHub Contribution Policy Notice" in md
