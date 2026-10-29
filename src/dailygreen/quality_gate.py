"""Independent, mandatory Quality Gate ensuring all security and test gates pass."""

import hashlib
import subprocess
from pathlib import Path
from typing import Optional
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import CommandResult, QualityGateResult, SecurityCheckResult, Task
from dailygreen.security import is_path_allowed, run_security_checks, safe_git_command


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
        )
        base_commit_sha = res_base.stdout.strip()

        # 2. Stage all modifications, additions, deletions, renames, mode changes
        subprocess.run(
            safe_git_command(["git", "add", "-A"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
        )

        # 3. Exact Git tree object SHA representing full working tree state
        res_tree = subprocess.run(
            safe_git_command(["git", "write-tree"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        tree_sha = res_tree.stdout.strip()

        # 4. Exact staged unified diff
        res_diff = subprocess.run(
            safe_git_command(["git", "diff", "--cached", "--unified=3", "HEAD"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        staged_diff = res_diff.stdout

        # 5. Exact list of changed files
        res_names = subprocess.run(
            safe_git_command(["git", "diff", "--cached", "--name-only", "HEAD"]),
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [line.strip().replace("\\", "/") for line in res_names.stdout.splitlines() if line.strip()]

        return base_commit_sha, tree_sha, staged_diff, changed_files
    except Exception:
        return None, None, None, []


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
    Evaluate the full quality gate and cryptographically seal the verified patch and tree.
    """
    post_tests = post_change_tests or []
    post_lints = post_change_lints or []

    # 1. Baseline Verification
    if baseline_result is not None and not baseline_result.passed:
        return QualityGateResult(
            passed=False,
            reason=f"Baseline tests failed prior to applying changes: exit code {baseline_result.exit_code}",
            baseline_result=baseline_result,
            post_change_tests=post_tests,
            post_change_lints=post_lints,
        )

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
        )

    # 4. Verify all files actually touched by Git against allowlist/denylist
    for f in effective_targets:
        allowed, reason = is_path_allowed(f, repo_config, policy)
        if not allowed:
            return QualityGateResult(
                passed=False,
                reason=f"Security violation: Untracked/modified file '{f}' is not permitted: {reason}",
                baseline_result=baseline_result,
                post_change_tests=post_tests,
                post_change_lints=post_lints,
            )

    # 5. Security Checks (Secrets, Traversals, Max Lines)
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
        )

    # 6. Post-change Test Commands
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
            )

    # 7. Post-change Lint Commands
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
            )

    # 8. Cryptographically seal verified patch and tree
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
    )
