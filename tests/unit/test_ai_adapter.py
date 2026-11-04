"""Unit tests for AI adapters, factory instantiation, error handling, timeouts, and fallbacks."""

import pytest
from dailygreen.ai import AIAdapterError, GeminiAIAdapter, MockAIAdapter, get_ai_adapter
from dailygreen.config import AIConfig
from dailygreen.models import RiskLevel, Task, TaskSource


def test_mock_ai_adapter_success():
    adapter = MockAIAdapter()
    context = {"repo_name": "org/repo", "file_list": ["README.md"]}
    tasks = adapter.propose_tasks(context)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == TaskSource.AI
    assert task.risk_level == RiskLevel.LOW
    assert task.target_files == ["README.md"]

    impl = adapter.implement_task(task, {"existing_files": {"README.md": "# Title\n"}})
    assert "README.md" in impl
    assert "# Title" in impl["README.md"]

    summary = adapter.explain_diff("diff text")
    assert "pull request" in summary.lower()


def test_mock_ai_adapter_failure():
    adapter = MockAIAdapter(should_fail=True)
    with pytest.raises(AIAdapterError) as exc_info:
        adapter.propose_tasks({})
    assert "upstream API error" in str(exc_info.value)

    with pytest.raises(AIAdapterError):
        adapter.implement_task(
            Task(
                id="t1",
                repo="org/repo",
                title="T",
                description="D",
                rationale="R",
                validation_strategy="V",
                source=TaskSource.AI,
            ),
            {},
        )


def test_mock_ai_adapter_timeout():
    adapter = MockAIAdapter(should_timeout=True)
    with pytest.raises(AIAdapterError) as exc_info:
        adapter.propose_tasks({})
    assert "timed out" in str(exc_info.value)


def test_mock_ai_adapter_malformed():
    adapter = MockAIAdapter(malformed_output=True)
    with pytest.raises(AIAdapterError) as exc_info:
        adapter.propose_tasks({})
    assert "malformed" in str(exc_info.value) or "validation" in str(exc_info.value)


def test_ai_factory():
    mock_cfg = AIConfig(provider="mock")
    adapter = get_ai_adapter(mock_cfg)
    assert isinstance(adapter, MockAIAdapter)

    gemini_cfg = AIConfig(provider="gemini")
    adapter2 = get_ai_adapter(gemini_cfg)
    assert isinstance(adapter2, GeminiAIAdapter)

    with pytest.raises(AIAdapterError):
        get_ai_adapter(AIConfig(provider="unsupported_provider"))


def test_gemini_missing_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = GeminiAIAdapter(AIConfig(provider="gemini"))
    with pytest.raises(AIAdapterError) as exc:
        adapter.propose_tasks({"repo_name": "org/repo"})
    assert "GEMINI_API_KEY" in str(exc.value)
