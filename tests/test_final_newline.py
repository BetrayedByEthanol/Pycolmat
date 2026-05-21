"""Tests for customfmt.rules.final_newline."""

from __future__ import annotations

from pathlib import Path

from customfmt.rules.final_newline import RULE_CODE, Check, Fix

P = Path("f.py")


def Lines(src: str) -> list[str]:
   return src.splitlines(keepends=True)


class TestCheck:
   def TestPresentNewlineOk(self):
      assert Check(Lines("x = 1\n"), P) == []

   def TestMissingNewlineViolation(self):
      viols = Check(Lines("x = 1"), P)
      assert len(viols) == 1
      assert viols[0].code == RULE_CODE

   def TestEmptyFileOk(self):
      assert Check([], P) == []


class TestFix:
   def TestAddsMissingNewline(self):
      result = Fix(Lines("x = 1"))
      assert "".join(result).endswith("\n")

   def TestPresentNewlineUnchanged(self):
      src = Lines("x = 1\n")
      assert Fix(src) == src

   def TestStripsTrailingBlankLines(self):
      src = Lines("x = 1\n\n\n")
      result = Fix(src)
      assert "".join(result) == "x = 1\n"

   def TestEmptyFileUnchanged(self):
      assert Fix([]) == []

   def TestIdempotent(self):
      src = Lines("x = 1")
      assert Fix(Fix(src)) == Fix(src)


class TestFixMutationSafety:
   def TestDoesNotMutateCallerList(self):
      """Fix() must never modify the list passed in."""
      original = ["x = 1\n", "\n", "\n"]
      copy = list(original)
      Fix(original)
      assert original == copy
