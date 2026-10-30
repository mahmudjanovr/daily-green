"""Integration tests for DailyGreen Phase 2 Intelligent Agent pipeline."""

import json
from pathlib import Path
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import DailyGreenConfig, RepoConfig, SecurityPolicyConfig
from dailygreen.delivery import format_pr_body
from dailygreen.github_client import MockGitHubClient
from dailygreen.models import RunStatus, TaskSource
from dailygreen.reporting import format_markdown_summary
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager


def test_phase2_intelligent_pipeline_e2e(tmp_path: Path):
    """
    Test complete Phase 2 pipeline:
    1. Repository context analysis & intelligent issue discovery
    2. Transparent 7-dimension task evaluation
    3. Structured machine-readable planning
    4. Context-aware execution & change explanation
    5. Automated validation & unrelated file detection
    6. Machine-readable artifact persistence with full observability
    """
    # Create realistic repo on disk
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Test Repo\nDocumentation content with typo teh in intro.\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text("[project]\nname='test-pkg'\n", encoding="utf-8")

    import subprocess
    subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "bot@dailygreen.local"], cwd=str(workspace), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DailyGreen Bot"], cwd=str(workspace), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(workspace), capture_output=True, check=True)

    repo_cfg = RepoConfig(
        name="test-org/test-repo",
        allowed_paths=["README.md", "docs/**"],
        supported_task_types=["doc_typos", "issue_task"],
    )

    state_dir = tmp_path / ".dailygreen"
    config = DailyGreenConfig(
        enabled=True,
        dry_run=True,
        allow_live_mutations=False,
        repos=[repo_cfg],
        policy=SecurityPolicyConfig(),
        state_dir=str(state_dir),
    )

    github_client = MockGitHubClient()
    state_mgr = StateManager(state_dir=state_dir)
    ai_adapter = MockAIAdapter()

    # Run the upgraded intelligent pipeline in worker-only mode to generate sealed artifact
    report = execute_dailygreen_pipeline(
        repo_config=repo_cfg,
        config=config,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        source_dir=workspace,
        worker_only=True,
    )

    # 1. Pipeline Status & Observability
    assert report.status == RunStatus.TASK_COMPLETED
    assert report.task is not None
    assert report.execution_duration_seconds > 0

    # 2. Evaluation scorecard attached and passed
    assert report.evaluation is not None
    assert report.evaluation.passed is True
    assert report.evaluation.overall_score >= 6.5
    assert report.evaluation.relevance.score > 0
    assert report.evaluation.clarity_completeness.score > 0
    assert report.evaluation.technical_feasibility.score > 0

    # 3. Structured task plan generated
    assert report.plan is not None
    assert report.plan.task_id == report.task.id
    assert len(report.plan.implementation_steps) >= 1
    assert "README.md" in report.plan.change_explanations

    # 4. Files scope tracked
    assert "README.md" in report.files_analyzed
    assert "README.md" in report.files_modified

    # 5. Validation details recorded
    assert report.quality_gate is not None
    assert report.quality_gate.passed is True
    assert report.quality_gate.acceptance_criteria_verified is True
    assert len(report.quality_gate.validation_details) >= 3

    # 6. Sealed artifact contains full Phase 2 intelligence data
    sealed_path = state_dir / "sealed_task.json"
    assert sealed_path.exists()
    with open(sealed_path, "r", encoding="utf-8") as f:
        artifact = json.load(f)

    assert artifact["repo"] == "test-org/test-repo"
    assert artifact["evaluation"]["overall_score"] == report.evaluation.overall_score
    assert artifact["plan"]["task_id"] == report.task.id
    assert artifact["files_analyzed"] == report.files_analyzed
    assert artifact["files_modified"] == report.files_modified
    assert artifact["duration_seconds"] > 0
    assert len(artifact["validation_details"]) >= 3

    # 7. Summary and PR body formatting include Phase 2 intelligence
    summary_md = format_markdown_summary(report)
    assert "Intelligent Evaluation Scorecard" in summary_md
    assert "Structured Task Plan" in summary_md
    assert "Validation Gate Outcomes" in summary_md
    assert "Execution Duration" in summary_md

    pr_body = format_pr_body(report.task, report.quality_gate, artifact["diff_text"])
    assert "Implementation Plan" in pr_body
    assert "Task Evaluation Score" in pr_body
