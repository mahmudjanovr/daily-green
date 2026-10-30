"""Global test configuration and state isolation fixtures."""

import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_test_state_environment(tmp_path, monkeypatch):
    """
    Ensure every test operates within an isolated temporary state directory,
    preventing any fallback to or modification of the user's real .dailygreen directory.
    """
    isolated_state_dir = tmp_path / ".dailygreen_test_state"
    isolated_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DAILYGREEN_STATE_DIR", str(isolated_state_dir))

    real_state = Path(".dailygreen") / "state.json"
    initial_mtime = real_state.stat().st_mtime if real_state.exists() else None

    yield isolated_state_dir

    if real_state.exists():
        current_mtime = real_state.stat().st_mtime
        assert current_mtime == initial_mtime, (
            f"Safety violation: Test modified the user's real .dailygreen/state.json! "
            f"(mtime changed from {initial_mtime} to {current_mtime})"
        )
