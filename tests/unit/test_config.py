"""Unit tests for configuration loading and repository allowlist validation."""

import pytest
from pathlib import Path
from dailygreen.config import (
    ConfigurationError,
    DailyGreenConfig,
    RepoConfig,
    SecurityPolicyConfig,
    load_config,
)


def test_repo_config_valid():
    repo = RepoConfig(
        name="my-org/my-repo",
        default_branch="main",
        enabled=True,
        allowed_paths=["docs/**", "README.md"],
        max_diff_lines=100,
    )
    assert repo.name == "my-org/my-repo"
    assert repo.default_branch == "main"
    assert repo.max_diff_lines == 100


def test_repo_config_invalid_name():
    with pytest.raises(ValueError):
        RepoConfig(name="invalid-name-without-slash")


def test_repo_config_diff_line_bounds():
    with pytest.raises(ValueError):
        RepoConfig(name="org/repo", max_diff_lines=0)
    with pytest.raises(ValueError):
        RepoConfig(name="org/repo", max_diff_lines=9999)


def test_allowlist_enforcement():
    cfg = DailyGreenConfig(
        repos=[
            RepoConfig(name="allowed-org/repo-1", enabled=True),
            RepoConfig(name="allowed-org/repo-2", enabled=False),
        ]
    )
    assert cfg.is_repo_authorized("allowed-org/repo-1") is True
    assert cfg.is_repo_authorized("allowed-org/repo-2") is False  # disabled
    assert cfg.is_repo_authorized("unauthorized-org/repo-x") is False  # not in list


def test_load_config_example_file(tmp_path: Path):
    policy_file = Path("config/policy.yml")
    repos_file = Path("config/repos.example.yml")
    cfg = load_config(repos_path=repos_file, policy_path=policy_file)
    assert cfg.enabled is True
    assert cfg.dry_run is True
    assert len(cfg.repos) == 2
    assert cfg.is_repo_authorized("example-org/astro-portfolio") is True
    assert cfg.is_repo_authorized("example-org/fastapi-service") is True


def test_load_config_missing_file_fails_closed():
    with pytest.raises(ConfigurationError):
        load_config(repos_path="nonexistent/repos.yml")


def test_load_config_kill_switch(monkeypatch):
    monkeypatch.setenv("DAILYGREEN_ENABLED", "false")
    cfg = load_config()
    assert cfg.enabled is False


@pytest.mark.parametrize("val", ["", "   ", "invalid", "maybe", "2", "default", "undefined"])
def test_load_config_kill_switch_fails_closed_on_empty_and_unrecognized(monkeypatch, val):
    """Empty, whitespace-only, or unrecognized DAILYGREEN_ENABLED values fail closed (disabled)."""
    monkeypatch.setenv("DAILYGREEN_ENABLED", val)
    cfg = load_config()
    assert cfg.enabled is False


@pytest.mark.parametrize("val", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"])
def test_load_config_kill_switch_explicit_true_values(monkeypatch, val):
    monkeypatch.setenv("DAILYGREEN_ENABLED", val)
    cfg = load_config()
    assert cfg.enabled is True


@pytest.mark.parametrize("val", ["false", "FALSE", "False", "0", "no", "NO", "off", "OFF", "  false  ", "  0 "])
def test_load_config_kill_switch_explicit_false_values(monkeypatch, val):
    monkeypatch.setenv("DAILYGREEN_ENABLED", val)
    cfg = load_config()
    assert cfg.enabled is False


def test_load_config_kill_switch_missing_defaults_to_true(monkeypatch):
    monkeypatch.delenv("DAILYGREEN_ENABLED", raising=False)
    cfg = load_config()
    assert cfg.enabled is True


def test_load_config_dry_run_override(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    cfg = load_config()
    assert cfg.dry_run is False

    # Explicit override takes precedence
    cfg2 = load_config(override_dry_run=True)
    assert cfg2.dry_run is True


@pytest.mark.parametrize("val", ["", "   ", "invalid", "maybe", "2", "default", "undefined"])
def test_load_config_dry_run_fails_safe_on_empty_and_unrecognized(monkeypatch, val):
    """Missing, empty, whitespace-only, or unrecognized values fail safe to True."""
    monkeypatch.setenv("DRY_RUN", val)
    cfg = load_config()
    assert cfg.dry_run is True


@pytest.mark.parametrize("val", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"])
def test_load_config_dry_run_explicit_true_values(monkeypatch, val):
    monkeypatch.setenv("DRY_RUN", val)
    cfg = load_config()
    assert cfg.dry_run is True


@pytest.mark.parametrize("val", ["false", "FALSE", "False", "0", "no", "NO", "off", "OFF", "  false  ", "  0 "])
def test_load_config_dry_run_explicit_false_values(monkeypatch, val):
    """Only explicit false values disable dry-run."""
    monkeypatch.setenv("DRY_RUN", val)
    cfg = load_config()
    assert cfg.dry_run is False


def test_load_config_dry_run_missing_defaults_to_true(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    cfg = load_config()
    assert cfg.dry_run is True


def test_repo_config_empty_allowed_paths_rejected():
    with pytest.raises(ValueError, match="at least one allowed path"):
        RepoConfig(name="org/repo", allowed_paths=[])


def test_repo_config_unsafe_allowed_path_rejected():
    with pytest.raises(ValueError, match="Unsafe path pattern"):
        RepoConfig(name="org/repo", allowed_paths=["../secret.txt"])
    with pytest.raises(ValueError, match="Unsafe path pattern"):
        RepoConfig(name="org/repo", allowed_paths=["/etc/shadow"])


def test_repo_config_unsupported_task_type_rejected():
    with pytest.raises(ValueError, match="Unsupported task type"):
        RepoConfig(name="org/repo", supported_task_types=["malicious_code_exec"])


def test_load_config_repo_max_diff_exceeds_policy_rejected(tmp_path: Path):
    policy_file = tmp_path / "policy.yml"
    policy_file.write_text("max_diff_lines: 50\n", encoding="utf-8")
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("""
repositories:
  - name: "org/repo"
    max_diff_lines: 100
    allowed_paths: ["docs/**"]
""", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="exceeds global security policy limit"):
        load_config(repos_path=repos_file, policy_path=policy_file)


def test_load_config_duplicate_repo_rejected(tmp_path: Path):
    policy_file = tmp_path / "policy.yml"
    policy_file.write_text("max_diff_lines: 150\n", encoding="utf-8")
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("""
repositories:
  - name: "org/repo"
    allowed_paths: ["docs/**"]
  - name: "org/repo"
    allowed_paths: ["README.md"]
""", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Duplicate repository definition"):
        load_config(repos_path=repos_file, policy_path=policy_file)
