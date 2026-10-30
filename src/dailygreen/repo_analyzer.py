"""Repository context analysis, project structure discovery, and issue intelligence."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import IssueAnalysis, IssueStatus, TaskCategory
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


class RepoContext(BaseModel):
    """Rich structured context of an analyzed repository."""
    repo_name: str
    default_branch: str
    project_type: str = "generic"
    readme_path: Optional[str] = None
    readme_content: Optional[str] = None
    allowed_files: list[str] = Field(default_factory=list)
    key_files: dict[str, str] = Field(default_factory=dict)
    structure_summary: dict[str, Any] = Field(default_factory=dict)
    maintenance_signals: list[dict[str, Any]] = Field(default_factory=list)


def detect_project_type(workspace_dir: Path) -> str:
    """Detect dominant project tech stack based on marker files."""
    if (workspace_dir / "pyproject.toml").exists() or (workspace_dir / "setup.py").exists() or (workspace_dir / "requirements.txt").exists():
        return "python"
    if (workspace_dir / "package.json").exists():
        return "node"
    if (workspace_dir / "Cargo.toml").exists():
        return "rust"
    if (workspace_dir / "go.mod").exists():
        return "go"
    return "generic"


def find_candidate_allowed_files(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
) -> list[str]:
    """Find all files in workspace that strictly match repository allowed_paths."""
    candidates: list[str] = []
    for root, _, files in os.walk(workspace_dir):
        # Skip hidden .git or .dailygreen directories immediately
        rel_root = os.path.relpath(root, workspace_dir)
        if rel_root.startswith(".git") or rel_root.startswith(".dailygreen"):
            continue

        for f in files:
            full_path = Path(root) / f
            try:
                rel_path = full_path.relative_to(workspace_dir).as_posix()
                allowed, _ = is_path_allowed(rel_path, repo_config, policy)
                if allowed:
                    candidates.append(rel_path)
            except ValueError:
                continue
    return sorted(candidates)


def scan_maintenance_signals(
    workspace_dir: Path,
    allowed_files: list[str],
) -> list[dict[str, Any]]:
    """Scan allowed markdown and text files for actionable maintenance signals."""
    signals: list[dict[str, Any]] = []

    for rel_path in allowed_files:
        full_path = workspace_dir / rel_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # 1. Broken Markdown Links
        if rel_path.endswith(".md"):
            for match in MD_LINK_PATTERN.finditer(content):
                link_text = match.group(1).strip()
                link_target = match.group(2).strip()
                if link_target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target_clean = link_target.split("#")[0].split("?")[0]
                if not target_clean:
                    continue
                target_path = (full_path.parent / target_clean).resolve()
                if not target_path.exists():
                    signals.append({
                        "type": "broken_link",
                        "file": rel_path,
                        "target": link_target,
                        "text": link_text,
                        "evidence": f"File '{rel_path}' references non-existent link target '{link_target}'",
                    })

        # 2. Common Typos
        for typo, fix in COMMON_DOC_TYPOS.items():
            pattern = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
            match = pattern.search(content)
            if match:
                signals.append({
                    "type": "typo",
                    "file": rel_path,
                    "typo": typo,
                    "replacement": fix,
                    "evidence": f"Typo '{typo}' found in '{rel_path}', correction: '{fix}'",
                })

        # 3. Formatting defects (trailing whitespace / missing EOF newline)
        if rel_path.endswith((".md", ".txt", ".rst")):
            has_trailing_space = False
            for line in content.splitlines(keepends=True):
                line_no_end = line.rstrip("\r\n")
                if line_no_end != line_no_end.rstrip(" \t"):
                    has_trailing_space = True
                    break
            missing_eof = bool(content and not content.endswith("\n"))
            if has_trailing_space or missing_eof:
                signals.append({
                    "type": "formatting",
                    "file": rel_path,
                    "trailing_whitespace": has_trailing_space,
                    "missing_eof_newline": missing_eof,
                    "evidence": f"Formatting defect in '{rel_path}': whitespace={has_trailing_space}, eof={missing_eof}",
                })

    return signals


def analyze_repository_context(
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
) -> RepoContext:
    """
    Perform comprehensive repository analysis:
    - Inspect project structure and metadata
    - Read README and key project files
    - Scan allowed files for maintenance signals
    """
    project_type = detect_project_type(workspace_dir)
    allowed_files = find_candidate_allowed_files(workspace_dir, repo_config, policy)

    # Locate README
    readme_path = None
    readme_content = None
    for candidate_name in ["README.md", "readme.md", "README.rst", "README.txt"]:
        candidate_p = workspace_dir / candidate_name
        if candidate_p.exists() and candidate_p.is_file():
            readme_path = candidate_name
            try:
                readme_content = candidate_p.read_text(encoding="utf-8", errors="replace")[:10000]
            except Exception:
                readme_content = None
            break

    # Key metadata files (read snippet)
    key_files: dict[str, str] = {}
    for kf in ["pyproject.toml", "package.json", "Cargo.toml", "setup.py"]:
        kp = workspace_dir / kf
        if kp.exists() and kp.is_file():
            try:
                key_files[kf] = kp.read_text(encoding="utf-8", errors="replace")[:2000]
            except Exception:
                pass

    structure_summary = {
        "project_type": project_type,
        "total_allowed_files": len(allowed_files),
        "has_readme": readme_path is not None,
        "key_marker_files": list(key_files.keys()),
    }

    signals = scan_maintenance_signals(workspace_dir, allowed_files)

    return RepoContext(
        repo_name=repo_config.name,
        default_branch=repo_config.default_branch,
        project_type=project_type,
        readme_path=readme_path,
        readme_content=readme_content,
        allowed_files=allowed_files,
        key_files=key_files,
        structure_summary=structure_summary,
        maintenance_signals=signals,
    )


# --- Issue Intelligence ---

def categorize_issue_content(title: str, body: str) -> TaskCategory:
    """Classify issue into an explicit TaskCategory using linguistic and contextual markers."""
    text = f"{title}\n{body}".lower()

    # 1. Dependency updates
    if any(k in text for k in ["bump ", "upgrade dependency", "dependabot", "cve-", "outdated package", "update version"]):
        return TaskCategory.DEPENDENCY_UPDATE

    # 2. Bug fixes
    if any(k in text for k in ["bug", "error", "crash", "failure", "broken link", "exception", "traceback", "fix "]):
        if "link" in text or "typo" in text or "doc" in text or "readme" in text:
            # Documentation defects
            return TaskCategory.DOCUMENTATION
        return TaskCategory.BUG_FIX

    # 3. Refactoring
    if any(k in text for k in ["refactor", "cleanup", "clean up", "restructure", "simplify", "reorganize"]):
        return TaskCategory.REFACTORING

    # 4. Documentation
    if any(k in text for k in ["doc", "readme", "markdown", "typo", "spelling", "guide", "tutorial", "link", "comment"]):
        return TaskCategory.DOCUMENTATION

    return TaskCategory.MAINTENANCE


def _extract_target_files_from_text(
    text: str,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    workspace_dir: Path,
) -> list[str]:
    """Extract mentioned file paths from issue text and verify path safety."""
    targets: list[str] = []
    # Match backticked or standalone file names with extensions
    file_matches = re.findall(r"`?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9_]+)`?", text)
    for m in file_matches:
        cleaned = m.strip().strip("`'\".,;:()")
        if any(cleaned.endswith(ext) for ext in [".md", ".txt", ".rst", ".py", ".js", ".ts", ".html"]):
            allowed, _ = is_path_allowed(cleaned, repo_config, policy)
            if allowed:
                targets.append(cleaned)

    # Dedup preserving order
    unique_targets: list[str] = []
    for t in targets:
        if t not in unique_targets:
            unique_targets.append(t)
    return unique_targets


def analyze_github_issue(
    issue: dict[str, Any],
    workspace_dir: Path,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    state_mgr: StateManager,
    other_issues: Optional[list[dict[str, Any]]] = None,
) -> IssueAnalysis:
    """
    Intelligently inspect a GitHub issue:
    - Categorize task
    - Detect duplicate issues
    - Detect stale issues
    - Detect ambiguous or non-actionable descriptions
    - Detect already-resolved issues
    - Verify target files exist and evidence is corroborated
    """
    issue_number = issue.get("number", 0)
    title = issue.get("title", "").strip()
    body = issue.get("body", "").strip()
    labels = [l.get("name", "").lower() if isinstance(l, dict) else str(l).lower() for l in issue.get("labels", [])]

    category = categorize_issue_content(title, body)

    # 1. Check if already completed in StateManager
    task_id = f"issue-{issue_number}"
    if state_mgr.is_task_already_done(repo_config.name, task_id):
        return IssueAnalysis(
            issue_number=issue_number,
            title=title,
            status=IssueStatus.ALREADY_RESOLVED,
            category=category,
            reason=f"Task '{task_id}' has already been completed in state history.",
            confidence=1.0,
        )

    # 2. Check for duplicate issue in active batch
    if other_issues:
        for other in other_issues:
            other_num = other.get("number", 0)
            if other_num != issue_number:
                other_title = other.get("title", "").strip().lower()
                # Similarity check: exact title match or very close title
                if title.lower() == other_title and other_num < issue_number:
                    return IssueAnalysis(
                        issue_number=issue_number,
                        title=title,
                        status=IssueStatus.DUPLICATE,
                        category=category,
                        reason=f"Duplicate of older issue #{other_num}: '{other.get('title')}'.",
                        confidence=0.95,
                    )

    # 3. Check for stale issue
    if "stale" in labels or "wontfix" in labels:
        return IssueAnalysis(
            issue_number=issue_number,
            title=title,
            status=IssueStatus.STALE,
            category=category,
            reason="Issue is explicitly marked with 'stale' or 'wontfix' label.",
            confidence=1.0,
        )

    updated_at_str = issue.get("updated_at") or issue.get("created_at")
    if updated_at_str:
        try:
            # Parse ISO date
            dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days > 180:
                return IssueAnalysis(
                    issue_number=issue_number,
                    title=title,
                    status=IssueStatus.STALE,
                    category=category,
                    reason=f"Issue has had no activity for {age_days} days (>180 days threshold).",
                    confidence=0.85,
                )
        except Exception:
            pass

    # 4. Check for ambiguity / lack of actionable instruction
    combined_text = f"{title} {body}".strip()
    if len(combined_text) < 15:
        return IssueAnalysis(
            issue_number=issue_number,
            title=title,
            status=IssueStatus.AMBIGUOUS,
            category=category,
            reason="Issue title and body are too brief to be actionable (<15 characters).",
            confidence=0.9,
        )

    vague_phrases = ["fix it", "make better", "not working", "help needed", "please fix", "clean code", "needs update"]
    has_vague_phrase = (
        title.lower() in vague_phrases
        or body.lower() in vague_phrases
        or any(phrase in combined_text.lower() for phrase in vague_phrases)
    )
    if has_vague_phrase:
        # If it doesn't mention a specific file path or concrete defect
        if not re.search(r"`?[a-zA-Z0-9_\-./]+\.[a-zA-Z0-9_]+`?", combined_text):
            return IssueAnalysis(
                issue_number=issue_number,
                title=title,
                status=IssueStatus.AMBIGUOUS,
                category=category,
                reason=f"Issue description is too ambiguous: '{combined_text}'.",
                confidence=0.95,
            )

    # 5. Extract target files & verify permissions
    target_files = _extract_target_files_from_text(f"{title}\n{body}", repo_config, policy, workspace_dir)
    if not target_files:
        # Fallback to README.md if permitted and allowed in config
        if any("README.md" in p for p in repo_config.allowed_paths):
            if (workspace_dir / "README.md").exists():
                target_files = ["README.md"]

    if not target_files:
        return IssueAnalysis(
            issue_number=issue_number,
            title=title,
            status=IssueStatus.UNSUPPORTED,
            category=category,
            reason="Issue does not reference any allowed repository files, or referenced files are outside allowed_paths.",
            confidence=0.9,
        )

    # 6. Verify evidence in workspace files & check if already resolved
    # For typo reports: check if reported typo actually exists in target files
    typo_candidates: list[str] = []
    quoted_matches = re.findall(r"typo[^\w\n]*['\"`](\w+)['\"`]|['\"`](\w+)['\"`]\s*(?:is a typo|typo)", combined_text, re.IGNORECASE)
    for g1, g2 in quoted_matches:
        word = (g1 or g2).lower()
        if len(word) >= 2 and word not in ("in", "to", "the", "a", "an", "is", "of", "and", "md"):
            typo_candidates.append(word)

    if not typo_candidates:
        for common_typo in COMMON_DOC_TYPOS:
            if re.search(rf"\b{common_typo}\b", combined_text, re.IGNORECASE):
                typo_candidates.append(common_typo.lower())

    if typo_candidates:
        reported_typo = typo_candidates[0]
        typo_present = False
        for tf in target_files:
            file_p = workspace_dir / tf
            if file_p.exists():
                file_text = file_p.read_text(encoding="utf-8", errors="replace").lower()
                pattern = re.compile(rf"\b{re.escape(reported_typo)}\b", re.IGNORECASE)
                if pattern.search(file_text):
                    typo_present = True
                    break
        if not typo_present:
            return IssueAnalysis(
                issue_number=issue_number,
                title=title,
                status=IssueStatus.ALREADY_RESOLVED,
                category=category,
                reason=f"Corroboration failed: reported typo '{reported_typo}' is not present in target files. Issue appears already resolved.",
                confidence=0.95,
            )

    # Build actionable acceptance criteria
    acceptance_criteria: list[str] = []
    for line in body.splitlines():
        trimmed = line.strip()
        if trimmed.startswith(("- [ ]", "* [ ]")):
            crit = trimmed[5:].strip()
            if crit:
                acceptance_criteria.append(crit)

    if not acceptance_criteria:
        acceptance_criteria.append(f"Safely address requirements of issue #{issue_number} in {', '.join(target_files)}")

    return IssueAnalysis(
        issue_number=issue_number,
        title=title,
        status=IssueStatus.ACTIONABLE,
        category=category,
        reason="Issue is actionable, corroborated by repository files, within allowed paths, and unambiguous.",
        confidence=1.0,
        target_files=target_files,
        acceptance_criteria=acceptance_criteria,
    )
