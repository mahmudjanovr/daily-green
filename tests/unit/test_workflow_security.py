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
    assert "needs.worker.outputs.dry_run != 'true'" in delivery_condition

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
