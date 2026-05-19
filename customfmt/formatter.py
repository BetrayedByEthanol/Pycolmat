"""
Formatter: orchestrates all auto-fixable rules.

Auto-fix pipeline (order matters):
  1. trailing_whitespace  – strips trailing spaces/tabs
  2. self_assignment_alignment – aligns self.X = value blocks
  3. final_newline        – ensures exactly one trailing newline

``process_file`` is the main entry point used by the CLI.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from customfmt.rules import final_newline, self_assignment_alignment, trailing_whitespace
from customfmt.types import Violation


def compute_fixed(lines: list[str]) -> list[str]:
    """Apply all auto-fix rules and return the result."""
    lines = trailing_whitespace.fix(lines)
    lines = self_assignment_alignment.fix(lines)
    lines = final_newline.fix(lines)
    return lines


def check_fixable(lines: list[str], path: Path) -> list[Violation]:
    """
    Return violations that *would* be fixed by ``compute_fixed``.
    Used by ``customfmt fix --check``.
    """
    violations: list[Violation] = []
    violations.extend(trailing_whitespace.check(lines, path))
    violations.extend(self_assignment_alignment.check(lines, path))
    violations.extend(final_newline.check(lines, path))
    return violations


def unified_diff(original: list[str], fixed: list[str], path: Path) -> str:
    """Return a unified diff string between original and fixed lines."""
    return "".join(
        difflib.unified_diff(
            original,
            fixed,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def process_file(
    path: Path,
    *,
    check_only: bool = False,
    diff: bool = False,
) -> tuple[bool, str, list[Violation]]:
    """
    Read *path*, optionally fix it.

    Parameters
    ----------
    path        : file to process
    check_only  : if True, do not write changes (``fix --check`` mode)
    diff        : if True, compute unified diff instead of writing

    Returns
    -------
    (changed, diff_text, violations)
      changed    – True if file content differs after fixing
      diff_text  – unified diff (only when diff=True)
      violations – violations found (only populated when check_only=True)
    """
    original_text = path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    fixed = compute_fixed(list(lines))
    changed = fixed != lines

    diff_text = ""
    if diff and changed:
        diff_text = unified_diff(lines, fixed, path)

    if check_only:
        viols = check_fixable(lines, path)
        return changed, diff_text, viols

    if changed and not diff:
        path.write_text("".join(fixed), encoding="utf-8")

    return changed, diff_text, []
