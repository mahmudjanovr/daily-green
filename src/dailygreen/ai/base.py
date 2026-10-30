"""Abstract base class for provider-neutral AI adapters."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from dailygreen.models import Task, TaskPlan


class AIAdapterError(Exception):
    """Raised when an AI adapter fails or produces invalid responses."""
    pass


class AIAdapterTimeoutError(AIAdapterError):
    """Raised when an AI adapter request times out."""
    pass


class AIAdapter(ABC):
    """Provider-neutral interface for AI-assisted task proposal, planning, and execution."""

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

    def select_relevant_files(
        self,
        task: Task,
        candidate_files: list[str],
        max_files: int = 5,
    ) -> list[str]:
        """
        Select only files relevant to the task to avoid sending the whole repo to the model.
        Prioritizes task.target_files, followed by matches in title and description.
        """
        relevant: list[str] = []
        for f in task.target_files:
            if f in candidate_files and f not in relevant:
                relevant.append(f)

        # Keyword matching on remaining candidates
        task_keywords = set((task.title + " " + task.description).lower().split())
        for f in candidate_files:
            if len(relevant) >= max_files:
                break
            if f not in relevant:
                f_tokens = set(Path(f).stem.lower().replace("-", "_").split("_"))
                if task_keywords & f_tokens:
                    relevant.append(f)

        # Ensure at least target_files are included even if not in candidate_files
        for f in task.target_files:
            if f not in relevant and len(relevant) < max_files:
                relevant.append(f)

        return relevant[:max_files]

    def create_plan(self, task: Task, repo_context: dict[str, Any]) -> Optional[TaskPlan]:
        """
        Optionally generate an AI-assisted structured task plan.
        Returns None by default to use the deterministic planner.
        """
        return None

    def explain_changes(self, modified_files: dict[str, str], task: Task) -> dict[str, str]:
        """
        Generate explanations for why each modified file was changed.
        """
        return {
            f: f"Applied targeted maintenance changes to satisfy '{task.title}'."
            for f in modified_files
        }

    def implement_task_with_plan(
        self,
        task: Task,
        plan: Optional[TaskPlan],
        repo_context: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        Context-aware execution returning (files_map, change_explanations).
        """
        files = self.implement_task(task, repo_context)
        explanations = self.explain_changes(files, task)
        return files, explanations
