"""Structured task evaluation engine assessing relevance, feasibility, risk, and impact."""

from pathlib import Path
from typing import Any, Optional
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import RiskLevel, ScoreDetail, Task, TaskEvaluation, TaskSource
from dailygreen.repo_analyzer import RepoContext
from dailygreen.security import is_path_allowed


EVALUATION_PASSING_THRESHOLD = 6.5


def evaluate_task(
    task: Task,
    workspace_dir: Path,
    repo_context: RepoContext,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
) -> TaskEvaluation:
    """
    Evaluate a candidate task across 7 transparent dimensions:
    1. Relevance to the repository (15%)
    2. Clarity and completeness (15%)
    3. Technical feasibility (20%)
    4. Expected impact (15%)
    5. Risk of breaking existing behavior (15%, higher = safer)
    6. Estimated complexity (10%, higher = more bounded/focused)
    7. Required permissions and dependencies (10%)

    Enforces strict hard rejection gates for dangerous, ambiguous, or unsupported tasks.
    """
    hard_rejections: list[str] = []

    # --- Hard Gate 1: Path Policy & Forbidden Paths ---
    if not task.target_files:
        hard_rejections.append("Task specifies no target files.")

    for f in task.target_files:
        allowed, reason = is_path_allowed(f, repo_config, policy)
        if not allowed:
            hard_rejections.append(f"Target path '{f}' violates repository security policy: {reason}")

    # --- Hard Gate 2: Evidence & File Existence ---
    missing_files: list[str] = []
    for f in task.target_files:
        p = workspace_dir / f
        if not p.exists() or not p.is_file():
            missing_files.append(f)

    # For deterministic tasks, target files MUST exist in the workspace
    if task.source == TaskSource.DETERMINISTIC and missing_files:
        hard_rejections.append(
            f"Deterministic task targets missing file(s): {missing_files}."
        )

    # --- Hard Gate 3: Scope Bounds & File Count ---
    if len(task.target_files) > 10:
        hard_rejections.append(
            f"Task is too broad: affects {len(task.target_files)} files (maximum bounded limit is 10)."
        )

    # --- Hard Gate 4: Clarity & Acceptance Criteria ---
    has_empty_criteria = not task.acceptance_criteria or all(not str(ac).strip() for ac in task.acceptance_criteria)
    if has_empty_criteria:
        if len(task.title.strip()) < 10 and len(task.description.strip()) < 10:
            hard_rejections.append("Task is ambiguous: description and title lack sufficient detail and no acceptance criteria provided.")
        elif task.title and len(task.title.strip()) >= 10:
            task.acceptance_criteria = [f"Safely fulfill requirements of '{task.title}'"]
        else:
            hard_rejections.append("Task is ambiguous: no measurable acceptance criteria or clear title provided.")

    if len(task.description.strip()) < 3 and len(task.title.strip()) < 3:
        hard_rejections.append("Task is ambiguous: description and title lack sufficient detail.")

    # --- Dimension 1: Relevance to Repository (Weight: 15%) ---
    relevance_score = 7.0
    rel_reasons = []
    if any(f in ("README.md", "readme.md") for f in task.target_files):
        relevance_score += 2.5
        rel_reasons.append("Targets root README documentation directly visible to users")
    elif any(f.startswith("docs/") for f in task.target_files):
        relevance_score += 1.5
        rel_reasons.append("Targets official project documentation")

    # Match supported task types
    if task.source.value in repo_config.supported_task_types or any(
        t in task.id for t in repo_config.supported_task_types
    ):
        relevance_score += 0.5
        rel_reasons.append("Matches configured repository supported task types")

    relevance_score = min(10.0, max(0.0, relevance_score))
    relevance_detail = ScoreDetail(
        score=round(relevance_score, 1),
        rationale="; ".join(rel_reasons) or "Task aligns with general repository maintenance scope",
    )

    # --- Dimension 2: Clarity and Completeness (Weight: 15%) ---
    clarity_score = 5.0
    clarity_reasons = []
    if len(task.acceptance_criteria) >= 1:
        clarity_score += 2.5
        clarity_reasons.append(f"Provides {len(task.acceptance_criteria)} specific acceptance criteria")
    if task.rationale and len(task.rationale.strip()) > 15:
        clarity_score += 1.5
        clarity_reasons.append("Detailed rationale articulated")
    if task.target_files:
        clarity_score += 1.0
        clarity_reasons.append(f"Explicit target files specified: {task.target_files}")

    clarity_score = min(10.0, max(0.0, clarity_score))
    clarity_detail = ScoreDetail(
        score=round(clarity_score, 1),
        rationale="; ".join(clarity_reasons) or "Adequate task description",
    )

    # --- Dimension 3: Technical Feasibility (Weight: 20%) ---
    feasibility_score = 9.0
    feas_reasons = []
    if not missing_files:
        feas_reasons.append("All target files verified present in workspace")
    else:
        feasibility_score -= 2.0
        feas_reasons.append(f"Target file(s) not currently on disk (new file creation): {missing_files}")

    if task.validation_strategy:
        feas_reasons.append(f"Established validation strategy: '{task.validation_strategy}'")
    else:
        feasibility_score -= 2.0
        feas_reasons.append("No explicit validation strategy specified")

    feasibility_score = min(10.0, max(0.0, feasibility_score))
    feasibility_detail = ScoreDetail(
        score=round(feasibility_score, 1),
        rationale="; ".join(feas_reasons),
    )

    # --- Dimension 4: Expected Impact (Weight: 15%) ---
    impact_score = 7.0
    impact_reasons = []
    if "link" in task.id or "link" in task.validation_strategy:
        impact_score = 9.0
        impact_reasons.append("Prevents dead-end navigation for developers and contributors")
    elif "typo" in task.id:
        impact_score = 8.0
        impact_reasons.append("Corrects visible spelling defect, elevating documentation quality")
    elif "format" in task.id:
        impact_score = 7.5
        impact_reasons.append("Standardizes formatting and eliminates git whitespace warnings")
    else:
        impact_reasons.append("Contributes to overall code health and project maintenance")

    impact_score = min(10.0, max(0.0, impact_score))
    impact_detail = ScoreDetail(
        score=round(impact_score, 1),
        rationale="; ".join(impact_reasons),
    )

    # --- Dimension 5: Risk of Breaking Existing Behavior (Weight: 15%) ---
    # Higher score = lower risk (safer)
    if task.risk_level == RiskLevel.LOW:
        risk_score = 9.5
        risk_reason = "Low risk tier: bounded text/doc modification with zero runtime code impact"
    elif task.risk_level == RiskLevel.MEDIUM:
        risk_score = 6.0
        risk_reason = "Medium risk tier: non-trivial changes require automated test pass"
    else:
        risk_score = 2.0
        risk_reason = "High risk tier: substantial changes with potential regression side effects"

    risk_detail = ScoreDetail(
        score=round(risk_score, 1),
        rationale=risk_reason,
    )

    # --- Dimension 6: Estimated Complexity (Weight: 10%) ---
    # Higher score = more bounded/focused/manageable
    num_files = len(task.target_files)
    if num_files == 1:
        complexity_score = 9.5
        comp_reason = "Single-file modification; tightly bounded"
    elif num_files <= 3:
        complexity_score = 8.0
        comp_reason = f"Multi-file modification across {num_files} files; moderate complexity"
    else:
        complexity_score = 4.0
        comp_reason = f"Spans {num_files} files; high complexity"

    complexity_detail = ScoreDetail(
        score=round(complexity_score, 1),
        rationale=comp_reason,
    )

    # --- Dimension 7: Permissions and Dependencies (Weight: 10%) ---
    perm_score = 10.0
    perm_reasons = ["Zero external permissions or additional dependencies required"]

    perm_detail = ScoreDetail(
        score=round(perm_score, 1),
        rationale="; ".join(perm_reasons),
    )

    # --- Composite Weighted Score Calculation ---
    # Weights: rel=0.15, clar=0.15, feas=0.20, imp=0.15, risk=0.15, comp=0.10, perm=0.10
    composite_score = (
        0.15 * relevance_score
        + 0.15 * clarity_score
        + 0.20 * feasibility_score
        + 0.15 * impact_score
        + 0.15 * risk_score
        + 0.10 * complexity_score
        + 0.10 * perm_score
    )
    overall_score = round(composite_score, 2)

    # Check passing status
    passed = False
    rejection_reason = None

    if hard_rejections:
        passed = False
        rejection_reason = "Hard gate failure: " + " | ".join(hard_rejections)
    elif overall_score < EVALUATION_PASSING_THRESHOLD:
        passed = False
        rejection_reason = (
            f"Score {overall_score:.2f} is below passing threshold ({EVALUATION_PASSING_THRESHOLD})."
        )
    else:
        passed = True

    explanation = (
        f"Task '{task.id}' evaluated with overall score {overall_score}/10.0. "
        f"Passed: {passed}. "
        f"[Relevance: {relevance_score}/10, Feasibility: {feasibility_score}/10, "
        f"Clarity: {clarity_score}/10, Impact: {impact_score}/10, "
        f"Safety: {risk_score}/10, Complexity: {complexity_score}/10, Permissions: {perm_score}/10]"
    )

    return TaskEvaluation(
        overall_score=overall_score,
        passed=passed,
        rejection_reason=rejection_reason,
        relevance=relevance_detail,
        clarity_completeness=clarity_detail,
        technical_feasibility=feasibility_detail,
        expected_impact=impact_detail,
        risk_assessment=risk_detail,
        estimated_complexity=complexity_detail,
        permissions_and_dependencies=perm_detail,
        explanation=explanation,
    )
