"""
Formatter: orchestrates all auto-fixable rules.

Auto-fix pipeline (order matters):
  0. Read raw bytes, decode as UTF-8 without BOM (error on BOM / bad bytes).
  1. line_endings.FixText       – normalise CRLF / CR → LF          (CF011)
  2. trailing_whitespace.Fix    – strip trailing spaces/tabs          (CF018)
  3. self_assignment_alignment  – align self.X = value blocks         (CF009)
  4. class_body_alignment       – align class-body declaration blocks  (CF013)
  5. final_newline.Fix          – ensure exactly one trailing newline  (CF019)
  6. Write UTF-8, LF only via WriteUtf8Lf.

Any rule whose code appears in *ignore_codes* is skipped in both fix and
check modes.

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
from customfmt.rules.line_endings import RULE_CF011
from customfmt.types import Violation

_EMPTY: frozenset[str] = frozenset()


def ComputeFixed(text: str, ignore_codes: frozenset[str] = _EMPTY) -> str:
   """
   Apply auto-fix rules to *text* (already decoded, no BOM) and return
   the corrected text.  Rules whose code is in *ignore_codes* are skipped.
   """
   if RULE_CF011 not in ignore_codes:
      text = line_endings.FixText(text)

   lines = text.splitlines(keepends=True)

   if trailing_whitespace.RULE_CODE not in ignore_codes:
      lines = trailing_whitespace.Fix(lines)

   if self_assignment_alignment.RULE_CODE not in ignore_codes:
      lines = self_assignment_alignment.Fix(lines)

   if class_body_alignment.RULE_CODE not in ignore_codes:
      lines = class_body_alignment.Fix(lines)

   if final_newline.RULE_CODE not in ignore_codes:
      lines = final_newline.Fix(lines)

   return "".join(lines)


def CheckFixable(
   raw: bytes,
   text: str,
   path: Path,
   ignore_codes: frozenset[str] = _EMPTY,
) -> list[Violation]:
   """
   Return violations that *would* be fixed by ComputeFixed.
   Used by ``customfmt fix --check``.
   Violations whose code is in *ignore_codes* are omitted.
   """
   violations: list[Violation] = []

   raw_viols = line_endings.CheckBytes(raw, path)
   violations.extend(v for v in raw_viols if v.code not in ignore_codes)

   lines = text.splitlines(keepends=True)

   ws_viols = trailing_whitespace.Check(lines, path)
   violations.extend(v for v in ws_viols if v.code not in ignore_codes)

   sa_viols = self_assignment_alignment.Check(lines, path)
   violations.extend(v for v in sa_viols if v.code not in ignore_codes)

   cb_viols = class_body_alignment.Check(lines, path)
   violations.extend(v for v in cb_viols if v.code not in ignore_codes)

   fn_viols = final_newline.Check(lines, path)
   violations.extend(v for v in fn_viols if v.code not in ignore_codes)

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
   ignore_codes: frozenset[str] = _EMPTY,
) -> tuple[bool, str, list[Violation]]:
   """
   Read *path*, optionally fix it.

   Returns (changed, diff_text, violations).

   Parameters
   ----------
   check_only    : if True, do not write changes.
   diff          : if True, compute unified diff instead of writing.
   ignore_codes  : rule codes to skip entirely.

   Raises
   ------
   ValueError          if the file has a UTF-8 BOM.
   UnicodeDecodeError  if the file is not valid UTF-8.
   OSError             on I/O failure.
   """
   original_raw  = ReadUtf8Bytes(path)
   original_text = ReadUtf8Text(path)
   fixed_text    = ComputeFixed(original_text, ignore_codes)
   changed       = fixed_text != original_text

   diff_text = ""
   if diff and changed:
      diff_text = UnifiedDiff(original_text, fixed_text, path)

   if check_only:
      viols = CheckFixable(original_raw, original_text, path, ignore_codes)
      return changed, diff_text, viols

   if changed and not diff:
      if RULE_CF011 in ignore_codes:
         # CF011 is ignored — preserve original line endings; write raw UTF-8.
         path.write_bytes(fixed_text.encode("utf-8"))
      else:
         WriteUtf8Lf(path, fixed_text)

   return changed, diff_text, []
