"""
Rule: trailing whitespace (auto-fix).

Removes spaces/tabs at the end of every line (before the newline).
"""

from __future__ import annotations

from pathlib import Path

from customfmt.types import Violation

RULE_CODE = "CF018"


def Check(lines: list[str], path: Path) -> list[Violation]:
   violations = []
   for i, line in enumerate(lines, 1):
      stripped = line.rstrip("\n")
      if stripped != stripped.rstrip():
         violations.append(
            Violation(path, i, len(stripped.rstrip()) + 1, RULE_CODE, "trailing whitespace")
         )
   return violations


def Fix(lines: list[str]) -> list[str]:
   """Remove trailing spaces/tabs from each line, preserving the newline.

   Only spaces and tabs are stripped; \\r is intentionally left intact so
   that CRLF lines are not corrupted when CF011 (line endings) is ignored.
   """
   result = []
   for line in lines:
      # Strip the line terminator(s) at the end, then strip only spaces/tabs.
      if line.endswith("\r\n"):
         result.append(line[:-2].rstrip(" \t") + "\r\n")
      elif line.endswith("\n"):
         result.append(line[:-1].rstrip(" \t") + "\n")
      else:
         result.append(line.rstrip(" \t"))
   return result
