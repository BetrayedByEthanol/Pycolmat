"""
Rule: trailing whitespace (auto-fix).

Removes spaces/tabs at the end of every line (before the newline).
"""

from __future__ import annotations

from pathlib import Path

from customfmt.types import Violation

RULE_CODE = "trailing-whitespace"  # internal; not a CF0xx check-only rule


def check(lines: list[str], path: Path) -> list[Violation]:
    violations = []
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip("\n")
        if stripped != stripped.rstrip():
            violations.append(
                Violation(path, i, len(stripped.rstrip()) + 1, RULE_CODE, "trailing whitespace")
            )
    return violations


def fix(lines: list[str]) -> list[str]:
    """Remove trailing whitespace from each line, preserving the newline."""
    return [line.rstrip("\n").rstrip() + "\n" for line in lines]
