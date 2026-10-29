"""Unit tests validating GitHub Actions workflow structure, permissions, and security conditions."""

import re
import yaml
from pathlib import Path


def test_workflow_structure_and_commit_pinning():
    wf_path = Path(".github/workflows/dailygreen.yml")
    assert wf_path.exists(), "dailygreen.yml workflow file must exist"

    content = wf_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    # 1. Top-level permissions must be read-only
    assert data.get("permissions") == {"contents": "read"}

    # 2. Concurrency configuration
    concurrency = data.get("concurrency", {})
    assert concurrency.get("group") == "dailygreen-execution"
    assert concurrency.get("cancel-in-progress") is False

    # 3. Scheduled crons match Asia/Tashkent (UTC+5)
    # 22:15 Tashkent -> 17:15 UTC ('15 17 * * *')
    # 22:35 Tashkent -> 17:35 UTC ('35 17 * * *')
    on_section = data.get(True) if True in data else data.get("on", {})
    schedules = [s.get("cron") for s in on_section.get("schedule", [])]
    assert "15 17 * * *" in schedules, "Primary run must be scheduled at 17:15 UTC (22:15 Tashkent)"
    assert "35 17 * * *" in schedules, "Backup run must be scheduled at 17:35 UTC (22:35 Tashkent)"

    jobs = data.get("jobs", {})
    assert "worker" in jobs
    assert "delivery" in jobs

    worker_job = jobs["worker"]
    delivery_job = jobs["delivery"]

    # 4. Worker job permissions: read-only
    worker_perms = worker_job.get("permissions", {})
    assert worker_perms.get("contents") == "read"
    assert worker_perms.get("issues") == "read"
    assert "pull-requests" not in worker_perms or worker_perms["pull-requests"] == "read"
    assert worker_perms.get("contents") != "write"

    # 5. Delivery job conditions and permissions
    delivery_condition = delivery_job.get("if", "")
    assert "needs.worker.outputs.has_task == 'true'" in delivery_condition
    assert "needs.worker.outputs.dry_run == 'false'" in delivery_condition

    # 6. Verify third-party action pinning to full commit SHAs
    # Pattern: uses: owner/action@<40-hex-sha>
    action_uses = re.findall(r"uses:\s*([^\s]+)", content)
    sha_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    for action in action_uses:
        # Strip comments
        action_clean = action.split("#")[0].strip()
        assert sha_pattern.match(action_clean), (
            f"Action '{action_clean}' is not pinned to a full 40-character commit SHA"
        )


def test_workflow_expression_injection_and_kill_switch_variable():
    wf_path = Path(".github/workflows/dailygreen.yml")
    content = wf_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    # 1. Ensure ${{ inputs. }} is NEVER directly interpolated in any run: block
    jobs = data.get("jobs", {})
    for job_name, job_def in jobs.items():
        steps = job_def.get("steps", [])
        for step in steps:
            run_script = step.get("run", "")
            assert "${{ inputs." not in run_script, (
                f"Expression injection vulnerability in job '{job_name}', step '{step.get('name')}': "
                f"${{{{ inputs. ... }}}} must be passed via env: variables, not inside run: script"
            )

    # 2. Verify emergency kill switch uses repository variable fallback
    worker_steps = jobs["worker"]["steps"]
    worker_run_step = next(s for s in worker_steps if "dailygreen.cli run" in s.get("run", ""))
    assert "DAILYGREEN_ENABLED" in worker_run_step.get("env", {})
    assert "vars.DAILYGREEN_ENABLED" in worker_run_step["env"]["DAILYGREEN_ENABLED"]

    delivery_steps = jobs["delivery"]["steps"]
    delivery_run_step = next(s for s in delivery_steps if "dailygreen.cli deliver" in s.get("run", ""))
    assert "DAILYGREEN_ENABLED" in delivery_run_step.get("env", {})
    assert "vars.DAILYGREEN_ENABLED" in delivery_run_step["env"]["DAILYGREEN_ENABLED"]
    assert "ALLOW_LIVE_MUTATIONS" in delivery_run_step.get("env", {})
    assert "vars.ALLOW_LIVE_MUTATIONS" in delivery_run_step["env"]["ALLOW_LIVE_MUTATIONS"]
    assert "DRY_RUN" in delivery_run_step.get("env", {})
    assert "needs.worker.outputs.dry_run" in delivery_run_step["env"]["DRY_RUN"]

    # 2b. Verify mode determination safely defaults to dry_run="true"
    mode_step = next(s for s in worker_steps if s.get("id") == "mode")
    mode_script = mode_step.get("run", "")
    assert 'DRY_RUN="true"' in mode_script
    assert '[ "$INPUT_DRY_RUN" = "false" ]' in mode_script

    # 3. Verify Bash argument array construction and safe quoting (no unquoted variable expansion)
    worker_script = worker_run_step.get("run", "")
    assert "ARGS=()" in worker_script, "Must initialize bash argument array ARGS=()"
    assert 'ARGS+=(--repo "$INPUT_REPO")' in worker_script, "Must append repo argument using array syntax"
    assert "ARGS+=(--backup)" in worker_script, "Must append backup flag using array syntax"
    assert "ARGS+=(--worker-only)" in worker_script, "Must append worker-only flag using array syntax"
    assert 'python -m dailygreen.cli run "${ARGS[@]}"' in worker_script, (
        "Must invoke CLI using quoted array expansion \"${ARGS[@]}\""
    )
    assert "$REPO_FLAG" not in worker_script, "Unquoted $REPO_FLAG expansion must not be used"
    assert "grep -Eq '^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$'" in worker_script, (
        "Must strictly validate owner/repo format before adding --repo argument"
    )
