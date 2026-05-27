"""
Rules: line endings (CF011) and encoding (CF012).

CF011  file must use LF line endings only (no CRLF or bare CR).
CF012  file must be valid UTF-8 without BOM.

Auto-fix (fix mode)
-------------------
Line endings are normalised:
   \\r\\n  →  \\n
   \\r    →  \\n
Invalid UTF-8 and BOM are NOT auto-fixed; they cause an error in fix mode
(exit code 2) so the user must correct the encoding manually.

Check mode
----------
CF011 is reported once per file (at line 1, col 1) when any non-LF line
ending is detected in the raw bytes.
CF012 is reported once per file (at line 1, col 1) for:
   - a UTF-8 BOM prefix, or
   - any byte sequence that is not valid UTF-8.
"""

from __future__ import annotations

from pathlib import Path

from customfmt.io import UTF8_BOM
from customfmt.types import Violation

RULE_CF011 = "CF011"
RULE_CF012 = "CF012"


def CheckBytes(raw: bytes, path: Path) -> list[Violation]:
   """
   Inspect raw file bytes and return CF011 / CF012 violations.

   Parameters
   ----------
   raw  : the complete raw bytes of the file.
   path : used only for the Violation path field.
   """
   violations: list[Violation] = []

   # CF012 – BOM
   if raw.startswith(UTF8_BOM):
      violations.append(
         Violation(path, 1, 1, RULE_CF012, "file has a UTF-8 BOM; use plain UTF-8")
      )
      # Strip BOM before further UTF-8 validation so we don't double-report.
      raw = raw[len(UTF8_BOM):]

   # CF012 – invalid UTF-8
   try:
      raw.decode("utf-8")
   except UnicodeDecodeError as exc:
      violations.append(
         Violation(
            path, 1, 1, RULE_CF012,
            f"file is not valid UTF-8: {exc}",
         )
      )
      # Can't check line endings reliably on broken bytes; stop here.
      return violations

   # CF011 – non-LF line endings
   if b"\r" in raw:
      if b"\r\n" in raw:
         detail = "CRLF (\\r\\n) line endings detected"
      else:
         detail = "bare CR (\\r) line endings detected"
      violations.append(
         Violation(path, 1, 1, RULE_CF011, f"{detail}; use LF only")
      )

   return violations


def FixText(text: str) -> str:
   """
   Normalise line endings in *text* to LF only.

   \\r\\n  →  \\n
   \\r    →  \\n
   """
   return text.replace("\r\n", "\n").replace("\r", "\n")
