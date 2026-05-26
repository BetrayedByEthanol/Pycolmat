"""
Checker: orchestrates all check-only rules (CF001–CF015).

CheckFile is the main entry point used by the CLI.
"""

from __future__ import annotations

from pathlib import Path

from customfmt.io import UTF8_BOM, ReadUtf8Bytes
from customfmt.rules import (
   class_body_alignment,
   hoisting,
   indentation,
   line_endings,
   naming,
   self_assignment_alignment,
)
from customfmt.types import Violation


def CheckFile(path: Path) -> list[Violation]:
   """
   Run all check-only rules against *path* and return violations.

   Rules run
   ---------
   CF011        line endings (line_endings.py) – checked on raw bytes
   CF012        encoding / BOM (line_endings.py) – checked on raw bytes
   CF001–CF008  naming conventions (naming.py, AST-based)
   CF009        self-assignment alignment (self_assignment_alignment.py)
   CF010        indentation width and style (indentation.py)
   CF013        class-body declaration alignment (class_body_alignment.py)
   CF014        top-level declaration hoisting (hoisting.py)
   CF015        class-body declaration hoisting (hoisting.py)

   If CF012 is reported (invalid UTF-8), AST-based rules are skipped
   because the source cannot be parsed.
   """
   raw = ReadUtf8Bytes(path)
   encoding_viols = line_endings.CheckBytes(raw, path)

   violations: list[Violation] = list(encoding_viols)

   # If the file has invalid UTF-8, we cannot decode or run AST rules.
   # A BOM-only CF012 violation is still decodable after stripping the BOM,
   # so we only bail out when the bytes themselves are not valid UTF-8.
   has_invalid_utf8 = any(
      v.code == "CF012" and "not valid UTF-8" in v.message for v in encoding_viols
   )
   if has_invalid_utf8:
      return sorted(violations)

   # Decode safely — remove exact BOM prefix if present (already reported above).
   if raw.startswith(UTF8_BOM):
      text = raw[len(UTF8_BOM) :].decode("utf-8")
   else:
      text = raw.decode("utf-8")

   # If CF011 was reported, normalise line endings before running text-based
   # rules so that CRLF does not cause spurious CF009 / CF010 violations.
   # We still report CF011 — we just don't want noisy duplicates.
   has_cf011 = any(v.code == "CF011" for v in encoding_viols)
   if has_cf011:
      from customfmt.rules.line_endings import FixText

      text = FixText(text)

   lines = text.splitlines(keepends=True)

   # Naming (CF001–CF008)
   violations.extend(naming.Check(lines, path))

   # CF009 alignment
   violations.extend(self_assignment_alignment.Check(lines, path))

   # CF013 class-body alignment
   violations.extend(class_body_alignment.Check(lines, path))

   # CF014 / CF015 declaration hoisting
   violations.extend(hoisting.Check(lines, path))

   # CF010 indentation
   violations.extend(indentation.Check(lines, path))

   return sorted(violations)
