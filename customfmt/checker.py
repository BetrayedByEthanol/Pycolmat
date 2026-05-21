"""
Checker: orchestrates all check-only rules (CF001–CF010).

``check_file`` is the main entry point used by the CLI.
"""

from __future__ import annotations

from pathlib import Path

from customfmt.rules import indentation, naming, self_assignment_alignment
from customfmt.types import Violation


def CheckFile(path: Path) -> list[Violation]:
   """
   Run all check-only rules against *path* and return violations.

   Rules run
   ---------
   CF001–CF008  naming conventions (naming.py, AST-based)
   CF009        self-assignment alignment (self_assignment_alignment.py)
   CF010        indentation width and style (indentation.py)
   """
   source = path.read_text(encoding="utf-8")
   lines = source.splitlines(keepends=True)

   violations: list[Violation] = []

   # Naming (CF001–CF008)
   violations.extend(naming.Check(lines, path))

   # CF009 alignment
   violations.extend(self_assignment_alignment.Check(lines, path))

   # CF010 indentation
   violations.extend(indentation.Check(lines, path))

   return sorted(violations)
