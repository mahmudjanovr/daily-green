"""Intelligent task discovery engine with contextual analysis, issue intelligence, evaluation, and planning."""

import os
import re
from pathlib import Path
from typing import Any, Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.evaluation import evaluate_task
from dailygreen.github_client import GitHubClient
from dailygreen.models import (
    DiscoverySummary,
    IssueAnalysis,
    IssueStatus,
    RiskLevel,
    Task,
    TaskCategory,
    TaskSource,
    TaskStatus,
)
from dailygreen.planner import create_task_plan
from dailygreen.repo_analyzer import (
    COMMON_DOC_TYPOS,
    MD_LINK_PATTERN,
    analyze_github_issue,
    analyze_repository_context,
    find_candidate_allowed_files,
)
from dailygreen.security import is_path_allowed
from dailygreen.state import StateManager
from dailygreen.task_engine import format_markdown_content
from dailygreen.task_queue import TaskQueue


def discover_issue_tasks(
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    workspace_dir: Optional[Path] = None,
) -> list[Task]:
    """
    Discover open issues explicitly labeled 'dailygreen' on GitHub.
    Uses intelligent issue analysis to detect duplicates, stale issues,
    ambiguous requests, and already-resolved defects.
    """
    tasks: list[Task] = []
    if "issue_task" not in repo_config.supported_task_types:
        return []

    try:
        issues = github_client.get_labeled_issues(repo_config.name, label="dailygreen")
    except Exception:
        return []

    effective_workspace = workspace_dir if workspace_dir and workspace_dir.exists() else Path(".")

    for issue in issues:
        issue_number = issue.get("number", 0)
        task_id = f"issue-{issue_number}"

        # Check idempotency
        if state_mgr.is_task_already_done(repo_config.name, task_id):
            continue

        # Run intelligent issue analysis
        analysis = analyze_github_issue(
            issue=issue,
            workspace_dir=effective_workspace,
            repo_config=repo_config,
            policy=policy,
            state_mgr=state_mgr,
            other_issues=issues,
        )

        # Only actionable issues proceed to candidate tasks
        if analysis.status != IssueStatus.ACTIONABLE:
            continue

        title = issue.get("title", "").strip()
        body = issue.get("body", "").strip()

        deps: list[str] = []
        dep_matches = re.findall(r"(?:depends on|prerequisite:?)\s*#?([0-9]+)", body, re.IGNORECASE)
        for d in dep_matches:
            deps.append(f"issue-{d}")

        tasks.append(
            Task(
                id=task_id,
                repo=repo_config.name,
                title=f"Fix issue #{issue_number}: {title}",
                description=body[:1000] if body else title,
                rationale=f"Addresses open GitHub issue #{issue_number} labeled 'dailygreen'",
                acceptance_criteria=analysis.acceptance_criteria,
                risk_level=RiskLevel.LOW,
                validation_strategy="issue_verification",
                source=TaskSource.ISSUE,
                category=analysis.category,
                target_files=analysis.target_files,
                dependencies=deps,
                metadata={
                    "issue_number": issue_number,
                    "issue_url": issue.get("html_url"),
                    "analysis": analysis.model_dump(),
                },
            )
        )

    return tasks


def discover_backlog_tasks(
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
) -> list[Task]:
    """Discover curated local backlog items configured for the repository."""
    tasks: list[Task] = []
    if "curated_backlog" not in repo_config.supported_task_types:
        return []

    for item in repo_config.curated_tasks:
        task_id = str(item.get("id", ""))
        if not task_id or state_mgr.is_task_already_done(repo_config.name, task_id):
            continue

        target_files = list(item.get("target_files", []))
        # Validate that target files are allowed
        safe_targets: list[str] = []
        for f in target_files:
            allowed, _ = is_path_allowed(f, repo_config, policy)
            if allowed:
                safe_targets.append(f)

        if not safe_targets:
            continue

        title = str(item.get("title", f"Backlog task: {task_id}"))
        description = str(item.get("description", title))
        raw_ac = list(item.get("acceptance_criteria", []))
        if not raw_ac:
            raw_ac = [f"Safely fulfill {title} requirements within {', '.join(safe_targets)}"]
        deps = list(item.get("dependencies", []))

        tasks.append(
            Task(
                id=task_id,
                repo=repo_config.name,
                title=title,
                description=description,
                rationale=str(item.get("rationale", "Curated maintenance task from repository configuration")),
                acceptance_criteria=raw_ac,
                risk_level=RiskLevel(item.get("risk_level", "low")),
                validation_strategy=str(item.get("validation_strategy", "verify")),
                source=TaskSource.BACKLOG,
                category=TaskCategory.MAINTENANCE,
                target_files=safe_targets,
                patch=item.get("patch"),
                dependencies=deps,
                metadata=item,
            )
        )

    return tasks


def find_candidate_markdown_files(workspace_dir: Path, repo_config: RepoConfig, policy: SecurityPolicyConfig) -> list[Path]:
    """Find all markdown files in workspace that are within allowed paths, ignoring vendor directories."""
    candidates: list[Path] = []
    ignored_dirs = {".git", "node_modules", ".venv", "venv", "dist", ".astro", "__pycache__"}
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                full_path = Path(root) / f
                try:
                    rel_path = full_path.relative_to(workspace_dir).as_posix()
                    allowed, _ = is_path_allowed(rel_path, repo_config, policy)
                    if allowed:
                        candidates.append(full_path)
                except ValueError:
                    continue
    return sorted(candidates)


def discover_deterministic_link_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
    limit: Optional[int] = 1,
) -> list[Task]:
    """Check for broken internal markdown links."""
    if "doc_links" not in repo_config.supported_task_types:
        return []

    tasks: list[Task] = []
    md_files = find_candidate_markdown_files(workspace_dir, repo_config, policy)
    for md_file in md_files:
        rel_path = md_file.relative_to(workspace_dir).as_posix()
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for match in MD_LINK_PATTERN.finditer(content):
            link_target = match.group(2).strip()
            # Ignore external URLs, mailto, and pure anchor links
            if link_target.startswith(("http://", "https://", "mailto:", "#")):
                continue

            target_clean = link_target.split("#")[0].split("?")[0]
            if not target_clean:
                continue

            # Check if target exists relative to md_file directory
            target_path = (md_file.parent / target_clean).resolve()
            if not target_path.exists():
                task_id = f"fix-broken-link-{rel_path.replace('/', '-')}"
                if state_mgr.is_task_already_done(repo_config.name, task_id):
                    continue
                if any(t.id == task_id for t in tasks):
                    continue

                tasks.append(
                    Task(
                        id=task_id,
                        repo=repo_config.name,
                        title=f"Fix broken relative link in {rel_path}",
                        description=f"Documentation file '{rel_path}' contains broken relative link target '{link_target}'.",
                        rationale="Ensures repository documentation navigation is functional and links resolve properly.",
                        acceptance_criteria=[f"Verify link target in '{rel_path}' is corrected or removed"],
                        risk_level=RiskLevel.LOW,
                        validation_strategy="markdown_link_verification",
                        source=TaskSource.DETERMINISTIC,
                        category=TaskCategory.DOCUMENTATION,
                        target_files=[rel_path],
                        metadata={"broken_target": link_target, "source_file": rel_path},
                    )
                )
                if limit is not None and len(tasks) >= limit:
                    return tasks
    return tasks


def discover_deterministic_formatting_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
    limit: Optional[int] = 1,
) -> list[Task]:
    """Check for trailing whitespace or missing EOF newlines in documentation."""
    if "doc_formatting" not in repo_config.supported_task_types:
        return []

    tasks: list[Task] = []
    md_files = find_candidate_markdown_files(workspace_dir, repo_config, policy)
    for md_file in md_files:
        rel_path = md_file.relative_to(workspace_dir).as_posix()
        task_id = f"format-{rel_path.replace('/', '-')}"
        if state_mgr.is_task_already_done(repo_config.name, task_id):
            continue
        if any(t.id == task_id for t in tasks):
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        _, needs_fix = format_markdown_content(content)

        if needs_fix:
            tasks.append(
                Task(
                    id=task_id,
                    repo=repo_config.name,
                    title=f"Standardize documentation formatting in {rel_path}",
                    description=f"Remove trailing whitespace and ensure trailing newline in '{rel_path}'.",
                    rationale="Enforces clean, standard Markdown formatting across repository documentation.",
                    acceptance_criteria=[
                        f"Lines in '{rel_path}' have no trailing whitespace",
                        f"'{rel_path}' ends with a single newline character",
                    ],
                    risk_level=RiskLevel.LOW,
                    validation_strategy="formatting_verification",
                    source=TaskSource.DETERMINISTIC,
                    category=TaskCategory.DOCUMENTATION,
                    target_files=[rel_path],
                    metadata={"format_type": "whitespace_and_eof"},
                )
            )
            if limit is not None and len(tasks) >= limit:
                return tasks
    return tasks


def discover_deterministic_typo_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
    limit: Optional[int] = 1,
) -> list[Task]:
    """Check for reproducible common typos in documentation."""
    if "doc_typos" not in repo_config.supported_task_types:
        return []

    tasks: list[Task] = []
    md_files = find_candidate_markdown_files(workspace_dir, repo_config, policy)
    for md_file in md_files:
        rel_path = md_file.relative_to(workspace_dir).as_posix()
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for typo, fix in COMMON_DOC_TYPOS.items():
            pattern = re.compile(rf"\b{typo}\b", re.IGNORECASE)
            if pattern.search(content):
                task_id = f"typo-{typo}-{rel_path.replace('/', '-')}"
                if state_mgr.is_task_already_done(repo_config.name, task_id):
                    continue
                if any(t.id == task_id for t in tasks):
                    continue

                tasks.append(
                    Task(
                        id=task_id,
                        repo=repo_config.name,
                        title=f"Correct common typo '{typo}' -> '{fix}' in {rel_path}",
                        description=f"Documentation file '{rel_path}' contains reproducible typo '{typo}'.",
                        rationale="Maintains high-quality, professional documentation in the repository.",
                        acceptance_criteria=[f"Typo '{typo}' is corrected to '{fix}' in '{rel_path}'"],
                        risk_level=RiskLevel.LOW,
                        validation_strategy="typo_verification",
                        source=TaskSource.DETERMINISTIC,
                        category=TaskCategory.DOCUMENTATION,
                        target_files=[rel_path],
                        metadata={"typo": typo, "replacement": fix},
                    )
                )
                if limit is not None and len(tasks) >= limit:
                    return tasks
    return tasks


def discover_ai_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    ai_adapter: AIAdapter,
    state_mgr: StateManager,
) -> list[Task]:
    """Propose AI-assisted tasks strictly when enabled and permitted by policy."""
    if not repo_config.allow_ai_tasks:
        return []

    md_files = find_candidate_markdown_files(workspace_dir, repo_config, policy)
    file_list = [f.relative_to(workspace_dir).as_posix() for f in md_files]
    if not file_list:
        return []

    context = {
        "repo_name": repo_config.name,
        "allowed_paths": repo_config.allowed_paths,
        "file_list": file_list,
    }

    try:
        proposed = ai_adapter.propose_tasks(context)
    except Exception:
        return []

    valid_tasks: list[Task] = []
    for t in proposed:
        if t.risk_level != RiskLevel.LOW:
            continue
        if state_mgr.is_task_already_done(repo_config.name, t.id):
            continue

        safe_files: list[str] = []
        for target in t.target_files:
            allowed, _ = is_path_allowed(target, repo_config, policy)
            if allowed:
                safe_files.append(target)

        if not safe_files:
            continue

        t.target_files = safe_files
        valid_tasks.append(t)

    return valid_tasks


def discover_and_evaluate_queue(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    ai_adapter: Optional[AIAdapter] = None,
    max_tasks: Optional[int] = None,
) -> tuple[TaskQueue, DiscoverySummary]:
    """
    Intelligently discover, evaluate, and plan multiple tasks into a dependency-aware TaskQueue.
    """
    effective_max = max_tasks if (max_tasks is not None and max_tasks > 0) else repo_config.max_tasks_per_run
    queue = TaskQueue(repo=repo_config.name, max_tasks=effective_max, state_dir=state_mgr.state_dir)
    # DG3-03: Recover persisted queue before discovery proceeds
    queue.recover(state_mgr=state_mgr)
    repo_context = analyze_repository_context(workspace_dir, repo_config, policy)

    issues_analyzed: list[IssueAnalysis] = []
    evaluations: list[dict[str, Any]] = []
    candidates: list[Task] = []

    # 1. Candidate gathering
    issue_tasks = discover_issue_tasks(
        repo_config=repo_config,
        policy=policy,
        github_client=github_client,
        state_mgr=state_mgr,
        workspace_dir=workspace_dir,
    )
    for t in issue_tasks:
        analysis_dict = t.metadata.get("analysis")
        if analysis_dict:
            try:
                issues_analyzed.append(IssueAnalysis(**analysis_dict))
            except Exception:
                pass

    if effective_max == 1:
        # Strict single-task priority cascade
        candidates.extend(issue_tasks)
        if not candidates:
            candidates.extend(discover_backlog_tasks(repo_config, policy, state_mgr))
        if not candidates:
            candidates.extend(discover_deterministic_link_tasks(workspace_dir, repo_config, policy, state_mgr, limit=1))
        if not candidates:
            candidates.extend(discover_deterministic_formatting_tasks(workspace_dir, repo_config, policy, state_mgr, limit=1))
        if not candidates:
            candidates.extend(discover_deterministic_typo_tasks(workspace_dir, repo_config, policy, state_mgr, limit=1))
        if not candidates and repo_config.allow_ai_tasks and ai_adapter:
            candidates.extend(discover_ai_tasks(workspace_dir, repo_config, policy, ai_adapter, state_mgr))
    else:
        # Multi-task gathering: gather across available sources up to candidate pool
        candidates.extend(issue_tasks)
        target_pool = max(effective_max * 2, 5)
        if len(candidates) < target_pool:
            candidates.extend(discover_backlog_tasks(repo_config, policy, state_mgr))
        if len(candidates) < target_pool:
            remaining = target_pool - len(candidates)
            candidates.extend(discover_deterministic_link_tasks(workspace_dir, repo_config, policy, state_mgr, limit=remaining))
        if len(candidates) < target_pool:
            remaining = target_pool - len(candidates)
            candidates.extend(discover_deterministic_formatting_tasks(workspace_dir, repo_config, policy, state_mgr, limit=remaining))
        if len(candidates) < target_pool:
            remaining = target_pool - len(candidates)
            candidates.extend(discover_deterministic_typo_tasks(workspace_dir, repo_config, policy, state_mgr, limit=remaining))
        if len(candidates) < target_pool and repo_config.allow_ai_tasks and ai_adapter:
            candidates.extend(discover_ai_tasks(workspace_dir, repo_config, policy, ai_adapter, state_mgr))

    # Deduplicate candidates preserving order
    seen_ids: set[str] = set()
    unique_candidates: list[Task] = []
    for c in candidates:
        if c.id not in seen_ids:
            seen_ids.add(c.id)
            unique_candidates.append(c)

    selected_ids: list[str] = []

    # 2. Structured Task Evaluation and Planning
    for candidate in unique_candidates:
        active_count = sum(1 for t in queue.get_all_tasks() if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRY_SCHEDULED))
        if active_count >= effective_max:
            break

        evaluation = evaluate_task(
            task=candidate,
            workspace_dir=workspace_dir,
            repo_context=repo_context,
            repo_config=repo_config,
            policy=policy,
        )
        candidate.evaluation = evaluation
        evaluations.append({
            "task_id": candidate.id,
            "overall_score": evaluation.overall_score,
            "passed": evaluation.passed,
            "rejection_reason": evaluation.rejection_reason,
            "explanation": evaluation.explanation,
        })

        if evaluation.passed:
            plan = create_task_plan(
                task=candidate,
                workspace_dir=workspace_dir,
                repo_config=repo_config,
                ai_adapter=ai_adapter,
            )
            candidate.plan = plan
            enqueued = queue.enqueue(candidate)
            if enqueued:
                selected_ids.append(candidate.id)

    # 3. Resolve dependencies & cycle detection
    queue.resolve_dependencies(state_mgr=state_mgr)

    summary = DiscoverySummary(
        candidates_found=len(unique_candidates),
        issues_analyzed=issues_analyzed,
        evaluations=evaluations,
        selected_task_id=selected_ids[0] if selected_ids else None,
        selected_task_ids=selected_ids,
    )

    return queue, summary


def discover_and_evaluate_task(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    ai_adapter: Optional[AIAdapter] = None,
) -> tuple[Optional[Task], DiscoverySummary]:
    """
    Intelligently discover, evaluate, and plan the highest-scoring legitimate task.
    Returns (task, summary) where summary contains all discovery details and evaluation scorecards.
    """
    queue, summary = discover_and_evaluate_queue(
        workspace_dir=workspace_dir,
        repo_config=repo_config,
        policy=policy,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
        max_tasks=1,
    )
    ready = queue.get_ready_tasks(state_mgr=state_mgr)
    selected_task = ready[0] if ready else None
    return selected_task, summary


def discover_next_task(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    ai_adapter: Optional[AIAdapter] = None,
) -> Optional[Task]:
    """
    Select exactly one legitimate task following strict priority and intelligent evaluation:
    1. GitHub Issues labeled 'dailygreen'
    2. Curated local backlog items
    3. Deterministic maintenance checks (broken links, formatting, typos)
    4. AI-assisted proposals (if enabled)
    Returns None if no task is found or if candidates fail evaluation.
    """
    task, _ = discover_and_evaluate_task(
        workspace_dir=workspace_dir,
        repo_config=repo_config,
        policy=policy,
        github_client=github_client,
        state_mgr=state_mgr,
        ai_adapter=ai_adapter,
    )
    return task
