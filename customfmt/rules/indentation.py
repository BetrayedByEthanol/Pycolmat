"""
Rule CF010: indentation must use spaces, and indentation width must be a
multiple of 3.

Detection strategy
------------------
- We scan each physical line for its leading whitespace.
- A line that starts with a TAB character is a violation (tabs used).
- A line whose leading-space count is not a multiple of 3 is a violation.
- Blank lines (only whitespace) are skipped.
- String literals that happen to start a line (e.g. triple-quoted blocks)
  are skipped via the AST to avoid false positives on multi-line strings.

We use a lightweight AST pre-scan to collect line ranges that belong to
string constants so we can skip those lines.
"""

from __future__ import annotations

import ast
from pathlib import Path

from customfmt.types import Violation

RULE_CODE = "CF010"


def _string_line_ranges(source: str) -> set[int]:
    """
    Return the set of 1-based line numbers that are *entirely inside* a
    string literal (i.e. continuation lines of multi-line strings).
    We leave the first line of each string alone so real indentation
    errors on that line are still caught.
    """
    inside: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return inside
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = node.lineno
            end = node.end_lineno  # type: ignore[attr-defined]
            if end is not None and end > start:
                for ln in range(start + 1, end + 1):
                    inside.add(ln)
    return inside


def check(lines: list[str], path: Path) -> list[Violation]:
    source = "".join(lines)
    skip = _string_line_ranges(source)
    violations: list[Violation] = []

    for lineno, line in enumerate(lines, 1):
        if lineno in skip:
            continue
        stripped = line.rstrip("\n")
        if not stripped.strip():
            continue  # blank / whitespace-only line

        # Count leading whitespace characters
        leading = len(stripped) - len(stripped.lstrip())
        if leading == 0:
            continue  # module-level line, no indentation to check

        leading_chars = stripped[:leading]

        # Tab check
        if "\t" in leading_chars:
            violations.append(
                Violation(path, lineno, 1, RULE_CODE, "indentation uses tabs; use spaces instead")
            )
            continue  # don't also report width for a tab-indented line

        # Multiple-of-3 check
        if leading % 3 != 0:
            violations.append(
                Violation(
                    path,
                    lineno,
                    1,
                    RULE_CODE,
                    f"indentation of {leading} spaces is not a multiple of 3",
                )
            )

    return violations
