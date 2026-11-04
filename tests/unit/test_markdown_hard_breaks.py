"""Regression tests for Markdown hard-break preservation, whitespace formatting, CRLF handling, and rendering."""

from pathlib import Path
from dailygreen.task_engine import apply_deterministic_formatting, format_markdown_content, format_markdown_line


def test_format_markdown_line_preserves_two_trailing_spaces():
    """Verify that a content line ending in exactly two spaces is preserved as a Markdown hard break."""
    # Two spaces on content line -> preserved
    assert format_markdown_line("Hello world  ") == "Hello world  "
    assert format_markdown_line("**Loyiha nomi:** TOLKIEN OLAMI  ") == "**Loyiha nomi:** TOLKIEN OLAMI  "

    # Tab before two spaces -> tab stripped, exactly two spaces preserved
    assert format_markdown_line("Hello world\t  ") == "Hello world  "


def test_format_markdown_line_strips_ordinary_trailing_whitespace():
    """Verify single space, 3+ spaces, and trailing tabs are stripped."""
    assert format_markdown_line("Hello world ") == "Hello world"
    assert format_markdown_line("Hello world   ") == "Hello world"
    assert format_markdown_line("Hello world\t") == "Hello world"
    assert format_markdown_line("Hello world  \t") == "Hello world"

    # Whitespace-only lines -> stripped to empty
    assert format_markdown_line("   ") == ""
    assert format_markdown_line("  ") == ""
    assert format_markdown_line("\t\t") == ""
    assert format_markdown_line("") == ""


def test_format_markdown_content_multiple_paragraphs():
    """Verify multi-paragraph documents maintain hard breaks while cleaning whitespace-only lines."""
    input_text = (
        "Paragraph 1, line 1  \n"
        "Paragraph 1, line 2   \n"
        "\n"
        "   \n"
        "Paragraph 2, line 1  \n"
        "Paragraph 2, line 2\n"
    )
    expected = (
        "Paragraph 1, line 1  \n"
        "Paragraph 1, line 2\n"
        "\n"
        "\n"
        "Paragraph 2, line 1  \n"
        "Paragraph 2, line 2\n"
    )
    formatted, changed = format_markdown_content(input_text)
    assert changed is True
    assert formatted == expected


def test_format_markdown_content_crlf_preservation():
    """Verify CRLF line endings are preserved throughout the document."""
    input_crlf = "Line 1  \r\nLine 2   \r\nLine 3\r\n"
    expected_crlf = "Line 1  \r\nLine 2\r\nLine 3\r\n"

    formatted, changed = format_markdown_content(input_crlf)
    assert changed is True
    assert formatted == expected_crlf
    assert "\r\n" in formatted
    assert formatted.count("\r\n") == 3
    assert "\n" not in formatted.replace("\r\n", "")


def test_format_markdown_content_no_trailing_whitespace():
    """Verify clean files with no unwanted whitespace report changed=False."""
    clean_text = "# Header\n\nThis is paragraph one.\n\nThis is paragraph two with hard break  \nnext line.\n"
    formatted, changed = format_markdown_content(clean_text)
    assert changed is False
    assert formatted == clean_text


def test_apply_deterministic_formatting_file_io(tmp_path: Path):
    """Verify apply_deterministic_formatting modifies file on disk and preserves encoding."""
    doc = tmp_path / "test.md"
    doc.write_bytes(b"# Title\nLine with hard break  \nLine with excess space   \n")

    apply_deterministic_formatting(tmp_path, "test.md")

    result = doc.read_bytes().decode("utf-8")
    assert result == "# Title\nLine with hard break  \nLine with excess space\n"


def test_rendered_markdown_behavior():
    """
    Simulate standard CommonMark paragraph rendering to prove that two trailing spaces
    produce a hard line break (<br>), whereas stripped trailing spaces would collapse into a single line.
    """
    def render_markdown_paragraph(lines: list[str]) -> str:
        """Simple CommonMark-compliant paragraph renderer simulating HTML output."""
        rendered = []
        for i, line in enumerate(lines):
            if i > 0:
                prev = lines[i - 1]
                # CommonMark: two trailing spaces at end of line indicates hard line break
                if prev.endswith("  "):
                    rendered.append("<br />\n")
                else:
                    rendered.append(" ")
            rendered.append(line.rstrip(" "))
        return "".join(rendered)

    raw_doc = [
        "**Loyiha nomi:** TOLKIEN OLAMI  ",
        "**Loyiha shiori:** Ensiklopediya  ",
        "**Holati:** Faza 7",
    ]

    # Pre-formatting simulation
    html_before = render_markdown_paragraph(raw_doc)
    assert "<br />\n" in html_before
    assert html_before.count("<br />\n") == 2

    # Run through DailyGreen format_markdown_content
    formatted_text, _ = format_markdown_content("\n".join(raw_doc) + "\n")
    formatted_lines = formatted_text.splitlines()

    # Post-formatting simulation
    html_after = render_markdown_paragraph(formatted_lines)
    assert html_after == html_before, "Rendered Markdown HTML output diverged after formatting!"
    assert html_after.count("<br />\n") == 2


def test_fenced_code_block_triple_backticks():
    """Verify that triple-backtick fenced code blocks preserve trailing whitespace and tabs exactly."""
    doc = (
        "# Prose Header   \n"
        "\n"
        "```python\n"
        "def example():   \n"
        "\tline_with_tab = 1\t  \n"
        "    trailing_spaces_here    \n"
        "```\n"
        "\n"
        "Prose line with hard break  \n"
        "Next prose line.\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is True
    # The prose header has excess trailing spaces stripped
    assert "# Prose Header\n" in formatted
    # Inside the code fence, trailing spaces and tabs are untouched
    assert "def example():   \n" in formatted
    assert "\tline_with_tab = 1\t  \n" in formatted
    assert "    trailing_spaces_here    \n" in formatted
    # Outside code block, hard break is preserved
    assert "Prose line with hard break  \n" in formatted


def test_fenced_code_block_triple_tildes():
    """Verify that triple-tilde fenced code blocks preserve all internal whitespace."""
    doc = (
        "~~~javascript\n"
        "const a = 'hello';   \n"
        "\tconst b = 2;\t\n"
        "~~~\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is False
    assert formatted == doc


def test_indented_code_block_preservation():
    """Verify that 4-space indented code blocks retain trailing spaces and tabs."""
    doc = (
        "Some intro paragraph.\n"
        "\n"
        "    def indented_code():   \n"
        "        tab_line = True\t\n"
        "\n"
        "Ending prose line.\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is False
    assert "    def indented_code():   \n" in formatted
    assert "        tab_line = True\t\n" in formatted


def test_code_block_crlf_and_lf():
    """Verify code blocks with CRLF and LF maintain internal whitespace and correct line endings."""
    doc_crlf = (
        "# Title   \r\n"
        "```sh\r\n"
        "echo 'hello'   \r\n"
        "\techo 'tab'\t\r\n"
        "```\r\n"
        "Prose line  \r\n"
    )
    formatted_crlf, changed = format_markdown_content(doc_crlf)
    assert changed is True
    assert "\r\n" in formatted_crlf
    assert "# Title\r\n" in formatted_crlf
    assert "echo 'hello'   \r\n" in formatted_crlf
    assert "\techo 'tab'\t\r\n" in formatted_crlf
    assert "Prose line  \r\n" in formatted_crlf


def test_multiple_code_blocks_in_one_document():
    """Verify multiple code blocks in one document with mixed fences and prose in between."""
    doc = (
        "# Main Documentation\n"
        "\n"
        "```python\n"
        "x = 10   \n"
        "```\n"
        "\n"
        "Prose section with hard break  \n"
        "Second line with excess space   \n"
        "\n"
        "~~~yaml\n"
        "key: value   \n"
        "\ttabbed: 42\t\n"
        "~~~\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is True
    assert "x = 10   \n" in formatted
    assert "Prose section with hard break  \n" in formatted
    assert "Second line with excess space\n" in formatted
    assert "key: value   \n" in formatted
    assert "\ttabbed: 42\t\n" in formatted


def test_unclosed_fence_preserved_to_eof():
    """Verify an unclosed fence preserves all lines to EOF without alterations."""
    doc = (
        "# Unclosed block header\n"
        "\n"
        "```python\n"
        "line 1 with spaces   \n"
        "line 2 with tab\t\n"
        "line 3\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is False
    assert formatted == doc


# Task 1: List Items vs Indented Code Block Tests


def test_list_item_with_blank_line_and_indented_continuation_paragraph():
    """
    CommonMark: Indented paragraph following a list item after a blank line is list prose, NOT code.
    Trailing excess whitespace must be cleaned, while list structure is preserved.
    """
    doc = (
        "* First list item\n"
        "\n"
        "    Continuation paragraph of first list item with excess whitespace   \n"
    )
    expected = (
        "* First list item\n"
        "\n"
        "    Continuation paragraph of first list item with excess whitespace\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is True
    assert formatted == expected


def test_nested_list_with_four_space_indents():
    """
    CommonMark: Nested lists indented by 4 spaces are list items, NOT code.
    Excess whitespace should be stripped and hard breaks preserved.
    """
    doc = (
        "* Top level item\n"
        "    * Nested item with excess whitespace   \n"
        "    * Nested item with hard break  \n"
        "      Continuation of nested item.\n"
    )
    expected = (
        "* Top level item\n"
        "    * Nested item with excess whitespace\n"
        "    * Nested item with hard break  \n"
        "      Continuation of nested item.\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is True
    assert formatted == expected


def test_list_item_containing_fenced_block():
    """
    CommonMark: A list item containing an indented fenced code block must preserve
    the code block's internal whitespace verbatim, while formatting list prose.
    """
    doc = (
        "* List item with code:\n"
        "\n"
        "    ```python\n"
        "    def list_code():   \n"
        "        val = 42\t\n"
        "    ```\n"
        "\n"
        "    Prose continuation with excess space   \n"
    )
    expected = (
        "* List item with code:\n"
        "\n"
        "    ```python\n"
        "    def list_code():   \n"
        "        val = 42\t\n"
        "    ```\n"
        "\n"
        "    Prose continuation with excess space\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is True
    assert formatted == expected
    assert "    def list_code():   \n" in formatted
    assert "        val = 42\t\n" in formatted


def test_real_indented_code_block_after_normal_paragraph():
    """
    CommonMark: 4-space indented block after a normal top-level paragraph (NOT in a list) is code.
    Its trailing spaces and tabs must remain verbatim.
    """
    doc = (
        "Normal top level prose paragraph.\n"
        "\n"
        "    def real_indented_code():   \n"
        "        return True\t\n"
        "\n"
        "Following paragraph.\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is False
    assert formatted == doc
    assert "    def real_indented_code():   \n" in formatted
    assert "        return True\t\n" in formatted


def test_hard_break_inside_list_item():
    """
    CommonMark: Two trailing spaces on a line inside a list item represent a hard break.
    Must be preserved.
    """
    doc = (
        "* Item first line with hard break  \n"
        "  Item second line without break.\n"
    )
    formatted, changed = format_markdown_content(doc)
    assert changed is False
    assert formatted == doc
    assert "* Item first line with hard break  \n" in formatted


