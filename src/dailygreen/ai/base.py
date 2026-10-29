"""Abstract base class for provider-neutral AI adapters."""

from abc import ABC, abstractmethod
from typing import Any
from dailygreen.models import Task


class AIAdapterError(Exception):
    """Raised when an AI adapter fails or produces invalid responses."""
    pass


class AIAdapter(ABC):
    """Provider-neutral interface for AI-assisted task proposal and implementation."""

    @abstractmethod
    def propose_tasks(self, repo_context: dict[str, Any]) -> list[Task]:
        """
        Propose bounded, low-risk maintenance tasks given repository context.
        Must return structured Task instances or an empty list.
        """
        pass

    @abstractmethod
    def implement_task(self, task: Task, repo_context: dict[str, Any]) -> dict[str, str]:
        """
        Generate file changes for the given task.
        Returns a dictionary mapping relative file path -> new file content.
        """
        pass

    @abstractmethod
    def explain_diff(self, diff: str) -> str:
        """
        Generate a concise, human-readable explanation of a verified diff for PR description.
        """
        pass
