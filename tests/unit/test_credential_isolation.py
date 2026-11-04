"""Unit tests verifying strict credential isolation, environment allowlisting, and secret redaction."""

import json
import logging
from dailygreen.reporting import StructuredJSONFormatter
from dailygreen.security import (
    redact_secrets,
    safe_git_command,
    sanitize_environment,
    scan_content_for_secrets,
)


def test_sanitize_environment_allowlist_drops_unknown():
    raw_env = {
        "PATH": "/usr/bin",
        "CUSTOM_APP_TOKEN": "secret_abc",
        "UNKNOWN_VARIABLE": "should_be_dropped",
        "GITHUB_AUTH": "ghp_123456789012345678901234567890123456",
        "SAFE_SYSTEM_VAR": "not_in_allowlist",
    }
    sanitized = sanitize_environment(raw_env)
    assert "CUSTOM_APP_TOKEN" not in sanitized
    assert "UNKNOWN_VARIABLE" not in sanitized
    assert "GITHUB_AUTH" not in sanitized
    assert "SAFE_SYSTEM_VAR" not in sanitized
    assert sanitized["PATH"] == "/usr/bin"
    assert sanitized["DAILYGREEN_SANDBOX"] == "1"
    assert sanitized["GIT_TERMINAL_PROMPT"] == "0"
    assert sanitized["GIT_CONFIG_NOSYSTEM"] == "1"


def test_sanitize_environment_drops_allowlisted_var_with_secret_value():
    """Even if a variable is in SAFE_ENV_ALLOWLIST (like TEMP), drop it if its value contains a secret."""
    raw_env = {
        "PATH": "/usr/bin",
        "TEMP": "AKIAIOSFODNN7EXAMPLE",  # AWS key pattern embedded in TEMP
        "TMP": "/tmp/normal",
    }
    sanitized = sanitize_environment(raw_env)
    assert "TEMP" not in sanitized
    assert sanitized["TMP"] == "/tmp/normal"


def test_redact_secrets_comprehensive():
    # GitHub Classic Token
    text1 = "Error connecting with token ghp_123456789012345678901234567890123456 in request"
    redacted1 = redact_secrets(text1)
    assert "ghp_" not in redacted1
    assert "***REDACTED_GITHUB_TOKEN***" in redacted1

    # GitHub Fine-Grained Token
    text2 = "PAT: github_pat_11AAAAAAA0123456789abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopq_rstuvwxyz012345"
    redacted2 = redact_secrets(text2)
    assert "github_pat_" not in redacted2
    assert "***REDACTED_GITHUB_PAT***" in redacted2

    # AWS Key
    text3 = "Failed using key AKIAIOSFODNN7EXAMPLE"
    redacted3 = redact_secrets(text3)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted3
    assert "***REDACTED_AWS_KEY***" in redacted3

    # URL with embedded credentials
    text4 = "Git clone failed: https://x-access-token:ghp_secrettoken@github.com/org/repo.git"
    redacted4 = redact_secrets(text4)
    assert "x-access-token" not in redacted4
    assert "https://***:***@github.com" in redacted4

    # Private key block
    text5 = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    redacted5 = redact_secrets(text5)
    assert "MIIEow" not in redacted5
    assert "***REDACTED_PRIVATE_KEY_BLOCK***" in redacted5


def test_safe_git_command_disables_hooks():
    cmd = ["git", "commit", "-m", "test"]
    safe = safe_git_command(cmd)
    assert safe[0] == "git"
    assert safe[1] == "-c"
    assert safe[2] == "core.hooksPath="
    assert safe[3] == "commit"


def test_structured_logger_redacts_secrets_in_logs():
    formatter = StructuredJSONFormatter()
    record = logging.LogRecord(
        name="dailygreen",
        level=logging.ERROR,
        pathname="delivery.py",
        lineno=50,
        msg="Failed with authorization ghp_123456789012345678901234567890123456",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)
    assert "ghp_" not in data["message"]
    assert "***REDACTED_GITHUB_TOKEN***" in data["message"]
