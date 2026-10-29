"""Command-line interface for DailyGreen operations."""

import os
import sys
from pathlib import Path
from typing import Optional
import click
from dailygreen import __version__
from dailygreen.ai.factory import get_ai_adapter
from dailygreen.config import ConfigurationError, load_config
from dailygreen.github_client import GitHubClient, MockGitHubClient
from dailygreen.models import RunStatus
from dailygreen.reporting import format_markdown_summary, setup_logging, write_github_step_summary
from dailygreen.repository_manager import IsolatedWorkspace
from dailygreen.scheduler import execute_dailygreen_pipeline
from dailygreen.state import StateManager
from dailygreen.task_discovery import discover_next_task


@click.group()
@click.version_option(version=__version__, prog_name="dailygreen")
def main() -> None:
    """DailyGreen - Automates meaningful maintenance across authorized repositories."""
    pass


@main.command("check-config")
@click.option("--repos-config", type=click.Path(exists=True), help="Path to repos.yml")
@click.option("--policy-config", type=click.Path(exists=True), help="Path to policy.yml")
def check_config_cmd(repos_config: Optional[str], policy_config: Optional[str]) -> None:
    """Validate configuration files and verify repository allowlist."""
    try:
        cfg = load_config(repos_path=repos_config, policy_path=policy_config)
        click.echo("Configuration validated successfully:")
        click.echo(f"  - Enabled (Global Kill Switch): {cfg.enabled}")
        click.echo(f"  - Dry Run Default: {cfg.dry_run}")
        click.echo(f"  - Max Diff Lines Policy: {cfg.policy.max_diff_lines}")
        click.echo(f"  - AI Provider: {cfg.ai.provider} (Model: {cfg.ai.model})")
        click.echo(f"  - Authorized Repositories ({len(cfg.repos)}):")
        for r in cfg.repos:
            status = "ENABLED" if r.enabled else "DISABLED"
            click.echo(f"    * {r.name} [{status}] (Tasks: {', '.join(r.supported_task_types)})")
    except ConfigurationError as e:
        click.echo(f"Configuration validation failed: {e}", err=True)
        sys.exit(1)


@main.command("check-github")
@click.option("--repo", help="Target specific authorized repository in 'owner/repo' format")
@click.option("--repos-config", type=click.Path(), help="Path to repos.yml")
@click.option("--policy-config", type=click.Path(), help="Path to policy.yml")
@click.option("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN environment variable)")
@click.option("--mock-github", is_flag=True, default=False, help="Use mock GitHub client for local testing")
def check_github_cmd(
    repo: Optional[str],
    repos_config: Optional[str],
    policy_config: Optional[str],
    token: Optional[str],
    mock_github: bool,
) -> None:
    """Verify GitHub authentication, API connectivity, and read-only repository access."""
    import os
    import re
    from datetime import datetime, timezone
    from dailygreen.github_client import GitHubAPIError

    logger = setup_logging()
    try:
        cfg = load_config(repos_path=repos_config, policy_path=policy_config)
    except ConfigurationError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    if not cfg.enabled:
        click.echo("DailyGreen is currently disabled via configuration or DAILYGREEN_ENABLED=false.")
        sys.exit(0)

    # Resolve target repositories
    target_repos = []
    if repo:
        if not re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
            click.echo(f"Error: Invalid repository name format '{repo}'. Expected 'owner/repo'.", err=True)
            sys.exit(1)
        repo_cfg = cfg.get_repo(repo)
        if not repo_cfg:
            click.echo(f"Error: Repository '{repo}' is not authorized in allowlist.", err=True)
            sys.exit(1)
        target_repos.append(repo_cfg)
    else:
        target_repos = [r for r in cfg.repos if r.enabled]

    if not target_repos:
        click.echo("No authorized repositories configured or enabled in allowlist.")
        click.echo("To configure a repository, copy config/repos.example.yml to config/repos.yml and define an authorized repository.")
        sys.exit(0)

    effective_token = token or os.getenv("GITHUB_TOKEN", "").strip()
    click.echo("=== GitHub Read-Only Connectivity Check ===")
    if effective_token:
        click.echo("Token Status: DETECTED (credentials provided via parameter or GITHUB_TOKEN)")
    else:
        click.echo("Token Status: NOT PROVIDED (unauthenticated; subject to strict 60 req/hr rate limits and public access only)")

    client = MockGitHubClient() if mock_github else GitHubClient(token=effective_token)

    # 1. Rate Limit & API connectivity
    try:
        rl_data = client.get_rate_limit()
        if rl_data and "rate" in rl_data:
            r = rl_data["rate"]
            reset_ts = r.get("reset", 0)
            reset_str = datetime.fromtimestamp(reset_ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if reset_ts else "N/A"
            click.echo(f"API Rate Limit: {r.get('remaining', 'N/A')}/{r.get('limit', 'N/A')} remaining (resets at {reset_str})")
        else:
            click.echo("API Rate Limit: Available")
    except GitHubAPIError as e:
        click.echo(f"Rate limit check warning: {e}", err=True)
    except Exception as e:
        click.echo(f"API connectivity failed: {e}", err=True)
        sys.exit(1)

    # 2. Authenticated user profile
    try:
        user_info = client.get_authenticated_user()
        if user_info and "login" in user_info:
            click.echo(f"Authenticated Identity: {user_info.get('login')} (Type: {user_info.get('type', 'User')})")
        elif effective_token:
            click.echo("Authenticated Identity: Token accepted (fine-grained token or resource-scoped credentials)")
        else:
            click.echo("Authenticated Identity: Anonymous")
    except GitHubAPIError as e:
        if e.status_code == 401:
            click.echo("Authentication Error: GitHub token is invalid or expired (HTTP 401).", err=True)
            sys.exit(1)
        click.echo(f"User identity note: {e}")

    # 3. Check each authorized repository
    overall_exit_code = 0
    for target in target_repos:
        click.echo(f"\nVerifying Repository Access: {target.name}")
        try:
            repo_info = client.get_repository(target.name)
            if not repo_info:
                click.echo(f"  - Status: INACCESSIBLE (HTTP 404 - Repository not found or token lacks read access)", err=True)
                overall_exit_code = 1
                continue

            remote_default = repo_info.get("default_branch", "main")
            is_private = repo_info.get("private", False)
            perms = repo_info.get("permissions", {})
            click.echo(f"  - Status: ACCESSIBLE")
            click.echo(f"  - Visibility: {'Private' if is_private else 'Public'}")
            click.echo(f"  - Remote Default Branch: {remote_default}")
            click.echo(
                f"  - Account Repository Permissions: Read: {perms.get('pull', True)}, Write: {perms.get('push', False)}, Admin: {perms.get('admin', False)} "
                "(Note: reflects user account role; DailyGreen check-github executes strictly read-only API calls)"
            )

            if target.default_branch != remote_default:
                click.echo(f"  - Notice: Configured default branch '{target.default_branch}' differs from remote default branch '{remote_default}'.")

            # Check labeled issues
            issues = client.get_labeled_issues(target.name, label="dailygreen")
            click.echo(f"  - Issues labeled 'dailygreen': {len(issues)} open issue(s) discovered")

            # Check open pull requests
            open_prs = client.get_open_pull_requests(target.name)
            click.echo(f"  - Open Pull Requests: {len(open_prs)} found")

        except GitHubAPIError as e:
            click.echo(f"  - Error querying repository '{target.name}': {e}", err=True)
            overall_exit_code = 1
        except Exception as e:
            click.echo(f"  - Unexpected error: {e}", err=True)
            overall_exit_code = 1

    click.echo("\nRead-Only Check Completed: Zero remote mutations performed.")
    sys.exit(overall_exit_code)


@main.command("discover")
@click.option("--repo", required=True, help="Authorized repository in 'owner/repo' format")
@click.option("--source-dir", type=click.Path(exists=True), help="Local source directory for testing")
@click.option("--repos-config", type=click.Path(), help="Path to repos.yml")
@click.option("--policy-config", type=click.Path(), help="Path to policy.yml")
@click.option("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN environment variable)")
@click.option("--mock-github", is_flag=True, default=False, help="Use mock GitHub client for local testing")
def discover_cmd(
    repo: str,
    source_dir: Optional[str],
    repos_config: Optional[str],
    policy_config: Optional[str],
    token: Optional[str],
    mock_github: bool,
) -> None:
    """Discover the next eligible maintenance task for a repository without making changes."""
    import os
    import re
    from dailygreen.repository_manager import RepositoryManagerError

    logger = setup_logging()
    cfg = load_config(repos_path=repos_config, policy_path=policy_config)

    if not cfg.enabled:
        logger.info("DailyGreen is currently disabled. Exiting.")
        sys.exit(0)

    if not re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
        click.echo(f"Error: Invalid repository name format '{repo}'. Expected 'owner/repo'.", err=True)
        sys.exit(1)

    repo_cfg = cfg.get_repo(repo)
    if not repo_cfg:
        click.echo(f"Error: Repository '{repo}' is not authorized in allowlist.", err=True)
        sys.exit(1)

    effective_token = token or os.getenv("GITHUB_TOKEN", "").strip()
    state_mgr = StateManager(state_dir=cfg.state_dir)
    github_client = MockGitHubClient() if mock_github else GitHubClient(token=effective_token)
    ai_adapter = get_ai_adapter(cfg.ai)

    # When testing against real remote repositories without source_dir, clone over HTTPS
    clone_url = None
    if not source_dir and not mock_github:
        clone_url = f"https://github.com/{repo_cfg.name}.git"

    try:
        with IsolatedWorkspace(
            repo_config=repo_cfg,
            source_dir=source_dir,
            clone_url=clone_url,
            token=effective_token,
        ) as workspace_path:
            task = discover_next_task(
                workspace_dir=workspace_path,
                repo_config=repo_cfg,
                policy=cfg.policy,
                github_client=github_client,
                state_mgr=state_mgr,
                ai_adapter=ai_adapter,
            )
    except RepositoryManagerError as e:
        click.echo(f"Workspace preparation error: {e}", err=True)
        sys.exit(1)

    if not task:
        click.echo("Read-Only Discovery Result:")
        click.echo(f"  Status: NO_TASK")
        click.echo(f"  Notice: No eligible maintenance tasks found for repository '{repo}'. Zero modifications performed.")
        sys.exit(0)

    click.echo("Read-Only Discovery Result:")
    click.echo(f"  Status: CANDIDATE_DISCOVERED (Proposed candidate only; no changes applied)")
    click.echo(f"  Task Title: {task.title}")
    click.echo(f"  Task ID: {task.id}")
    click.echo(f"  Source: {task.source.value}")
    click.echo(f"  Risk Level: {task.risk_level.value}")
    click.echo(f"  Target Files: {task.target_files}")
    click.echo(f"  Rationale: {task.rationale}")
    click.echo("  Acceptance Criteria:")
    for ac in task.acceptance_criteria:
        click.echo(f"    - {ac}")
    click.echo("\nNotice: Discovered candidate is proposed only. Zero remote or local modifications were made.")


@main.command("run")
@click.option("--repo", help="Target specific authorized repository (e.g. owner/repo)")
@click.option("--repos-config", type=click.Path(), help="Path to repos.yml")
@click.option("--policy-config", type=click.Path(), help="Path to policy.yml")
@click.option("--dry-run/--no-dry-run", default=None, help="Explicitly enable or disable dry-run mode")
@click.option("--allow-live-mutations/--no-allow-live-mutations", default=None, help="Explicitly authorize live mutations")
@click.option("--backup", is_flag=True, default=False, help="Run in backup check mode")
@click.option("--source-dir", type=click.Path(exists=True), help="Local source directory for offline testing")
@click.option("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN environment variable)")
@click.option("--mock-github", is_flag=True, default=False, help="Use mock GitHub client for local testing")
@click.option("--worker-only", is_flag=True, default=False, help="Run worker evaluation and write sealed artifact without delivery")
def run_cmd(
    repo: Optional[str],
    repos_config: Optional[str],
    policy_config: Optional[str],
    dry_run: Optional[bool],
    allow_live_mutations: Optional[bool],
    backup: bool,
    source_dir: Optional[str],
    token: Optional[str],
    mock_github: bool,
    worker_only: bool,
) -> None:
    """Execute DailyGreen maintenance pipeline across authorized repositories."""
    logger = setup_logging()
    try:
        cfg = load_config(
            repos_path=repos_config,
            policy_path=policy_config,
            override_dry_run=dry_run,
            override_allow_live_mutations=allow_live_mutations,
        )
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    if not cfg.enabled:
        logger.info("DailyGreen is currently disabled. Exiting.")
        sys.exit(0)

    # Determine target repositories
    target_repos = []
    if repo:
        import re
        if not re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
            logger.error(f"Invalid repository name format '{repo}'. Expected 'owner/repo'.")
            sys.exit(1)
        repo_cfg = cfg.get_repo(repo)
        if not repo_cfg:
            logger.error(f"Repository '{repo}' is not explicitly authorized in allowlist.")
            sys.exit(1)
        target_repos.append(repo_cfg)
    else:
        target_repos = [r for r in cfg.repos if r.enabled]

    if not target_repos:
        logger.info("No authorized repositories configured or enabled. Exiting.")
        sys.exit(0)

    state_mgr = StateManager(state_dir=cfg.state_dir)
    effective_token = token or os.getenv("GITHUB_TOKEN", "").strip()
    github_client = MockGitHubClient() if mock_github else GitHubClient(token=effective_token)

    overall_exit_code = 0
    for target in target_repos:
        logger.info(f"Starting execution for repository: {target.name} (Dry run: {cfg.dry_run})")
        report = execute_dailygreen_pipeline(
            repo_config=target,
            config=cfg,
            github_client=github_client,
            state_mgr=state_mgr,
            source_dir=source_dir,
            is_backup_run=backup,
            override_dry_run=cfg.dry_run,
            worker_only=worker_only,
        )

        logger.info(f"Run completed for {target.name}: status={report.status.value}")
        write_github_step_summary(report)

        if report.status == RunStatus.FAILED:
            overall_exit_code = 1

    sys.exit(overall_exit_code)


@main.command("deliver")
@click.option("--sealed-artifact", required=True, type=click.Path(exists=True), help="Path to sealed_task.json")
@click.option("--repos-config", type=click.Path(), help="Path to repos.yml")
@click.option("--policy-config", type=click.Path(), help="Path to policy.yml")
@click.option("--dry-run/--no-dry-run", default=None, help="Explicitly enable or disable dry-run")
@click.option("--allow-live-mutations/--no-allow-live-mutations", default=None, help="Explicitly authorize live mutations")
@click.option("--source-dir", type=click.Path(exists=True), help="Local source directory for testing")
@click.option("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN environment variable)")
@click.option("--mock-github", is_flag=True, default=False, help="Use mock GitHub client for local testing")
def deliver_cmd(
    sealed_artifact: str,
    repos_config: Optional[str],
    policy_config: Optional[str],
    dry_run: Optional[bool],
    allow_live_mutations: Optional[bool],
    source_dir: Optional[str],
    token: Optional[str],
    mock_github: bool,
) -> None:
    """Deliver a pre-verified sealed artifact in an isolated delivery environment."""
    import json
    import re
    import subprocess
    from dailygreen.delivery import deliver_pull_request
    from dailygreen.models import QualityGateResult, Task
    from dailygreen.quality_gate import compute_patch_hash
    from dailygreen.security import count_diff_lines, is_path_allowed, safe_git_command, scan_content_for_secrets

    logger = setup_logging()

    # Load and validate configuration
    try:
        cfg = load_config(
            repos_path=repos_config,
            policy_path=policy_config,
            override_dry_run=dry_run,
            override_allow_live_mutations=allow_live_mutations,
        )
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    if not cfg.enabled:
        logger.info("DailyGreen is currently disabled. Delivery aborted.")
        sys.exit(0)

    def _fail(msg: str) -> None:
        logger.error(msg)
        click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    # 1. Parse and validate sealed artifact JSON
    try:
        with open(sealed_artifact, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        _fail(f"Failed to read sealed artifact '{sealed_artifact}': {e}")

    if not isinstance(data, dict):
        _fail("Invalid sealed artifact: root is not a dictionary.")

    required_keys = {"repo", "task", "quality_gate", "diff_text"}
    if not required_keys.issubset(data.keys()):
        _fail(f"Sealed artifact missing required keys: {required_keys - set(data.keys())}")

    repo_name = data["repo"]
    repo_cfg = cfg.get_repo(repo_name)
    if not repo_cfg:
        _fail(f"Security violation: Repository '{repo_name}' is not authorized in allowlist.")

    if not repo_cfg.enabled:
        logger.info(f"Repository '{repo_name}' is disabled in configuration. Delivery aborted.")
        sys.exit(0)

    try:
        task = Task(**data["task"])
        quality_gate = QualityGateResult(**data["quality_gate"])
    except Exception as e:
        _fail(f"Sealed artifact model validation failed: {e}")

    diff_text = str(data["diff_text"])

    # Enforce dry-run precedence: if CLI or config specifies dry_run=True, force dry-run
    if dry_run is not None:
        effective_dry_run = dry_run
    elif cfg.dry_run:
        effective_dry_run = True
    else:
        effective_dry_run = bool(data.get("dry_run", True))

    # Independent explicit live-mutation safety gate
    if not effective_dry_run and not cfg.allow_live_mutations:
        _fail("Security violation: Live delivery rejected. ALLOW_LIVE_MUTATIONS must be explicitly enabled to perform remote mutations.")

    today_str = data.get("today_str")

    # 2. Strict Artifact Integrity and Security Gates
    # 2a. Task ID validation
    if not re.match(r"^[a-zA-Z0-9_.-]+$", task.id):
        _fail(f"Security violation: Malformed or unsafe task ID '{task.id}'.")

    # 2b. Target files validation
    if not task.target_files:
        _fail("Security violation: Task has empty target_files.")

    for target in task.target_files:
        allowed, reason = is_path_allowed(target, repo_cfg, cfg.policy)
        if not allowed:
            _fail(f"Security violation: Task target file '{target}' is forbidden: {reason}")

    # 2c. Quality gate seal verification
    if not quality_gate.passed:
        _fail(f"Cannot deliver: Quality gate failed ({quality_gate.reason}).")

    actual_diff_hash = compute_patch_hash(diff_text)
    if quality_gate.patch_hash and actual_diff_hash != quality_gate.patch_hash:
        _fail("Security violation: Artifact diff hash does not match quality gate seal.")

    # 2d. Diff size bounds check
    allowed_max_lines = min(repo_cfg.max_diff_lines, cfg.policy.max_diff_lines)
    actual_diff_lines = count_diff_lines(diff_text)
    if actual_diff_lines > allowed_max_lines:
        _fail(f"Security violation: Diff lines ({actual_diff_lines}) exceed limit ({allowed_max_lines}).")

    # 2e. Secret scan on diff
    if cfg.policy.require_secret_scan:
        secret_matches = scan_content_for_secrets(diff_text)
        if secret_matches:
            _fail(f"Security violation: Secrets detected in delivery artifact diff: {secret_matches}")

    state_mgr = StateManager(state_dir=cfg.state_dir)
    effective_token = token or os.getenv("GITHUB_TOKEN", "").strip()
    github_client = MockGitHubClient() if mock_github else GitHubClient(token=effective_token)

    with IsolatedWorkspace(repo_config=repo_cfg, source_dir=source_dir) as workspace_path:
        # If git workspace, apply verified patch
        if (workspace_path / ".git").exists() and diff_text:
            try:
                subprocess.run(
                    safe_git_command(["git", "apply", "--ignore-whitespace"]),
                    input=diff_text,
                    cwd=str(workspace_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to apply sealed patch in isolated workspace: {e.stderr}")
                sys.exit(1)

        delivery_res = deliver_pull_request(
            workspace_dir=workspace_path,
            task=task,
            quality_gate=quality_gate,
            diff_text=diff_text,
            repo_config=repo_cfg,
            policy=cfg.policy,
            github_client=github_client,
            dry_run=effective_dry_run,
            date_str=today_str,
            allow_live_mutations=cfg.allow_live_mutations,
        )

        if delivery_res.success and not effective_dry_run:
            state_mgr.record_task_completion(
                repo=repo_cfg.name,
                task_id=task.id,
                details={"branch": delivery_res.branch_name, "pr_number": delivery_res.pr_number},
                date_str=today_str,
            )

        click.echo(f"Delivery result: {delivery_res.message}")
        if not delivery_res.success:
            sys.exit(1)


@main.command("report")
@click.option("--state-dir", default=".dailygreen", help="Directory containing state.json")
def report_cmd(state_dir: str) -> None:
    """Inspect recent runs and state history."""
    state_mgr = StateManager(state_dir=state_dir)
    runs = state_mgr._state.get("runs", [])
    if not runs:
        click.echo("No run history recorded.")
        return

    click.echo(f"Recent DailyGreen Runs ({len(runs)}):")
    for r in runs[-10:]:
        click.echo(f"[{r.get('timestamp')}] {r.get('repo')} -> {r.get('status')} ({r.get('message')})")


if __name__ == "__main__":
    main()
