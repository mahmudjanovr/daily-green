"""Independent, mandatory Quality Gate ensuring all security, test, and acceptance validation gates pass."""

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Optional
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import CommandResult, QualityGateResult, SecurityCheckResult, Task
from dailygreen.security import is_path_allowed, run_security_checks, safe_git_command
from dailygreen.task_engine import format_markdown_content


def compute_patch_hash(diff_text: str) -> str:
    """Compute deterministic SHA256 hash of a verified unified diff."""
    # Normalize line endings to avoid CRLF vs LF divergence
    normalized = "\n".join(diff_text.replace("\r\n", "\n").splitlines()) + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_git_tree_state(workspace_dir: Path) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
    """
    Query Git for the base commit SHA, stage all working tree changes (-A),
    and return (base_commit_sha, tree_sha, staged_diff, changed_files).
    Returns (None, None, None, []) if workspace is not a git repository.
    """
    if not (workspace_dir / ".git").exists():
        return None, None, None, []

    try:
        # 1. Base commit SHA
        res_base = subprocess.run(
            safe_git_command(["git", "rev-parse", "HEAD"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        base_commit_sha = res_base.stdout.strip()

        # 2. Stage all modifications, additions, deletions, renames, mode changes
        subprocess.run(
            safe_git_command(["git", "add", "-A"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

        # 3. Exact Git tree object SHA representing full working tree state
        res_tree = subprocess.run(
            safe_git_command(["git", "write-tree"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        tree_sha = res_tree.stdout.strip()

        # 4. Exact staged unified diff
        res_diff = subprocess.run(
            safe_git_command(["git", "diff", "--cached", "--unified=3", "HEAD"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        staged_diff = res_diff.stdout

        # 5. Exact list of changed files
        res_names = subprocess.run(
            safe_git_command(["git", "diff", "--cached", "--name-only", "HEAD"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        changed_files = [line.strip().replace("\\", "/") for line in res_names.stdout.splitlines() if line.strip()]

        return base_commit_sha, tree_sha, staged_diff, changed_files
    except Exception:
        return None, None, None, []


def verify_acceptance_criteria(
    workspace_dir: Path,
    task: Task,
) -> tuple[bool, list[str]]:
    """
    Verify that acceptance criteria are satisfied in the workspace post-change.
    Returns (passed, details).
    """
    meta = task.metadata or {}
    details: list[str] = []

    # 1. Deterministic Typo Verification
    if meta.get("typo"):
        typo = meta["typo"]
        pattern = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
        for target in task.target_files:
            target_p = workspace_dir / target
            if target_p.exists():
                text = target_p.read_text(encoding="utf-8", errors="replace")
                if pattern.search(text):
                    return False, [f"Acceptance criteria failed: typo '{typo}' still present in '{target}'"]
        details.append(f"Acceptance verification: typo '{typo}' confirmed eliminated.")

    # 2. Deterministic Link Verification
    if meta.get("broken_target"):
        broken_target = meta["broken_target"]
        for target in task.target_files:
            target_p = workspace_dir / target
            if target_p.exists():
                text = target_p.read_text(encoding="utf-8", errors="replace")
                if f"({broken_target})" in text:
                    return False, [f"Acceptance criteria failed: broken link '({broken_target})' still present in '{target}'"]
        details.append(f"Acceptance verification: broken link '{broken_target}' confirmed resolved.")

    # 3. Deterministic Formatting Verification (Markdown hard-break aware)
    if meta.get("format_type") == "whitespace_and_eof":
        for target in task.target_files:
            target_p = workspace_dir / target
            if target_p.exists():
                text = target_p.read_text(encoding="utf-8", errors="replace")
                _, needs_fix = format_markdown_content(text)
                if needs_fix:
                    return False, [
                        f"Acceptance criteria failed: unformatted trailing whitespace or missing EOF newline in '{target}'"
                    ]
        details.append("Acceptance verification: clean formatting and EOF newline confirmed (Markdown hard-breaks preserved).")

    # 4. Deterministic Relative Markdown Link Check
    is_link_task = (
        meta.get("validation_strategy") == "deterministic_markdown_link_check"
        or task.validation_strategy in ("deterministic_markdown_link_check", "markdown_link_verification")
        or any("relative markdown link" in ac.lower() or "relative link" in ac.lower() for ac in task.acceptance_criteria)
    )
    if is_link_task:
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        for target in task.target_files:
            target_p = workspace_dir / target
            if target_p.exists() and target_p.is_file():
                content = target_p.read_text(encoding="utf-8", errors="replace")
                for match in link_pattern.finditer(content):
                    link_target = match.group(2).strip()
                    if link_target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    clean_target = link_target.split("#")[0].split("?")[0]
                    if not clean_target:
                        continue
                    resolved = (target_p.parent / clean_target).resolve()
                    if not resolved.exists():
                        resolved_root = (workspace_dir / clean_target).resolve()
                        if resolved_root.exists():
                            resolved = resolved_root
                    if not resolved.exists():
                        return False, [
                            f"Acceptance criteria failed: relative link target '{link_target}' in '{target}' does not exist on disk."
                        ]
        details.append("Acceptance verification: all relative markdown links point to existing files on disk.")

    # 5. Target files exist
    for target in task.target_files:
        target_p = workspace_dir / target
        if not target_p.exists():
            return False, [f"Acceptance criteria failed: target file '{target}' does not exist after changes."]

    details.append("Acceptance criteria verification passed across all target files.")
    return True, details


def validate_semantic_diff(
    task: Task,
    diff_text: str,
    workspace_dir: Path,
) -> tuple[bool, str]:
    """
    Validate that diff content semantically matches the task's stated objective:
    - Rejects comment-only or trivial/cosmetic changes for tasks requiring functional/documentation fixes.
    - Rejects documentation-link tasks if the diff does not modify or add links.
    - Rejects typo tasks if the diff does not modify the specified typo.
    Returns (passed, rationale).
    """
    if not diff_text or not diff_text.strip():
        return False, "Diff is empty."

    added_lines: list[str] = []
    removed_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added_lines.append(line[1:].strip())
        elif line.startswith("-"):
            removed_lines.append(line[1:].strip())

    non_empty_added = [l for l in added_lines if l]
    non_empty_removed = [l for l in removed_lines if l]

    if not non_empty_added and not non_empty_removed:
        return False, "Diff contains no substantive added or removed lines (whitespace only)."

    # 1. Comment-only detection
    def is_comment(line: str) -> bool:
        s = line.strip()
        if not s:
            return True
        if s.startswith("<!--") or s.endswith("-->") or (s.startswith("<!--") and s.endswith("-->")):
            return True
        if s.startswith("#") and not re.match(r"^#+\s+\S+", s):  # Exclude markdown headers (# Header)
            return True
        if s.startswith("//") or s.startswith("/*") or s.endswith("*/") or s.startswith("*"):
            return True
        return False

    all_comments = (
        all(is_comment(l) for l in non_empty_added)
        and (not non_empty_removed or all(is_comment(l) for l in non_empty_removed))
    )

    is_comment_intended = (
        "comment" in task.id.lower()
        or "comment" in task.title.lower()
        or "comment" in task.description.lower()
    )

    if all_comments and not is_comment_intended:
        return False, "Patch is comment-only and introduces no substantive functional or documentation changes."

    # 2. Link Task Objective Validation
    is_link_task = (
        task.validation_strategy in ("deterministic_markdown_link_check", "markdown_link_verification", "link_check")
        or "link" in task.id.lower()
        or "link" in task.title.lower()
        or any("link" in ac.lower() for ac in task.acceptance_criteria)
    )

    if is_link_task:
        link_regex = re.compile(r"(\[[^\]]+\]\([^)]+\)|<https?://[^>]+>|href\s*=|\[[^\]]+\]:\s*\S+|`[^`]+`)")
        diff_combined = " ".join(non_empty_added + non_empty_removed)
        has_link_change = bool(link_regex.search(diff_combined)) or "](" in diff_combined

        if not has_link_change:
            return False, (
                f"Task '{task.id}' is a documentation-link task, but diff contains no link-related changes "
                "(markdown links, link references, hrefs, or link replacements)."
            )

    # 3. Typo Task Objective Validation
    meta = task.metadata or {}
    if meta.get("typo"):
        typo = meta["typo"].lower()
        replacement = meta.get("replacement", "").lower()
        diff_combined = " ".join(non_empty_added + non_empty_removed).lower()
        if typo not in diff_combined and replacement not in diff_combined:
            return False, f"Task '{task.id}' requires correcting typo '{meta['typo']}', but diff does not modify that typo."

    return True, "Diff semantically aligns with task objectives."


def evaluate_quality_gate(
    workspace_dir: Path,
    task: Task,
    diff_text: str,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
    baseline_result: Optional[CommandResult] = None,
    post_change_tests: Optional[list[CommandResult]] = None,
    post_change_lints: Optional[list[CommandResult]] = None,
) -> QualityGateResult:
    """
    Evaluate the full quality gate, including:
    - Baseline verification
    - Diff emptiness
    - Unrelated file modification detection
    - Path safety & security scanning
    - Post-change tests and linter runs
    - Acceptance criteria verification
    - Cryptographic diff and tree seal
    """
    post_tests = post_change_tests or []
    post_lints = post_change_lints or []
    validation_details: list[str] = []

    # 1. Baseline Verification
    if baseline_result is not None and not baseline_result.passed:
        return QualityGateResult(
            passed=False,
            reason=f"Baseline tests failed prior to applying changes: exit code {baseline_result.exit_code}",
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
            validation_details=["Baseline test check: FAILED"],
        )
    if baseline_result is not None:
        validation_details.append(f"Baseline test check: PASSED (duration: {baseline_result.duration_seconds}s)")

    # 2. Extract immutable Git tree state if in a git repository
    base_commit_sha, tree_sha, staged_diff, git_changed_files = get_git_tree_state(workspace_dir)
    effective_diff = staged_diff if staged_diff is not None else diff_text
    effective_targets = git_changed_files if git_changed_files else task.target_files

    # 3. Diff emptiness check
    if not effective_diff.strip():
        return QualityGateResult(
            passed=False,
            reason="Diff is empty. Zero changes applied.",
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
            validation_details=validation_details + ["Diff emptiness check: FAILED (empty diff)"],
        )
    validation_details.append("Diff emptiness check: PASSED (non-empty changes generated)")

    # 4. Detect Unrelated File Modifications
    # If in git repo, git_changed_files gives the exact files modified on disk
    unrelated_files: list[str] = []
    if git_changed_files:
        planned_files = set(task.target_files)
        if task.plan and task.plan.evidence_and_affected_files:
            planned_files.update(task.plan.evidence_and_affected_files)

        for changed in git_changed_files:
            if changed not in planned_files:
                unrelated_files.append(changed)

        if unrelated_files:
            return QualityGateResult(
                passed=False,
                reason=(
                    f"Validation rejected: Unrelated file modification(s) detected: {unrelated_files}. "
                    "Changes must be strictly confined to planned target files."
                ),
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
                unrelated_files_detected=unrelated_files,
                validation_details=validation_details + [f"Unrelated files check: FAILED ({unrelated_files})"],
            )
        validation_details.append("Unrelated files check: PASSED (zero unexpected files touched)")

    # 5. Verify all files actually touched by Git against allowlist/denylist
    for f in effective_targets:
        allowed, reason = is_path_allowed(f, repo_config, policy)
        if not allowed:
            return QualityGateResult(
                passed=False,
                reason=f"Security violation: Untracked/modified file '{f}' is not permitted: {reason}",
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
                validation_details=validation_details + [f"Path policy check: FAILED for '{f}' ({reason})"],
            )
    validation_details.append(f"Path policy check: PASSED ({len(effective_targets)} files verified allowed)")

    # 6. Semantic Validation (Task objective matching, non-triviality, comment-only rejection)
    sem_passed, sem_reason = validate_semantic_diff(task=task, diff_text=effective_diff, workspace_dir=workspace_dir)
    if not sem_passed:
        return QualityGateResult(
            passed=False,
            reason=f"Semantic quality gate rejected: {sem_reason}",
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
            validation_details=validation_details + [f"Semantic validation: FAILED ({sem_reason})"],
        )
    validation_details.append(f"Semantic validation: PASSED ({sem_reason})")

    # 7. Security Checks (Secrets, Traversals, Max Lines)
    security_res: SecurityCheckResult = run_security_checks(
        workspace_dir=workspace_dir,
        target_files=effective_targets,
        diff_text=effective_diff,
        repo_config=repo_config,
        policy=policy,
    )

    if not security_res.passed:
        failure_details = "; ".join(security_res.details)
        return QualityGateResult(
            passed=False,
            reason=f"Security checks failed: {failure_details}",
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
            security_result=security_res,
            validation_details=validation_details + [f"Security scan: FAILED ({failure_details})"],
        )
    validation_details.append(
        f"Security scan: PASSED ({security_res.lines_changed}/{security_res.max_lines_allowed} lines, 0 secrets, 0 path traversals)"
    )

    # 7. Post-change Test Commands
    for idx, test_res in enumerate(post_tests):
        if not test_res.passed:
            cmd_str = " ".join(test_res.command)
            return QualityGateResult(
                passed=False,
                reason=f"Post-change test #{idx+1} '{cmd_str}' failed with exit code {test_res.exit_code}",
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
                security_result=security_res,
                validation_details=validation_details + [f"Test #{idx+1} '{cmd_str}': FAILED"],
            )
        validation_details.append(f"Test #{idx+1} '{' '.join(test_res.command)}': PASSED ({test_res.duration_seconds}s)")

    # 8. Post-change Lint Commands
    for idx, lint_res in enumerate(post_lints):
        if not lint_res.passed:
            cmd_str = " ".join(lint_res.command)
            return QualityGateResult(
                passed=False,
                reason=f"Post-change linter #{idx+1} '{cmd_str}' failed with exit code {lint_res.exit_code}",
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
                security_result=security_res,
                validation_details=validation_details + [f"Linter #{idx+1} '{cmd_str}': FAILED"],
            )
        validation_details.append(f"Linter #{idx+1} '{' '.join(lint_res.command)}': PASSED ({lint_res.duration_seconds}s)")

    # 9. Verify Acceptance Criteria
    ac_passed, ac_details = verify_acceptance_criteria(workspace_dir, task)
    validation_details.extend(ac_details)
    if not ac_passed:
        return QualityGateResult(
            passed=False,
            reason="; ".join(ac_details),
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
            security_result=security_res,
            acceptance_criteria_verified=False,
            validation_details=validation_details,
        )

    # 10. Cryptographically seal verified patch and tree
    patch_seal = compute_patch_hash(effective_diff)

    return QualityGateResult(
        passed=True,
        reason="All quality, security, and validation gates passed successfully.",
        baseline_result=baseline_result,
        post_change_tests=post_tests,
        post_change_lints=post_lints,
        security_result=security_res,
        patch_hash=patch_seal,
        base_commit_sha=base_commit_sha,
        tree_sha=tree_sha,
        verified_diff=effective_diff,
        changed_files=effective_targets,
        unrelated_files_detected=[],
        acceptance_criteria_verified=True,
        validation_details=validation_details,
    )
