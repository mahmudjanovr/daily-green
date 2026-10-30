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


FENCE_PATTERN = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")


def format_markdown_line(line: str) -> str:
    """
    Format a single line of markdown:
    - If the line is empty or whitespace-only, strip to empty string.
    - If the line has content and ends with exactly two trailing spaces (Markdown hard line break),
      preserve the two trailing spaces and strip any unwanted whitespace before them.
    - Otherwise, strip all trailing whitespace (spaces and tabs).
    """
    if not line.strip():
        return ""

    # Check for Markdown hard break: exactly two trailing spaces on a line with content
    if line.endswith("  ") and not line.endswith("   ") and not line.endswith("\t"):
        base = line[:-2].rstrip(" \t")
        if base:
            return base + "  "
        return ""

    return line.rstrip(" \t")


def format_markdown_content(content: str) -> tuple[str, bool]:
    """
    Format markdown text preserving line endings, semantic hard breaks, and code block contents:
    - Code blocks fenced with ``` (triple backticks) or ~~~ (triple tildes) are preserved verbatim.
    - Indented code blocks (4 spaces or tabs following blank line) are preserved verbatim.
    - Unclosed fences are preserved verbatim to EOF.
    - Outside code blocks, CommonMark hard breaks (two trailing spaces) are preserved,
      while ordinary trailing whitespace and blank lines are cleaned.
    Returns (formatted_content, has_changes).
    """
    if not content:
        return "", False

    # Detect predominant line ending
    is_crlf = "\r\n" in content
    line_ending = "\r\n" if is_crlf else "\n"

    lines = content.splitlines()
    cleaned_lines: list[str] = []

    in_fence = False
    fence_char = ""
    fence_len = 0
    in_indented_code = False
    prev_was_blank = True

    for line in lines:
        if in_fence:
            # Code block content: preserve completely verbatim
            cleaned_lines.append(line)
            # Check for closing fence matching opening fence character and length >= fence_len
            close_pattern = rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$"
            if re.match(close_pattern, line):
                in_fence = False
                fence_char = ""
                fence_len = 0
            continue

        # Check for fence opening: 0-3 spaces followed by 3+ backticks or tildes
        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            f_chars = fence_match.group(1)
            info = fence_match.group(2).strip()
            # CommonMark rule: backtick fence info string cannot contain backticks
            if not (f_chars[0] == "`" and "`" in info):
                in_fence = True
                fence_char = f_chars[0]
                fence_len = len(f_chars)
                in_indented_code = False
                prev_was_blank = False
                cleaned_lines.append(line.rstrip(" \t"))
                continue

        # Check for indented code block (4 spaces or tab after blank line or continuing)
        is_indented_line = line.startswith("    ") or line.startswith("\t")
        if (prev_was_blank and is_indented_line) or (in_indented_code and is_indented_line):
            in_indented_code = True
            cleaned_lines.append(line)
            prev_was_blank = False
            continue
        elif not line.strip():
            in_indented_code = False
            prev_was_blank = True
            cleaned_lines.append("")
            continue
        else:
            in_indented_code = False
            prev_was_blank = False

        # Normal prose line formatting
        cleaned_lines.append(format_markdown_line(line))

    new_content = line_ending.join(cleaned_lines)
    # Ensure trailing newline matching detected line ending
    if new_content and not new_content.endswith(line_ending):
        new_content += line_ending

    return new_content, (new_content != content)


def apply_deterministic_formatting(workspace_dir: Path, target_file: str) -> None:
    """
    Format markdown file: strip unwanted trailing whitespace while strictly
    preserving Markdown hard breaks (two trailing spaces), line endings (CRLF vs LF),
    and file encoding (UTF-8 / UTF-8 BOM).
    """
    file_path = workspace_dir / target_file
    if not file_path.exists():
        raise TaskEngineError(f"Target file '{target_file}' does not exist")

    raw_bytes = file_path.read_bytes()
    encoding = "utf-8-sig" if raw_bytes.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        content = raw_bytes.decode(encoding)
    except UnicodeDecodeError:
        content = raw_bytes.decode("utf-8", errors="replace")
        encoding = "utf-8"

    new_content, changed = format_markdown_content(content)
    if changed:
        file_path.write_bytes(new_content.encode(encoding))


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
            timeout=30,
        )
        res = subprocess.run(
            ["git", "diff", "--unified=3"],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
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
                timeout=30,
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
    """Read selected relevant files, request AI implementation, validate paths, and record explanations."""
    # Find candidate files in workspace to select relevant context
    candidate_files = list(task.target_files)
    if hasattr(ai_adapter, "select_relevant_files"):
        candidate_files = ai_adapter.select_relevant_files(task, candidate_files)

    existing_files: dict[str, str] = {}
    for f in candidate_files:
        p = workspace_dir / f
        if p.exists() and p.is_file():
            # Bound context size per file to 25KB to avoid excessive tokens
            existing_files[f] = p.read_text(encoding="utf-8", errors="replace")[:25000]

    context = {
        "repo_name": task.repo,
        "existing_files": existing_files,
        "plan": task.plan.model_dump() if task.plan else None,
    }

    try:
        if hasattr(ai_adapter, "implement_task_with_plan"):
            new_files, explanations = ai_adapter.implement_task_with_plan(task, task.plan, context)
            if task.plan and explanations:
                task.plan.change_explanations.update(explanations)
            task.metadata["change_explanations"] = explanations
        else:
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
