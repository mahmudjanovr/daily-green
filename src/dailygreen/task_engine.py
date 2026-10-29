"""Task implementation engine: applies deterministic or AI changes to the workspace."""

import re
import subprocess
from pathlib import Path
from typing import Optional
from dailygreen.ai.base import AIAdapter, AIAdapterError
from dailygreen.models import Task, TaskSource
from dailygreen.security import validate_path_safety


class TaskEngineError(Exception):
    """Raised when applying a task fails."""
    pass


def apply_deterministic_formatting(workspace_dir: Path, target_file: str) -> None:
    """Strip trailing whitespace from lines and ensure clean trailing newline."""
    file_path = workspace_dir / target_file
    if not file_path.exists():
        raise TaskEngineError(f"Target file '{target_file}' does not exist")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    cleaned_lines = [line.rstrip(" \t") for line in lines]
    new_content = "\n".join(cleaned_lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    file_path.write_text(new_content, encoding="utf-8")


def apply_deterministic_typo_fix(workspace_dir: Path, target_file: str, typo: str, replacement: str) -> None:
    """Replace common typo with corrected word, preserving case where possible."""
    file_path = workspace_dir / target_file
    if not file_path.exists():
        raise TaskEngineError(f"Target file '{target_file}' does not exist")

    content = file_path.read_text(encoding="utf-8", errors="replace")

    def _replace_match(m: re.Match) -> str:
        word = m.group(0)
        if word.isupper():
            return replacement.upper()
        if word[0].isupper():
            return replacement.capitalize()
        return replacement.lower()

    pattern = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
    new_content = pattern.sub(_replace_match, content)

    if new_content == content:
        raise TaskEngineError(f"Typo '{typo}' was not found in '{target_file}'")

    file_path.write_text(new_content, encoding="utf-8")


def apply_deterministic_link_fix(workspace_dir: Path, target_file: str, broken_target: str) -> None:
    """
    Safely fix broken relative link in markdown file by converting to plaintext reference
    or updating to existing file if target was misspelled.
    """
    file_path = workspace_dir / target_file
    if not file_path.exists():
        raise TaskEngineError(f"Target file '{target_file}' does not exist")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    # Replace [text](broken_target) with `text` or valid link
    # If broken target has a simple typo like missing .md or case difference, check parent
    target_clean = broken_target.split("#")[0].split("?")[0]
    fixed_name = None

    parent_dir = file_path.parent
    for item in parent_dir.iterdir():
        if item.name.lower() == Path(target_clean).name.lower():
            fixed_name = item.name
            break

    if fixed_name:
        new_content = content.replace(f"({broken_target})", f"({fixed_name})")
    else:
        # Neutralize broken link into styled text: [link_text](broken) -> `link_text`
        pattern = re.compile(rf"\[([^\]]+)\]\({re.escape(broken_target)}\)")
        new_content = pattern.sub(r"`\1`", content)

    if new_content == content:
        raise TaskEngineError(f"Broken link '{broken_target}' could not be safely replaced in '{target_file}'")

    file_path.write_text(new_content, encoding="utf-8")


def get_git_diff(workspace_dir: Path) -> str:
    """Retrieve unified git diff of all modifications in the workspace."""
    try:
        # First ensure untracked files are staged if any
        subprocess.run(
            ["git", "add", "-N", "."],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        res = subprocess.run(
            ["git", "diff", "--unified=3"],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout
    except Exception as e:
        raise TaskEngineError(f"Failed to generate git diff: {e}") from e


def implement_task(
    workspace_dir: Path,
    task: Task,
    ai_adapter: Optional[AIAdapter] = None,
) -> str:
    """
    Apply task changes to workspace and return the generated git diff.
    Raises TaskEngineError if implementation produces no changes or fails.
    """
    # 1. Deterministic tasks
    if task.source == TaskSource.DETERMINISTIC:
        meta = task.metadata
        if meta.get("format_type") == "whitespace_and_eof":
            for f in task.target_files:
                apply_deterministic_formatting(workspace_dir, f)
        elif meta.get("typo") and meta.get("replacement"):
            for f in task.target_files:
                apply_deterministic_typo_fix(workspace_dir, f, meta["typo"], meta["replacement"])
        elif meta.get("broken_target"):
            for f in task.target_files:
                apply_deterministic_link_fix(workspace_dir, f, meta["broken_target"])
        else:
            raise TaskEngineError(f"Unknown deterministic task metadata: {meta}")

    # 2. Backlog tasks with explicit patch or instructions
    elif task.source == TaskSource.BACKLOG:
        if task.patch:
            # Apply unified patch
            res = subprocess.run(
                ["git", "apply", "--ignore-whitespace"],
                input=task.patch,
                cwd=str(workspace_dir),
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                raise TaskEngineError(f"Failed to apply backlog patch: {res.stderr}")
        else:
            # If backlog item is documentation improvement without explicit patch, use AI if available
            if not ai_adapter:
                raise TaskEngineError("Backlog task requires AI adapter to implement but none was provided")
            _implement_via_ai(workspace_dir, task, ai_adapter)

    # 3. Issue or AI tasks
    elif task.source in (TaskSource.AI, TaskSource.ISSUE):
        if not ai_adapter:
            raise TaskEngineError(f"Task from source '{task.source}' requires an AI adapter")
        _implement_via_ai(workspace_dir, task, ai_adapter)

    else:
        raise TaskEngineError(f"Unsupported task source: {task.source}")

    # Compute diff
    diff = get_git_diff(workspace_dir)
    if not diff.strip():
        raise TaskEngineError("Task implementation produced an empty diff. Fabrication is strictly prohibited.")

    return diff


def _implement_via_ai(workspace_dir: Path, task: Task, ai_adapter: AIAdapter) -> None:
    """Read target files, request AI implementation, validate paths, and write changes."""
    existing_files: dict[str, str] = {}
    for f in task.target_files:
        p = workspace_dir / f
        if p.exists() and p.is_file():
            existing_files[f] = p.read_text(encoding="utf-8", errors="replace")

    context = {
        "repo_name": task.repo,
        "existing_files": existing_files,
    }

    try:
        new_files = ai_adapter.implement_task(task, context)
    except Exception as e:
        raise TaskEngineError(f"AI adapter failed to implement task '{task.id}': {e}") from e

    if not new_files:
        raise TaskEngineError("AI adapter returned no file modifications.")

    for rel_path, content in new_files.items():
        if not validate_path_safety(workspace_dir, rel_path):
            raise TaskEngineError(f"AI attempted unsafe path traversal: '{rel_path}'")

        target_file = workspace_dir / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")
