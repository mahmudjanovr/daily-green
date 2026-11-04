"""Unit tests for Phase 3 configuration validation and environment variable overrides."""

import os
from unittest.mock import patch
from dailygreen.config import DailyGreenConfig, ExecutionConfig, RepoConfig, SecurityPolicyConfig, load_config


def test_execution_config_safe_defaults():
    """Verify default execution configuration is safe and bounded."""
    exec_cfg = ExecutionConfig()
    assert exec_cfg.max_tasks_per_run == 1
    assert exec_cfg.max_workers == 1
    assert exec_cfg.max_retries == 2
    assert exec_cfg.retry_backoff_factor == 1.0
    assert exec_cfg.task_timeout_seconds == 300


def test_execution_config_bounds_enforced():
    """Verify execution configuration enforces reasonable lower and upper bounds and strictly limits max_workers=1."""
    import pytest
    with pytest.raises(Exception):
        ExecutionConfig(max_workers=0)
    with pytest.raises(Exception):
        ExecutionConfig(max_workers=2)
    with pytest.raises(Exception):
        ExecutionConfig(max_workers=50)
    with pytest.raises(Exception):
        ExecutionConfig(max_tasks_per_run=0)
    with pytest.raises(Exception):
        ExecutionConfig(max_tasks_per_run=200)
    with pytest.raises(Exception):
        ExecutionConfig(max_retries=-1)
    with pytest.raises(Exception):
        ExecutionConfig(max_retries=20)


def test_load_config_with_phase3_env_vars():
    """Verify environment variables correctly override execution parameters."""
    env = {
        "DAILYGREEN_MAX_TASKS_PER_RUN": "5",
        "DAILYGREEN_MAX_WORKERS": "1",
        "DAILYGREEN_MAX_RETRIES": "4",
        "DAILYGREEN_RETRY_BACKOFF": "2.5",
        "DAILYGREEN_TASK_TIMEOUT": "600",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()
        assert cfg.execution.max_tasks_per_run == 5
        assert cfg.execution.max_workers == 1
        assert cfg.execution.max_retries == 4
        assert cfg.execution.retry_backoff_factor == 2.5
        assert cfg.execution.task_timeout_seconds == 600


def test_load_config_cli_overrides_take_precedence():
    """Verify explicit CLI arguments take precedence over environment variables."""
    env = {
        "DAILYGREEN_MAX_TASKS_PER_RUN": "10",
        "DAILYGREEN_MAX_WORKERS": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config(
            override_max_tasks=3,
            override_max_workers=1,
            override_max_retries=1,
        )
        assert cfg.execution.max_tasks_per_run == 3
        assert cfg.execution.max_workers == 1
        assert cfg.execution.max_retries == 1


def test_load_config_rejects_max_workers_greater_than_one():
    """Verify load_config rejects max_workers > 1 with clear validation error (DG3-01)."""
    import pytest
    env = {"DAILYGREEN_MAX_WORKERS": "2"}
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(Exception):
            load_config()
