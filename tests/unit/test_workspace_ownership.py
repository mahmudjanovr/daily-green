"""Unit tests for HMAC workspace ownership, secret key isolation, and restart survival."""

import json
from pathlib import Path
import pytest
from dailygreen.repository_manager import (
    MARKER_FILENAME,
    SIGNING_KEY_FILENAME,
    get_or_create_signing_key,
    verify_managed_workspace_ownership,
    write_managed_workspace_marker,
)


def test_hmac_signing_key_creation_and_persistence(tmp_path: Path):
    """HMAC signing key is created in state_dir, has 32 bytes, and persists across reloads."""
    state_dir = tmp_path / "state"
    key1 = get_or_create_signing_key(state_dir)

    assert len(key1) == 32
    assert (state_dir / SIGNING_KEY_FILENAME).exists()

    # Second load must return identical key
    key2 = get_or_create_signing_key(state_dir)
    assert key1 == key2


def test_workspace_marker_creation_and_hmac_verification(tmp_path: Path):
    """Managed workspace marker contains valid HMAC authenticated by the state signing key."""
    state_dir = tmp_path / "state"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    repo_name = "test-org/test-repo"
    ws_id = write_managed_workspace_marker(ws_dir, repo_name, state_dir=state_dir)

    marker_file = ws_dir / MARKER_FILENAME
    assert marker_file.exists()

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["managed"] is True
    assert marker_data["workspace_id"] == ws_id
    assert marker_data["repo_name"] == repo_name
    assert "signature" in marker_data
    # PID must not be stored in marker (does not tie to ephemeral PID)
    assert "pid" not in marker_data

    # Verification must succeed
    assert verify_managed_workspace_ownership(ws_dir, expected_repo=repo_name, state_dir=state_dir) is True


def test_workspace_marker_survives_process_restart(tmp_path: Path):
    """Verification succeeds when invoked in a new process context using the persisted state key."""
    state_dir = tmp_path / "state"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    repo_name = "test-org/restart-repo"
    write_managed_workspace_marker(ws_dir, repo_name, state_dir=state_dir)

    # In a separate call / simulated restarted process loading the same state_dir:
    assert verify_managed_workspace_ownership(ws_dir, expected_repo=repo_name, state_dir=state_dir) is True


def test_verification_rejects_unmanaged_or_forged_workspace(tmp_path: Path):
    """Verification rejects unmanaged directories, tampered signatures, or mismatched state keys."""
    state_dir = tmp_path / "state"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    # 1. Completely unmanaged directory without marker
    assert verify_managed_workspace_ownership(ws_dir, expected_repo="test-org/test-repo", state_dir=state_dir) is False

    # 2. Workspace created with different state directory (different secret key)
    other_state_dir = tmp_path / "other_state"
    write_managed_workspace_marker(ws_dir, "test-org/test-repo", state_dir=other_state_dir)
    assert verify_managed_workspace_ownership(ws_dir, expected_repo="test-org/test-repo", state_dir=state_dir) is False

    # 3. Tampered repository name in marker
    ws_tampered = tmp_path / "tampered_ws"
    ws_tampered.mkdir()
    write_managed_workspace_marker(ws_tampered, "test-org/test-repo", state_dir=state_dir)
    marker_path = ws_tampered / MARKER_FILENAME
    data = json.loads(marker_path.read_text(encoding="utf-8"))
    data["repo_name"] = "test-org/other-repo"
    marker_path.write_text(json.dumps(data), encoding="utf-8")

    assert verify_managed_workspace_ownership(ws_tampered, expected_repo="test-org/test-repo", state_dir=state_dir) is False


def test_verification_rejects_symlink_marker(tmp_path: Path):
    """Verification rejects symlinks pointing to marker files to prevent path traversal."""
    state_dir = tmp_path / "state"
    real_ws = tmp_path / "real_ws"
    real_ws.mkdir()
    write_managed_workspace_marker(real_ws, "test-org/test-repo", state_dir=state_dir)

    target_ws = tmp_path / "fake_ws"
    target_ws.mkdir()
    symlink_marker = target_ws / MARKER_FILENAME

    try:
        symlink_marker.symlink_to(real_ws / MARKER_FILENAME)
        assert verify_managed_workspace_ownership(target_ws, expected_repo="test-org/test-repo", state_dir=state_dir) is False
    except OSError:
        # If symlink creation not supported on unprivileged Windows, skip symlink creation
        pytest.skip("Symlink creation requires elevated permissions on this environment")
