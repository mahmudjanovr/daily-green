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


def test_isolated_workspace_cleanup_aborts_on_unverified_ownership(tmp_path: Path):
    """IsolatedWorkspace.cleanup() aborts without deleting files if marker signature is tampered."""
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    repo_cfg = RepoConfig(name="test-org/tampered-repo", default_branch="main")

    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()
    assert (ws_path / MARKER_FILENAME).exists()

    # Tamper with the marker file signature
    marker_file = ws_path / MARKER_FILENAME
    data = json.loads(marker_file.read_text(encoding="utf-8"))
    data["signature"] = "forged_signature_0000000000000000000000000000"
    marker_file.write_text(json.dumps(data), encoding="utf-8")

    # Call cleanup
    ws.cleanup()

    # Because ownership verification failed, workspace path was preserved
    assert ws.workspace_path is not None
    assert (ws.workspace_path / MARKER_FILENAME).exists()

    # Manual cleanup of tempdir for test cleanliness
    if ws._temp_dir:
        ws._temp_dir.cleanup()
        ws._temp_dir = None
        ws.workspace_path = None


def test_cleanup_fails_closed_on_missing_marker_during_normal_cleanup(tmp_path: Path):
    """
    IsolatedWorkspace.cleanup() must fail closed if marker is missing after normal initialization.
    Workspace directory and user files must be preserved untouched.
    """
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    repo_cfg = RepoConfig(name="test-org/normal-repo", default_branch="main")

    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()
    assert ws_path.exists()
    assert (ws_path / MARKER_FILENAME).exists()

    # Create a user file in the workspace
    user_file = ws_path / "work.txt"
    user_file.write_text("precious user work", encoding="utf-8")

    # Simulate marker being deleted during execution before cleanup
    (ws_path / MARKER_FILENAME).unlink()

    # Cleanup must abort and refuse to delete the workspace
    ws.cleanup()

    assert ws.workspace_path is not None
    assert ws.workspace_path.exists()
    assert user_file.exists()
    assert user_file.read_text(encoding="utf-8") == "precious user work"

    # Clean up tempdir manually for test hygiene
    if ws._temp_dir:
        ws._temp_dir.cleanup()
        ws._temp_dir = None
        ws.workspace_path = None


def test_cleanup_succeeds_on_missing_marker_during_partial_initialization(monkeypatch, tmp_path: Path):
    """
    When clone/setup fails during __enter__ before marker creation, cleanup() must safely
    remove the partially initialized TemporaryDirectory whose ownership is proven by the
    TemporaryDirectory instance.
    """
    import subprocess
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace, RepositoryManagerError

    repo_cfg = RepoConfig(name="test-org/fail-repo", default_branch="main")
    ws = IsolatedWorkspace(
        repo_config=repo_cfg,
        clone_url="https://github.com/test-org/fail.git",
        token="dummy",
    )

    def mock_fail(cmd, cwd=None, env=None, capture_output=None, check=None, *args, **kwargs):
        raise subprocess.CalledProcessError(returncode=128, cmd=cmd, stderr=b"fatal: clone failed")

    monkeypatch.setattr(subprocess, "run", mock_fail)

    with pytest.raises(RepositoryManagerError, match="Failed to clone remote repository"):
        ws.__enter__()

    # Directory was cleaned up safely and reference cleared
    assert ws.workspace_path is None
    assert ws._temp_dir is None


def test_cleanup_fails_closed_on_corrupt_marker(tmp_path: Path):
    """
    IsolatedWorkspace.cleanup() must fail closed if the marker file is corrupted or unreadable.
    Workspace directory and contents must remain preserved.
    """
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    repo_cfg = RepoConfig(name="test-org/corrupt-marker-repo", default_branch="main")

    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()
    assert ws_path.exists()
    marker_path = ws_path / MARKER_FILENAME
    assert marker_path.exists()

    # Corrupt the marker file with invalid JSON syntax
    marker_path.write_text("{corrupt: json syntax <<< invalid", encoding="utf-8")

    canary = ws_path / "canary.txt"
    canary.write_text("canary content", encoding="utf-8")

    ws.cleanup()

    # Must fail closed: workspace path and canary preserved
    assert ws.workspace_path is not None
    assert ws.workspace_path.exists()
    assert canary.exists()
    assert canary.read_text(encoding="utf-8") == "canary content"

    # Manual cleanup for test hygiene
    if ws._temp_dir:
        ws._temp_dir.cleanup()
        ws._temp_dir = None
        ws.workspace_path = None


def test_cleanup_fails_closed_on_missing_or_invalid_signing_key(tmp_path: Path):
    """
    IsolatedWorkspace.cleanup() must fail closed if the signing key is missing, truncated,
    or does not match the key used to sign the workspace marker.
    """
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    repo_cfg = RepoConfig(name="test-org/key-mismatch-repo", default_branch="main")

    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()
    assert ws_path.exists()

    canary = ws_path / "important.txt"
    canary.write_text("must survive", encoding="utf-8")

    # Invalidate the signing key in state_dir by overwriting it with truncated bytes
    key_path = state_dir / SIGNING_KEY_FILENAME
    assert key_path.exists()
    key_path.write_bytes(b"short")  # Invalid: <16 bytes

    ws.cleanup()

    # Must fail closed because fresh key will not match marker signature
    assert ws.workspace_path is not None
    assert ws.workspace_path.exists()
    assert canary.exists()
    assert canary.read_text(encoding="utf-8") == "must survive"

    # Manual cleanup for test hygiene
    if ws._temp_dir:
        ws._temp_dir.cleanup()
        ws._temp_dir = None
        ws.workspace_path = None


def test_cleanup_preserves_external_target_when_node_modules_is_junction_or_symlink(tmp_path: Path):
    """
    If workspace/node_modules itself is a Windows junction or POSIX symlink pointing to an
    external directory, cleanup() must remove the junction/symlink link without traversing
    or modifying any files inside the external target directory.
    """
    import os
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    ext_dir = tmp_path / "external_node_modules"
    ext_dir.mkdir()
    (ext_dir / "protected_pkg").mkdir()
    (ext_dir / "protected_pkg" / "index.js").write_text("export const safe = true;", encoding="utf-8")
    (ext_dir / ".astro").mkdir()
    (ext_dir / ".astro" / "data-store.json").write_text('{"untouched": true}', encoding="utf-8")

    repo_cfg = RepoConfig(name="test-org/nm-junction-repo", default_branch="main")
    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()

    # Create workspace node_modules as junction or symlink to external_node_modules
    ws_nm = ws_path / "node_modules"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(ext_dir.resolve()), str(ws_nm))
    else:
        try:
            ws_nm.symlink_to(ext_dir.resolve())
        except OSError:
            pytest.skip("Symlink creation requires elevated permissions on this platform")

    # Verify junction was created
    assert ws_nm.exists()

    ws.cleanup()

    # External directory must remain completely intact and untouched!
    assert ext_dir.exists()
    assert (ext_dir / "protected_pkg" / "index.js").exists()
    assert (ext_dir / "protected_pkg" / "index.js").read_text(encoding="utf-8") == "export const safe = true;"
    assert (ext_dir / ".astro" / "data-store.json").exists()
    assert (ext_dir / ".astro" / "data-store.json").read_text(encoding="utf-8") == '{"untouched": true}'

    # The workspace itself was cleaned up
    assert ws.workspace_path is None


def test_cleanup_preserves_external_target_when_cache_dir_is_junction_or_symlink(tmp_path: Path):
    """
    If workspace/node_modules/.astro or .cache is a Windows junction or POSIX symlink pointing
    to an external directory, cleanup() must remove the junction/symlink link without calling
    shutil.rmtree on or traversing the external target directory.
    """
    import os
    from dailygreen.config import RepoConfig
    from dailygreen.repository_manager import IsolatedWorkspace

    state_dir = tmp_path / "state"
    ext_astro = tmp_path / "external_astro_cache"
    ext_astro.mkdir()
    ext_data = ext_astro / "critical_data.json"
    ext_data.write_text('{"critical": true}', encoding="utf-8")

    ext_cache = tmp_path / "external_cache"
    ext_cache.mkdir()
    ext_cache_file = ext_cache / "cache_store.bin"
    ext_cache_file.write_bytes(b"do not delete me")

    repo_cfg = RepoConfig(name="test-org/cache-junction-repo", default_branch="main")
    ws = IsolatedWorkspace(repo_config=repo_cfg, state_dir=state_dir)
    ws_path = ws.__enter__()

    # Create normal workspace node_modules directory
    ws_nm = ws_path / "node_modules"
    ws_nm.mkdir(parents=True, exist_ok=True)

    ws_astro = ws_nm / ".astro"
    ws_cache = ws_nm / ".cache"

    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(ext_astro.resolve()), str(ws_astro))
        _winapi.CreateJunction(str(ext_cache.resolve()), str(ws_cache))
    else:
        try:
            ws_astro.symlink_to(ext_astro.resolve())
            ws_cache.symlink_to(ext_cache.resolve())
        except OSError:
            pytest.skip("Symlink creation requires elevated permissions on this platform")

    assert ws_astro.exists()
    assert ws_cache.exists()

    ws.cleanup()

    # Both external directories and their contents must be 100% untouched!
    assert ext_astro.exists()
    assert ext_data.exists()
    assert ext_data.read_text(encoding="utf-8") == '{"critical": true}'

    assert ext_cache.exists()
    assert ext_cache_file.exists()
    assert ext_cache_file.read_bytes() == b"do not delete me"

    # Workspace directory was cleaned up
    assert ws.workspace_path is None
