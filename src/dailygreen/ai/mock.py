"""Mock AI adapter for deterministic unit and integration tests."""

from typing import Any, Optional
from dailygreen.ai.base import AIAdapter, AIAdapterError, AIAdapterTimeoutError
from dailygreen.models import RiskLevel, Task, TaskPlan, TaskSource


class MockAIAdapter(AIAdapter):
    """Deterministic mock AI adapter for testing without external API calls or credentials."""

    def __init__(
        self,
        should_fail: bool = False,
        should_timeout: bool = False,
        malformed_output: bool = False,
        custom_tasks: Optional[list[Task]] = None,
        custom_implementation: Optional[dict[str, str]] = None,
        custom_plan: Optional[TaskPlan] = None,
    ):
        self.should_fail = should_fail
        self.should_timeout = should_timeout
        self.malformed_output = malformed_output
        self.custom_tasks = custom_tasks
        self.custom_implementation = custom_implementation
        self.custom_plan = custom_plan
        self.calls: list[dict[str, Any]] = []

    def propose_tasks(self, repo_context: dict[str, Any]) -> list[Task]:
        self.calls.append({"method": "propose_tasks", "context": repo_context})
        if self.should_timeout:
            raise AIAdapterTimeoutError("Mock AI provider request timed out after 30s")
        if self.should_fail:
            raise AIAdapterError("Mock AI provider encountered an upstream API error")
        if self.malformed_output:
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
            raise AIAdapterTimeoutError("Mock AI provider request timed out during implementation")
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
            is_link_task = (
                "link" in task.id.lower()
                or "link" in task.title.lower()
                or "link" in task.validation_strategy.lower()
                or any("link" in ac.lower() for ac in task.acceptance_criteria)
            )
            if is_link_task:
                # Add a valid markdown link reference to an existing related file if available, avoiding self-links
                from pathlib import Path as P
                candidates = [
                    k for k in repo_context.get("existing_files", {}).keys()
                    if k != f and P(k).name.lower() not in ("license", "license.md", "license.txt", ".gitignore")
                ]
                if candidates:
                    link_target = candidates[0]
                elif P(f).name.lower() == "readme.md":
                    link_target = "docs/guide.md"
                else:
                    link_target = "../README.md" if ("/" in f.replace("\\", "/")) else "README.md"
                result[f] = existing.rstrip() + f"\n\nSee [Documentation Guide]({link_target}) for reference.\n"
            else:
                result[f] = existing.rstrip() + "\n\nUpdated documentation section for improved clarity.\n"
        return result

    def explain_diff(self, diff: str) -> str:
        self.calls.append({"method": "explain_diff", "diff": diff})
        if self.should_fail:
            raise AIAdapterError("Mock AI provider failed to explain diff")
        return "This pull request makes minor documentation improvements verified against security policies."

    def create_plan(self, task: Task, repo_context: dict[str, Any]) -> Optional[TaskPlan]:
        self.calls.append({"method": "create_plan", "task": task.id, "context": repo_context})
        if self.custom_plan:
            return self.custom_plan
        return None

    def explain_changes(self, modified_files: dict[str, str], task: Task) -> dict[str, str]:
        self.calls.append({"method": "explain_changes", "files": list(modified_files.keys()), "task": task.id})
        return {
            f: f"Documentation improvement applied to '{f}' in accordance with task '{task.id}'."
            for f in modified_files
        }
