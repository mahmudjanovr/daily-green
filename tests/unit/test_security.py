"""Unit tests for security checks, path traversal rejection, secret scanning, and environment sanitization."""

import os
from pathlib import Path
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.security import (
    count_diff_lines,
    is_path_allowed,
    run_security_checks,
    sanitize_environment,
    scan_content_for_secrets,
    validate_path_safety,
)


def test_path_safety_valid(tmp_path: Path):
    safe_file = tmp_path / "docs" / "index.md"
    safe_file.parent.mkdir()
    safe_file.write_text("hello", encoding="utf-8")
    assert validate_path_safety(tmp_path, "docs/index.md") is True


def test_path_safety_traversal_rejected(tmp_path: Path):
    assert validate_path_safety(tmp_path, "../outside.txt") is False
    assert validate_path_safety(tmp_path, "docs/../../outside.txt") is False


def test_path_safety_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    symlink_target = outside / "secret.txt"
    symlink_target.write_text("secret", encoding="utf-8")

    link_path = tmp_path / "sneaky_link"
    try:
        os.symlink(symlink_target, link_path)
        assert validate_path_safety(tmp_path, "sneaky_link") is False
    except OSError:
        # On Windows without developer mode/admin rights symlink might be restricted
        pass


def test_is_path_allowed():
    repo = RepoConfig(
        name="org/repo",
        allowed_paths=["docs/**", "README.md"],
        denied_paths=["docs/internal/**"],
    )
    policy = SecurityPolicyConfig()

    # Allowed paths
    allowed, _ = is_path_allowed("README.md", repo, policy)
    assert allowed is True
    allowed, _ = is_path_allowed("docs/guide.md", repo, policy)
    assert allowed is True

    # Denied by repo denylist
    allowed, reason = is_path_allowed("docs/internal/secret.md", repo, policy)
    assert allowed is False
    assert "denied pattern" in reason

    # Denied by global policy (workflows, lockfiles, .env)
    allowed, reason = is_path_allowed(".github/workflows/deploy.yml", repo, policy)
    assert allowed is False
    allowed, reason = is_path_allowed(".env", repo, policy)
    assert allowed is False
    allowed, reason = is_path_allowed("package-lock.json", repo, policy)
    assert allowed is False

    # Denied by extension (.sh, .exe)
    allowed, reason = is_path_allowed("docs/run.sh", repo, policy)
    assert allowed is False
    assert "extension" in reason

    # Outside allowed paths
    allowed, reason = is_path_allowed("src/main.py", repo, policy)
    assert allowed is False
    assert "outside allowed paths" in reason


def test_scan_content_for_secrets():
    # AWS Key
    assert len(scan_content_for_secrets("export AWS_KEY=AKIAIOSFODNN7EXAMPLE")) > 0
    # GitHub Classic Token
    assert len(scan_content_for_secrets("token = 'ghp_123456789012345678901234567890123456'")) > 0
    # GitHub Fine-Grained Token
    assert len(scan_content_for_secrets("pat = 'github_pat_11AAAAAAA0123456789abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopq_rstuvwxyz012345'")) > 0
    # Private Key
    assert len(scan_content_for_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...")) > 0
    # Clean text
    assert len(scan_content_for_secrets("This is completely safe documentation text.")) == 0


def test_sanitize_environment():
    test_env = {
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "ghp_secrettoken123456",
        "GH_TOKEN": "secret",
        "GEMINI_API_KEY": "AIzaSySecret",
        "PAT": "my_pat",
        "MY_SECRET_KEY": "supersecret",
        "SAFE_VAR": "standard_value",
    }
    sanitized = sanitize_environment(test_env, extra_allowed_keys={"SAFE_VAR"})
    assert "GITHUB_TOKEN" not in sanitized
    assert "GH_TOKEN" not in sanitized
    assert "GEMINI_API_KEY" not in sanitized
    assert "PAT" not in sanitized
    assert "MY_SECRET_KEY" not in sanitized
    assert sanitized["PATH"] == "/usr/bin"
    assert sanitized["SAFE_VAR"] == "standard_value"
    assert sanitized["DAILYGREEN_SANDBOX"] == "1"


def test_count_diff_lines():
    diff = """--- a/docs/README.md
+++ b/docs/README.md
@@ -1,3 +1,4 @@
 # Title
-Old line 1
+New line 1
+New line 2
"""
    # 1 deletion + 2 additions = 3 changed lines
    assert count_diff_lines(diff) == 3


def test_run_security_checks_exceeds_max_lines(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"], max_diff_lines=5)
    policy = SecurityPolicyConfig(max_diff_lines=5)

    f = tmp_path / "README.md"
    f.write_text("safe content", encoding="utf-8")

    diff = "@@ -1,1 +1,10 @@\n" + "".join(f"+line {i}\n" for i in range(10))
    res = run_security_checks(tmp_path, ["README.md"], diff, repo, policy)
    assert res.passed is False
    assert any("exceeds maximum limit" in d for d in res.details)


def test_run_security_checks_secret_in_diff(tmp_path: Path):
    repo = RepoConfig(name="org/repo", allowed_paths=["README.md"], max_diff_lines=50)
    policy = SecurityPolicyConfig()

    f = tmp_path / "README.md"
    f.write_text("safe", encoding="utf-8")

    diff = "@@ -1,1 +1,2 @@\n+api_key = 'AKIA1234567890EXAMPLE'\n"
    res = run_security_checks(tmp_path, ["README.md"], diff, repo, policy)
    assert res.passed is False
    assert len(res.secrets_detected) > 0
