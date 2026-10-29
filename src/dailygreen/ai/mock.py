"""Mock AI adapter for deterministic unit and integration tests."""

from typing import Any, Optional
from dailygreen.ai.base import AIAdapter, AIAdapterError
from dailygreen.models import RiskLevel, Task, TaskSource


class MockAIAdapter(AIAdapter):
    """Deterministic mock AI adapter for testing without external API calls or credentials."""

    def __init__(
        self,
        should_fail: bool = False,
        should_timeout: bool = False,
        malformed_output: bool = False,
        custom_tasks: Optional[list[Task]] = None,
        custom_implementation: Optional[dict[str, str]] = None,
    ):
        self.should_fail = should_fail
        self.should_timeout = should_timeout
        self.malformed_output = malformed_output
        self.custom_tasks = custom_tasks
        self.custom_implementation = custom_implementation
        self.calls: list[dict[str, Any]] = []

    def propose_tasks(self, repo_context: dict[str, Any]) -> list[Task]:
        self.calls.append({"method": "propose_tasks", "context": repo_context})
        if self.should_timeout:
            raise AIAdapterError("Mock AI provider request timed out after 30s")
        if self.should_fail:
            raise AIAdapterError("Mock AI provider encountered an upstream API error")
        if self.malformed_output:
            # Simulate returning invalid / malformed task structure
            raise AIAdapterError("AI response was malformed JSON or failed schema validation")

        if self.custom_tasks is not None:
            return self.custom_tasks

        repo_name = repo_context.get("repo_name", "unknown/repo")
        return [
            Task(
                id="mock-ai-doc-improvement",
                repo=repo_name,
                title="Improve documentation clarity in README",
                description="Refine documentation wording to improve developer readability.",
                rationale="Improves onboarding experience for contributors.",
                acceptance_criteria=["README wording is clear and concise"],
                risk_level=RiskLevel.LOW,
                validation_strategy="docs_verification",
                source=TaskSource.AI,
                target_files=["README.md"],
            )
        ]

    def implement_task(self, task: Task, repo_context: dict[str, Any]) -> dict[str, str]:
        self.calls.append({"method": "implement_task", "task": task.id, "context": repo_context})
        if self.should_timeout:
            raise AIAdapterError("Mock AI provider request timed out during implementation")
        if self.should_fail:
            raise AIAdapterError("Mock AI provider implementation failure")
        if self.malformed_output:
            raise AIAdapterError("AI output schema validation failed: missing required file content")

        if self.custom_implementation is not None:
            return self.custom_implementation

        # Default safe mock implementation for target files
        result: dict[str, str] = {}
        for f in task.target_files:
            existing = repo_context.get("existing_files", {}).get(f, "# Documentation\n")
            result[f] = existing + "\n<!-- DailyGreen automated enhancement: documentation clarity verified -->\n"
        return result

    def explain_diff(self, diff: str) -> str:
        self.calls.append({"method": "explain_diff", "diff": diff})
        if self.should_fail:
            raise AIAdapterError("Mock AI provider failed to explain diff")
        return "This pull request makes minor documentation improvements verified against security policies."
