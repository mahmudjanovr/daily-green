"""Gemini AI provider implementation using Google Gemini REST API."""

import json
import os
import re
from typing import Any, Optional
import httpx
from dailygreen.ai.base import AIAdapter, AIAdapterError, AIAdapterTimeoutError
from dailygreen.config import AIConfig
from dailygreen.models import RiskLevel, Task, TaskPlan, TaskSource


class GeminiAIAdapter(AIAdapter):
    """Adapter for Google Gemini models using direct HTTP API calls via httpx."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, config: AIConfig):
        self.config = config
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()

    def _ensure_api_key(self) -> str:
        if not self.api_key:
            raise AIAdapterError("GEMINI_API_KEY environment variable is not configured.")
        return self.api_key

    def _call_gemini(self, prompt: str, system_instruction: str = "") -> str:
        """Execute a text generation call to the Gemini API with timeout and budget constraints."""
        api_key = self._ensure_api_key()
        url = f"{self.BASE_URL}/{self.config.model}:generateContent?key={api_key}"

        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            }
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        req_timeout = float(self.config.timeout_seconds)
        httpx_timeout = httpx.Timeout(
            timeout=req_timeout,
            connect=min(10.0, req_timeout),
            read=req_timeout,
            write=min(10.0, req_timeout),
            pool=5.0,
        )

        try:
            with httpx.Client(timeout=httpx_timeout) as client:
                response = client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
                if response.status_code == 429:
                    raise AIAdapterError("Gemini API rate limit exceeded.")
                if response.status_code != 200:
                    raise AIAdapterError(f"Gemini API returned HTTP {response.status_code}: {response.text}")

                data = response.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise AIAdapterError("Gemini API returned no candidates.")

                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    raise AIAdapterError("Gemini API returned candidate with no text parts.")

                return parts[0].get("text", "").strip()
        except httpx.TimeoutException as e:
            raise AIAdapterTimeoutError(f"Gemini API request timed out after {self.config.timeout_seconds}s") from e
        except httpx.RequestError as e:
            raise AIAdapterError(f"Gemini network request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise AIAdapterError(f"Gemini response could not be parsed as JSON: {e}") from e

    def propose_tasks(self, repo_context: dict[str, Any]) -> list[Task]:
        """Ask Gemini to propose bounded maintenance tasks formatted as JSON."""
        system_prompt = (
            "You are a conservative code maintenance assistant. Propose at most 1 small, low-risk, "
            "verifiable maintenance task strictly within the allowed documentation paths. "
            "Never invent issues or propose modifications outside allowed paths. "
            "Respond ONLY with a JSON array of task objects matching this schema: "
            "[{\"id\": \"slug\", \"title\": \"...\", \"description\": \"...\", "
            "\"rationale\": \"...\", \"acceptance_criteria\": [\"...\"], "
            "\"risk_level\": \"low\", \"validation_strategy\": \"...\", \"target_files\": [\"...\"]}]"
        )

        repo_name = repo_context.get("repo_name", "unknown/repo")
        allowed_paths = repo_context.get("allowed_paths", ["docs/**", "README.md"])
        file_list = repo_context.get("file_list", [])

        user_prompt = (
            f"Repository: {repo_name}\n"
            f"Allowed Paths: {allowed_paths}\n"
            f"Candidate Files:\n" + "\n".join(file_list[:30]) + "\n\n"
            "Return valid JSON array only."
        )

        raw_text = self._call_gemini(user_prompt, system_instruction=system_prompt)

        # Extract JSON from potential code block
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
            if not isinstance(data, list):
                raise ValueError("Expected JSON array")

            tasks: list[Task] = []
            for item in data:
                tasks.append(
                    Task(
                        id=str(item.get("id", "ai-task")),
                        repo=repo_name,
                        title=str(item.get("title", "")),
                        description=str(item.get("description", "")),
                        rationale=str(item.get("rationale", "")),
                        acceptance_criteria=list(item.get("acceptance_criteria", [])),
                        risk_level=RiskLevel(item.get("risk_level", "low")),
                        validation_strategy=str(item.get("validation_strategy", "verify")),
                        source=TaskSource.AI,
                        target_files=list(item.get("target_files", [])),
                    )
                )
            return tasks
        except Exception as e:
            raise AIAdapterError(f"Failed to parse Gemini task proposal response: {e}") from e

    def create_plan(self, task: Task, repo_context: dict[str, Any]) -> Optional[TaskPlan]:
        """Ask Gemini to generate a structured execution plan for complex tasks."""
        system_prompt = (
            "You are a software maintenance planning assistant. Generate a structured, verifiable task plan. "
            "Respond ONLY with a JSON object matching this schema: "
            "{\"problem_statement\": \"...\", \"evidence_and_affected_files\": [\"...\"], "
            "\"proposed_solution\": \"...\", \"implementation_steps\": [\"...\"], "
            "\"expected_behavior\": \"...\", \"tests_required\": [\"...\"], "
            "\"risk_assessment\": \"...\", \"acceptance_criteria\": [\"...\"]}"
        )

        prompt = (
            f"Task: {task.title}\n"
            f"Description: {task.description}\n"
            f"Rationale: {task.rationale}\n"
            f"Target Files: {task.target_files}\n"
            f"Existing Acceptance Criteria: {task.acceptance_criteria}\n\n"
            "Return JSON plan object only."
        )

        try:
            raw_text = self._call_gemini(prompt, system_instruction=system_prompt)
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            return TaskPlan(
                task_id=task.id,
                problem_statement=str(data.get("problem_statement", task.description)),
                evidence_and_affected_files=list(data.get("evidence_and_affected_files", task.target_files)),
                proposed_solution=str(data.get("proposed_solution", task.rationale)),
                implementation_steps=list(data.get("implementation_steps", ["1. Apply changes"])),
                expected_behavior=str(data.get("expected_behavior", "Requirements satisfied")),
                tests_required=list(data.get("tests_required", [task.validation_strategy])),
                risk_assessment=str(data.get("risk_assessment", f"Risk level: {task.risk_level.value}")),
                acceptance_criteria=list(data.get("acceptance_criteria", task.acceptance_criteria)),
            )
        except Exception:
            return None

    def implement_task(self, task: Task, repo_context: dict[str, Any]) -> dict[str, str]:
        """Ask Gemini to generate updated file contents for the task."""
        system_prompt = (
            "You are a cautious code assistant. Apply the requested maintenance task accurately. "
            "Generate focused, minimal changes that respect repository policies and protected paths. "
            "Respond ONLY with a JSON object containing a 'files' map of relative path to full updated content: "
            "{\"files\": {\"path/to/file.md\": \"full file content...\"}}"
        )

        existing_files = repo_context.get("existing_files", {})
        prompt_parts = [
            f"Task: {task.title}",
            f"Description: {task.description}",
            f"Acceptance Criteria: {task.acceptance_criteria}",
            "Current file contents:",
        ]
        for f in task.target_files:
            content = existing_files.get(f, "")
            prompt_parts.append(f"--- File: {f} ---\n{content}\n")

        raw_text = self._call_gemini("\n".join(prompt_parts), system_instruction=system_prompt)

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
            files = data.get("files", {})
            if not isinstance(files, dict):
                raise ValueError("Response missing 'files' dictionary")
            return {k: str(v) for k, v in files.items()}
        except Exception as e:
            raise AIAdapterError(f"Failed to parse Gemini task implementation response: {e}") from e

    def explain_diff(self, diff: str) -> str:
        """Ask Gemini to summarize a unified diff concisely for the PR body."""
        prompt = (
            "Summarize the following git diff in 2-3 clear, factual sentences for a Pull Request description. "
            "Do not fabricate details:\n\n" + diff[:3000]
        )
        return self._call_gemini(prompt)

    def explain_changes(self, modified_files: dict[str, str], task: Task) -> dict[str, str]:
        """Explain why each modified file was changed."""
        explanations: dict[str, str] = {}
        for f in modified_files:
            prompt = (
                f"In 1 sentence, explain why modifying '{f}' is necessary to resolve task '{task.title}':\n"
                f"Task Description: {task.description}"
            )
            try:
                explanations[f] = self._call_gemini(prompt)
            except Exception:
                explanations[f] = f"Modified '{f}' to fulfill requirements of '{task.title}'."
        return explanations
