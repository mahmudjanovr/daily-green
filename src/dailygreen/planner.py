"""Structured task planning engine generating machine-readable implementation plans."""

from pathlib import Path
from typing import Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.config import RepoConfig
from dailygreen.models import Task, TaskPlan, TaskSource


def create_task_plan(
    task: Task,
    workspace_dir: Path,
    repo_config: RepoConfig,
    ai_adapter: Optional[AIAdapter] = None,
) -> TaskPlan:
    """
    Generate a machine-readable TaskPlan containing:
    - Problem statement
    - Evidence and affected files
    - Proposed solution
    - Implementation steps
    - Expected behavior
    - Tests required
    - Risk assessment
    - Acceptance criteria
    - Explanations for why each change is necessary
    """
    meta = task.metadata or {}
    evidence: list[str] = list(task.evidence or [])
    change_explanations: dict[str, str] = {}
    implementation_steps: list[str] = []
    tests_required: list[str] = []

    # Assemble test commands from repo_config
    if repo_config.baseline_command:
        tests_required.append("Baseline: " + " ".join(repo_config.baseline_command))
    for t_cmd in repo_config.test_commands:
        tests_required.append("Test: " + " ".join(t_cmd))
    for l_cmd in repo_config.lint_commands:
        tests_required.append("Lint: " + " ".join(l_cmd))
    if not tests_required:
        tests_required.append(f"Task validation strategy: {task.validation_strategy}")

    # 1. Deterministic Link Fixes
    if meta.get("broken_target"):
        broken_target = meta["broken_target"]
        problem_statement = (
            f"Documentation file '{task.target_files[0]}' contains broken relative link target '{broken_target}' "
            "which does not resolve to an existing file."
        )
        evidence.append(f"Broken link target: '{broken_target}' in {task.target_files[0]}")
        proposed_solution = (
            f"Safely correct or neutralize broken link reference '{broken_target}' in '{task.target_files[0]}' "
            "so users and navigation tools do not encounter broken links."
        )
        implementation_steps = [
            f"1. Open '{task.target_files[0]}' and locate markdown link reference to '{broken_target}'",
            "2. Determine if a matching target file exists with case or path variance",
            "3. If found, update link to point to existing file; otherwise neutralize to code reference",
            "4. Verify that the link syntax in markdown is valid and no unintended content is altered",
        ]
        expected_behavior = (
            f"All relative links in '{task.target_files[0]}' resolve to existing files or valid anchors."
        )
        risk_assessment = (
            "Minimal risk. Modification affects documentation markdown links only, leaving runtime behavior untouched."
        )
        for f in task.target_files:
            change_explanations[f] = f"Update link target '{broken_target}' to ensure reliable documentation navigation."

    # 2. Deterministic Typo Fixes
    elif meta.get("typo") and meta.get("replacement"):
        typo = meta["typo"]
        replacement = meta["replacement"]
        problem_statement = (
            f"File '{task.target_files[0]}' contains reproducible spelling defect '{typo}'."
        )
        evidence.append(f"Found typo '{typo}' -> replacement '{replacement}' in {task.target_files[0]}")
        proposed_solution = (
            f"Replace word '{typo}' with correct spelling '{replacement}' while preserving word casing."
        )
        implementation_steps = [
            f"1. Inspect '{task.target_files[0]}' for occurrences of '{typo}' using word-boundary matching",
            f"2. Replace with '{replacement}', matching original letter casing (UPPERCASE, Capitalized, or lowercase)",
            "3. Ensure surrounding punctuation and text are preserved exactly",
            "4. Verify no syntax errors are introduced",
        ]
        expected_behavior = (
            f"Typo '{typo}' is removed from '{task.target_files[0]}' and replaced with '{replacement}'."
        )
        risk_assessment = "Low risk. Limited to single-word typographical correction in documentation."
        for f in task.target_files:
            change_explanations[f] = f"Correct typo '{typo}' to '{replacement}' to improve documentation quality."

    # 3. Deterministic Formatting Fixes
    elif meta.get("format_type") == "whitespace_and_eof":
        problem_statement = (
            f"Documentation file '{task.target_files[0]}' contains trailing whitespace or is missing a trailing newline."
        )
        evidence.append(f"Whitespace / EOF newline discrepancy in {task.target_files[0]}")
        proposed_solution = (
            f"Strip trailing whitespace from lines in '{task.target_files[0]}' and ensure clean EOF newline."
        )
        implementation_steps = [
            f"1. Read contents of '{task.target_files[0]}'",
            "2. Strip trailing whitespace from every line",
            "3. Append a single newline character if missing at EOF",
            "4. Verify line count and visible text content remain unchanged",
        ]
        expected_behavior = (
            f"'{task.target_files[0]}' has clean line endings without git whitespace warnings."
        )
        risk_assessment = "Zero functional risk. Formatting cleanup only."
        for f in task.target_files:
            change_explanations[f] = "Eliminate trailing whitespace and enforce standard trailing newline."

    # 4. Backlog / Issue / AI Tasks
    else:
        problem_statement = task.description or task.title
        for f in task.target_files:
            evidence.append(f"Target file: {f}")
        proposed_solution = task.rationale or f"Implement requirements for {task.title}"
        implementation_steps = [
            f"1. Analyze existing content in target files: {', '.join(task.target_files)}",
            "2. Generate focused modifications satisfying all acceptance criteria",
            "3. Validate changes stay within policy bounds and allowed paths",
            "4. Run validation test suite to confirm zero regressions",
        ]
        expected_behavior = (
            f"Requirements of task '{task.id}' satisfied while preserving all existing repository functionality."
        )
        risk_assessment = f"Risk tier: {task.risk_level.value}. Bounded strictly to permitted target files."
        for f in task.target_files:
            change_explanations[f] = f"Apply focused changes necessary to resolve '{task.title}'."

    # If AI adapter is available and has custom plan generation capability
    if ai_adapter and hasattr(ai_adapter, "create_plan") and task.source in (TaskSource.AI, TaskSource.ISSUE):
        try:
            ai_plan = ai_adapter.create_plan(
                task,
                {"repo_name": repo_config.name, "tests_required": tests_required, "evidence": evidence},
            )
            if ai_plan:
                return ai_plan
        except Exception:
            pass  # Fallback to structured deterministic plan

    return TaskPlan(
        task_id=task.id,
        problem_statement=problem_statement,
        evidence_and_affected_files=evidence + task.target_files,
        proposed_solution=proposed_solution,
        implementation_steps=implementation_steps,
        expected_behavior=expected_behavior,
        tests_required=tests_required,
        risk_assessment=risk_assessment,
        acceptance_criteria=list(task.acceptance_criteria),
        change_explanations=change_explanations,
    )
