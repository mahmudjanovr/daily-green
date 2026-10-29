"""Task discovery engine with strict rules-first priority."""

import os
import re
from pathlib import Path
from typing import Any, Optional
from dailygreen.ai.base import AIAdapter
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.github_client import GitHubClient
from dailygreen.models import RiskLevel, Task, TaskSource
from dailygreen.security import is_path_allowed
from dailygreen.state import StateManager


# Common documentation typos for deterministic correction
COMMON_DOC_TYPOS: dict[str, str] = {
    "teh": "the",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "occured": "occurred",
    "refering": "referring",
    "succesful": "successful",
    "accomodate": "accommodate",
}

# Regex for Markdown links: [text](target)
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def discover_issue_tasks(
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
) -> list[Task]:
    """Discover open issues explicitly labeled 'dailygreen' on GitHub."""
    tasks: list[Task] = []
    if "issue_task" not in repo_config.supported_task_types:
        return []

    try:
        issues = github_client.get_labeled_issues(repo_config.name, label="dailygreen")
    except Exception:
        return []

    for issue in issues:
        issue_number = issue.get("number")
        title = issue.get("title", "").strip()
        body = issue.get("body", "").strip()
        task_id = f"issue-{issue_number}"

        # Check idempotency
        if state_mgr.is_task_already_done(repo_config.name, task_id):
            continue

        # Extract target files mentioned in issue or default to allowed README/docs
        target_files: list[str] = []
        for line in body.splitlines():
            line_str = line.strip().lstrip("-*` ").rstrip("`")
            if any(line_str.endswith(ext) for ext in [".md", ".txt", ".rst"]):
                allowed, _ = is_path_allowed(line_str, repo_config, policy)
                if allowed:
                    target_files.append(line_str)

        if not target_files:
            # Fall back to README.md if permitted
            if any("README.md" in p for p in repo_config.allowed_paths):
                target_files = ["README.md"]
            else:
                continue

        tasks.append(
            Task(
                id=task_id,
                repo=repo_config.name,
                title=f"Fix issue #{issue_number}: {title}",
                description=body[:1000] if body else title,
                rationale=f"Addresses open GitHub issue #{issue_number} labeled 'dailygreen'",
                acceptance_criteria=[f"Resolve issue #{issue_number} requirements safely within allowed paths"],
                risk_level=RiskLevel.LOW,
                validation_strategy="issue_verification",
                source=TaskSource.ISSUE,
                target_files=target_files,
                metadata={"issue_number": issue_number, "issue_url": issue.get("html_url")},
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

        tasks.append(
            Task(
                id=task_id,
                repo=repo_config.name,
                title=str(item.get("title", f"Backlog task: {task_id}")),
                description=str(item.get("description", "")),
                rationale=str(item.get("rationale", "Curated maintenance task from repository configuration")),
                acceptance_criteria=list(item.get("acceptance_criteria", [])),
                risk_level=RiskLevel(item.get("risk_level", "low")),
                validation_strategy=str(item.get("validation_strategy", "verify")),
                source=TaskSource.BACKLOG,
                target_files=safe_targets,
                metadata=item,
            )
        )

    return tasks


def find_candidate_markdown_files(workspace_dir: Path, repo_config: RepoConfig, policy: SecurityPolicyConfig) -> list[Path]:
    """Find all markdown files in workspace that are within allowed paths."""
    candidates: list[Path] = []
    for root, _, files in os.walk(workspace_dir):
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
) -> list[Task]:
    """Check for broken internal markdown links."""
    if "doc_links" not in repo_config.supported_task_types:
        return []

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

                return [
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
                        target_files=[rel_path],
                        metadata={"broken_target": link_target, "source_file": rel_path},
                    )
                ]
    return []


def discover_deterministic_formatting_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
) -> list[Task]:
    """Check for trailing whitespace or missing EOF newlines in documentation."""
    if "doc_formatting" not in repo_config.supported_task_types:
        return []

    md_files = find_candidate_markdown_files(workspace_dir, repo_config, policy)
    for md_file in md_files:
        rel_path = md_file.relative_to(workspace_dir).as_posix()
        task_id = f"format-{rel_path.replace('/', '-')}"
        if state_mgr.is_task_already_done(repo_config.name, task_id):
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        needs_fix = False
        lines = content.splitlines(keepends=True)
        for line in lines:
            line_no_end = line.rstrip("\r\n")
            if line_no_end != line_no_end.rstrip(" \t"):
                needs_fix = True
                break

        if content and not content.endswith("\n"):
            needs_fix = True

        if needs_fix:
            return [
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
                    target_files=[rel_path],
                    metadata={"format_type": "whitespace_and_eof"},
                )
            ]
    return []


def discover_deterministic_typo_tasks(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
) -> list[Task]:
    """Check for reproducible common typos in documentation."""
    if "doc_typos" not in repo_config.supported_task_types:
        return []

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

                return [
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
                        target_files=[rel_path],
                        metadata={"typo": typo, "replacement": fix},
                    )
                ]
    return []


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
        # Validate that task is low risk and files are permitted
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


def discover_next_task(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    github_client: GitHubClient,
    state_mgr: StateManager,
    ai_adapter: Optional[AIAdapter] = None,
) -> Optional[Task]:
    """
    Select exactly one legitimate task following strict priority:
    1. GitHub Issues labeled 'dailygreen'
    2. Curated local backlog items
    3. Deterministic maintenance checks (broken links, formatting, typos)
    4. AI-assisted proposals (if enabled)
    Returns None if no task is found (reporting NO_TASK).
    """
    # 1. Issues
    issue_tasks = discover_issue_tasks(repo_config, policy, github_client, state_mgr)
    if issue_tasks:
        return issue_tasks[0]

    # 2. Curated Backlog
    backlog_tasks = discover_backlog_tasks(repo_config, policy, state_mgr)
    if backlog_tasks:
        return backlog_tasks[0]

    # 3. Deterministic checks
    # 3a. Link tasks
    link_tasks = discover_deterministic_link_tasks(workspace_dir, repo_config, policy, state_mgr)
    if link_tasks:
        return link_tasks[0]

    # 3b. Formatting tasks
    formatting_tasks = discover_deterministic_formatting_tasks(workspace_dir, repo_config, policy, state_mgr)
    if formatting_tasks:
        return formatting_tasks[0]

    # 3c. Typo tasks
    typo_tasks = discover_deterministic_typo_tasks(workspace_dir, repo_config, policy, state_mgr)
    if typo_tasks:
        return typo_tasks[0]

    # 4. AI-assisted (only if configured)
    if repo_config.allow_ai_tasks and ai_adapter:
        ai_tasks = discover_ai_tasks(workspace_dir, repo_config, policy, ai_adapter, state_mgr)
        if ai_tasks:
            return ai_tasks[0]

    return None
