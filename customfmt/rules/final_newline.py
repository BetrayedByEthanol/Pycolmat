"""
Rule: final newline (auto-fix).

Ensures every file ends with exactly one newline character.
"""

from __future__ import annotations

from pathlib import Path

from customfmt.types import Violation

RULE_CODE = "CF019"


def Check(lines: list[str], path: Path) -> list[Violation]:
   if not lines:
      return []
   last = lines[-1]
   if not last.endswith("\n"):
      return [
         Violation(path, len(lines), len(last) + 1, RULE_CODE, "missing newline at end of file")
      ]
   return []


def Fix(lines: list[str]) -> list[str]:
   """Ensure the file ends with exactly one newline."""
   if not lines:
      return lines
   # Copy first so we never mutate the caller's list.
   lines = list(lines)
   # Strip any blank trailing lines, then guarantee exactly one \n.
   while lines and lines[-1].strip() == "":
      lines.pop()
   if not lines:
      return lines
   lines[-1] = lines[-1].rstrip("\n") + "\n"
   return lines
