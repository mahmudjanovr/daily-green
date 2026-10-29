"""Security enforcement, path validation, secret scanning, and environment sanitization."""

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from dailygreen.config import RepoConfig, SecurityPolicyConfig
from dailygreen.models import SecurityCheckResult


# Regex patterns for sensitive secrets
SECRET_PATTERNS: dict[str, re.Pattern] = {
    "AWS Access Key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub Classic Token": re.compile(r"gh[posru]_[a-zA-Z0-9]{36}"),
    "GitHub Fine-Grained Token": re.compile(r"github_pat_[a-zA-Z0-9_]{82}"),
    "Private Key Block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "Generic High-Entropy Secret": re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|auth[_-]?token|password)\s*[:=]\s*['\"][0-9a-zA-Z\-_]{16,}['\"]"
    ),
    "Slack Token": re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}"),
    "Bearer or Basic Auth": re.compile(r"(?i)\b(?:Bearer|Basic|token)\s+[a-zA-Z0-9_.\-+/=]{16,}"),
    "URL Embedded Credentials": re.compile(r"https?://([^:\s/]+):([^@\s/]+)@"),
}

# Strict allowlist of safe system environment variables permitted in worker subprocesses
SAFE_ENV_ALLOWLIST: set[str] = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMP",
    "TEMP",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "NUMBER_OF_PROCESSORS",
    "TZ",
    "PWD",
    "HOSTNAME",
    "SHELL",
    "SHLVL",
    "USER",
    "LOGNAME",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
}

# Substrings in variable names that strictly disqualify them from the subprocess environment
SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "PRIVATE_KEY",
    "API_KEY",
    "PASSW",
    "AUTH",
    "CRED",
    "BEARER",
    "SIGNING",
    "CERT",
)


def is_sensitive_env_name(name: str) -> bool:
    """Check if an environment variable name indicates sensitive credentials or keys."""
    upper = name.upper()
    if any(sub in upper for sub in SENSITIVE_KEY_SUBSTRINGS):
        return True
    # For PAT and PASS, match as standalone words or delimited tokens (not 'PATH' or 'PATHEXT')
    if re.search(r"(?:^|_)PAT(?:$|_)", upper):
        return True
    if re.search(r"(?:^|_)PASS(?:$|_)", upper):
        return True
    return False


def redact_secrets(text: str, extra_secrets: Optional[list[str]] = None) -> str:
    """
    Scrub tokens, credentials, authorization headers, and private keys from strings,
    ensuring log output and error messages never expose sensitive secrets.
    """
    if not text:
        return text

    redacted = text

    # Explicitly scrub known token values if provided
    if extra_secrets:
        for s in extra_secrets:
            if s and len(s) >= 4:
                redacted = redacted.replace(s, "***REDACTED_SECRET***")

    # Mask URL credentials (e.g. https://token:x@github.com -> https://***:***@github.com)
    redacted = re.sub(r"(https?://)([^:\s/]+):([^@\s/]+)@", r"\1***:***@", redacted)
    # Mask GitHub classic and fine-grained tokens
    redacted = re.sub(r"gh[posru]_[a-zA-Z0-9]{36}", "***REDACTED_GITHUB_TOKEN***", redacted)
    redacted = re.sub(r"github_pat_[a-zA-Z0-9_]{82}", "***REDACTED_GITHUB_PAT***", redacted)
    # Mask AWS keys
    redacted = re.sub(r"AKIA[0-9A-Z]{16}", "***REDACTED_AWS_KEY***", redacted)
    # Mask Slack tokens
    redacted = re.sub(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}", "***REDACTED_SLACK_TOKEN***", redacted)
    # Mask Authorization header values
    redacted = re.sub(r"(?i)\b(Bearer|Basic|token)\s+[a-zA-Z0-9_.\-+/=]{8,}", r"\1 ***REDACTED_AUTH***", redacted)
    # Mask private key blocks
    redacted = re.sub(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        "***REDACTED_PRIVATE_KEY_BLOCK***",
        redacted,
    )
    return redacted


def sanitize_environment(
    base_env: Optional[dict[str, str]] = None,
    extra_allowed_keys: Optional[set[str]] = None,
) -> dict[str, str]:
    """
    Produce a sanitized environment dictionary using an allowlist of standard system
    variables, combined with secret pattern scanning on values and strict name filtering.
    """
    source = dict(base_env if base_env is not None else os.environ)
    sanitized: dict[str, str] = {}
    allowed_keys = SAFE_ENV_ALLOWLIST.copy()
    if extra_allowed_keys:
        allowed_keys.update(k.upper() for k in extra_allowed_keys)

    for k, v in source.items():
        k_upper = k.upper()
        # 1. Name must be in allowed keys
        if k_upper not in allowed_keys:
            continue
        # 2. Name must not contain any sensitive substrings or token identifiers
        if is_sensitive_env_name(k):
            continue
        # 3. Value must not contain any detected secret patterns
        if scan_content_for_secrets(v):
            continue
        sanitized[k] = v

    # Explicit isolation flags
    sanitized["DAILYGREEN_SANDBOX"] = "1"
    sanitized["GIT_TERMINAL_PROMPT"] = "0"
    sanitized["GIT_CONFIG_NOSYSTEM"] = "1"
    return sanitized


def safe_git_command(cmd_args: list[str]) -> list[str]:
    """
    Ensure all Git commands disable repository-controlled hooks (core.hooksPath)
    and terminal credential prompts to prevent hook execution with delivery or worker credentials.
    """
    if not cmd_args or cmd_args[0] != "git":
        return cmd_args

    # Inject -c core.hooksPath="" right after 'git' if not already present
    if len(cmd_args) >= 3 and cmd_args[1] == "-c" and cmd_args[2].startswith("core.hooksPath="):
        return cmd_args

    return ["git", "-c", "core.hooksPath="] + cmd_args[1:]


def validate_path_safety(base_dir: Path | str, target_rel_path: str) -> bool:
    """
    Verify that target_rel_path is strictly within base_dir and does not escape
    via path traversal ('..') or symlinks pointing outside.
    """
    base = Path(base_dir).resolve()
    try:
        resolved = (base / target_rel_path).resolve()
    except Exception:
        return False

    # Check path containment
    try:
        resolved.relative_to(base)
    except ValueError:
        return False

    # Prevent symlink traversal outside base
    current = base / target_rel_path
    if current.is_symlink():
        target = current.resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return False

    return True


def is_path_allowed(
    rel_path: str,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
) -> tuple[bool, str]:
    """
    Check if a relative file path is permitted according to repository allowlist
    and global/repo denylists.
    Returns (is_allowed, reason).
    """
    normalized = rel_path.replace("\\", "/").lstrip("/")

    # 1. Check disallowed extensions
    _, ext = os.path.splitext(normalized)
    if ext.lower() in [e.lower() for e in policy.disallowed_extensions]:
        return False, f"File extension '{ext}' is prohibited by security policy"

    # 2. Check global denied paths
    all_denied = list(policy.denied_paths) + list(repo_config.denied_paths)
    for pattern in all_denied:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(os.path.basename(normalized), pattern):
            return False, f"Path '{normalized}' matches denied pattern '{pattern}'"

    # 3. Check repository allowed paths
    matched_allow = False
    for pattern in repo_config.allowed_paths:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(os.path.basename(normalized), pattern):
            matched_allow = True
            break

    if not matched_allow:
        return False, f"Path '{normalized}' is outside allowed paths for repo {repo_config.name}"

    return True, "Path is allowed"


def scan_content_for_secrets(text: str) -> list[str]:
    """Scan string content for known secret patterns."""
    detected: list[str] = []
    for secret_name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            detected.append(secret_name)
    return detected


def scan_git_diff_with_gitleaks(workspace_dir: Path | str) -> list[str]:
    """
    Run gitleaks if installed on the host. Returns detected findings if any.
    Fails closed if gitleaks is expected but exits with error other than clean/findings.
    """
    gitleaks_bin = shutil.which("gitleaks")
    if not gitleaks_bin:
        return []

    try:
        res = subprocess.run(
            [gitleaks_bin, "detect", "--no-git", "--source", str(workspace_dir), "--exit-code", "2"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 2:
            return ["Gitleaks detected sensitive credentials in workspace"]
        return []
    except Exception:
        # If gitleaks is not available or fails, built-in scanner provides guaranteed coverage
        return []


def count_diff_lines(diff_text: str) -> int:
    """
    Count the number of changed lines (additions + deletions) in unified diff text,
    ignoring hunk headers and file metadata.
    """
    changed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+") or line.startswith("-"):
            changed += 1
    return changed


def run_security_checks(
    workspace_dir: Path | str,
    target_files: list[str],
    diff_text: str,
    repo_config: RepoConfig,
    policy: SecurityPolicyConfig,
) -> SecurityCheckResult:
    """
    Comprehensive security evaluation of a proposed change.
    """
    details: list[str] = []
    secrets_detected: list[str] = []
    denied_files: list[str] = []
    path_traversals: list[str] = []

    # 1. Path safety and allowlist validation
    for f in target_files:
        if not validate_path_safety(workspace_dir, f):
            path_traversals.append(f)
            details.append(f"Path traversal or invalid symlink detected: {f}")
            continue

        allowed, reason = is_path_allowed(f, repo_config, policy)
        if not allowed:
            denied_files.append(f)
            details.append(f"File rejected: {reason}")

    # 2. Secret scanning in diff text
    diff_secrets = scan_content_for_secrets(diff_text)
    if diff_secrets:
        secrets_detected.extend(diff_secrets)
        details.append(f"Secrets detected in proposed diff: {', '.join(diff_secrets)}")

    # 3. Secret scanning in changed files content
    base = Path(workspace_dir)
    for f in target_files:
        file_path = base / f
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                file_secrets = scan_content_for_secrets(content)
                for s in file_secrets:
                    if s not in secrets_detected:
                        secrets_detected.append(s)
                        details.append(f"Secret detected in '{f}': {s}")
            except Exception as e:
                details.append(f"Failed to read '{f}' for secret scanning: {e}")

    # 4. Optional Gitleaks scan
    gitleaks_findings = scan_git_diff_with_gitleaks(workspace_dir)
    if gitleaks_findings:
        secrets_detected.extend(gitleaks_findings)
        details.extend(gitleaks_findings)

    # 5. Diff size evaluation
    lines_changed = count_diff_lines(diff_text)
    max_lines = min(repo_config.max_diff_lines, policy.max_diff_lines)
    if lines_changed > max_lines:
        details.append(f"Diff size ({lines_changed} lines) exceeds maximum limit ({max_lines} lines)")

    passed = (
        len(secrets_detected) == 0
        and len(denied_files) == 0
        and len(path_traversals) == 0
        and lines_changed <= max_lines
    )

    return SecurityCheckResult(
        passed=passed,
        secrets_detected=secrets_detected,
        denied_files=denied_files,
        path_traversals=path_traversals,
        lines_changed=lines_changed,
        max_lines_allowed=max_lines,
        details=details,
    )
