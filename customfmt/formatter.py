"""
Formatter: orchestrates all auto-fixable rules.

Auto-fix pipeline (order matters):
  0. Read raw bytes, decode as UTF-8 without BOM (error on BOM / bad bytes).
  1. line_endings.FixText   – normalise CRLF / CR  →  LF
  2. trailing_whitespace    – strip trailing spaces/tabs
  3. self_assignment_alignment – align self.X = value blocks
  4. class_body_alignment   – align class-body declaration blocks
  5. final_newline          – ensure exactly one trailing newline
  6. Write UTF-8, LF only via WriteUtf8Lf.

ProcessFile is the main entry point used by the CLI.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from customfmt.io import ReadUtf8Bytes, ReadUtf8Text, WriteUtf8Lf
from customfmt.rules import (
   class_body_alignment,
   final_newline,
   line_endings,
   self_assignment_alignment,
   trailing_whitespace,
)
from customfmt.types import Violation


def ComputeFixed(text: str) -> str:
   """
   Apply all auto-fix rules to *text* (already decoded, no BOM) and
   return the corrected text.
   """
   text = line_endings.FixText(text)
   lines = text.splitlines(keepends=True)
   lines = trailing_whitespace.Fix(lines)
   lines = self_assignment_alignment.Fix(lines)
   lines = class_body_alignment.Fix(lines)
   lines = final_newline.Fix(lines)
   return "".join(lines)


def CheckFixable(raw: bytes, text: str, path: Path) -> list[Violation]:
   """
   Return violations that *would* be fixed by ComputeFixed.
   Used by ``customfmt fix --check``.

   Parameters
   ----------
   raw  : original file bytes, used for CF011 line-ending detection so we
          inspect the bytes on disk rather than a re-encoded copy.
   text : decoded text (no BOM), used for all text-based rules.
   path : used only for Violation path fields.
   """
   violations: list[Violation] = []
   raw = text.encode("utf-8")
   violations.extend(line_endings.CheckBytes(raw, path))
   lines = text.splitlines(keepends=True)
   violations.extend(trailing_whitespace.Check(lines, path))
   violations.extend(self_assignment_alignment.Check(lines, path))
   violations.extend(class_body_alignment.Check(lines, path))
   violations.extend(final_newline.Check(lines, path))
   return violations


def UnifiedDiff(original: str, fixed: str, path: Path) -> str:
   """Return a unified diff string between original and fixed text."""
   return "".join(
      difflib.unified_diff(
         original.splitlines(keepends=True),
         fixed.splitlines(keepends=True),
         fromfile=f"a/{path}",
         tofile=f"b/{path}",
      )
   )


def ProcessFile(
   path: Path,
   *,
   check_only: bool = False,
   diff: bool = False,
) -> tuple[bool, str, list[Violation]]:
   """
   Read *path*, optionally fix it.

   Returns (changed, diff_text, violations).

   Raises
   ------
   ValueError          if the file has a UTF-8 BOM.
   UnicodeDecodeError  if the file is not valid UTF-8.
   OSError             on I/O failure.
   """
   original_raw = ReadUtf8Bytes(path)
   original_text = ReadUtf8Text(path)  # raises ValueError on BOM, UnicodeDecodeError on bad bytes
   fixed_text = ComputeFixed(original_text)
   changed = fixed_text != original_text

   diff_text = ""
   if diff and changed:
      diff_text = UnifiedDiff(original_text, fixed_text, path)

   if check_only:
      viols = CheckFixable(original_raw, original_text, path)
      return changed, diff_text, viols

   if changed and not diff:
      WriteUtf8Lf(path, fixed_text)

   return changed, diff_text, []
