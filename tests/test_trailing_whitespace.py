"""Tests for customfmt.rules.trailing_whitespace."""

from __future__ import annotations

from pathlib import Path

from customfmt.rules.trailing_whitespace import RULE_CODE, Check, Fix

P = Path("f.py")


def Lines(src: str) -> list[str]:
   return src.splitlines(keepends=True)


class TestCheck:
   def TestCleanNoViolations(self):
      assert Check(Lines("x = 1\n"), P) == []

   def TestTrailingSpacesReported(self):
      viols = Check(Lines("x = 1   \n"), P)
      assert len(viols) == 1
      assert viols[0].code == RULE_CODE
      assert viols[0].line == 1

   def TestTrailingTabReported(self):
      viols = Check(Lines("x = 1\t\n"), P)
      assert len(viols) == 1

   def TestMultipleLines(self):
      src = "a = 1  \nb = 2\nc = 3 \n"
      viols = Check(Lines(src), P)
      assert {v.line for v in viols} == {1, 3}

   def TestBlankLineNoViolation(self):
      assert Check(Lines("\n"), P) == []


class TestFix:
   def TestRemovesTrailingSpaces(self):
      result = Fix(Lines("x = 1   \n"))
      assert result == ["x = 1\n"]

   def TestRemovesTrailingTab(self):
      result = Fix(Lines("x = 1\t\n"))
      assert result == ["x = 1\n"]

   def TestPreservesNewline(self):
      result = Fix(Lines("x = 1  \n"))
      assert result[0].endswith("\n")

   def TestCleanLineUnchanged(self):
      result = Fix(Lines("x = 1\n"))
      assert result == ["x = 1\n"]

   def TestIdempotent(self):
      src = Lines("x = 1   \ny = 2  \n")
      assert Fix(Fix(src)) == Fix(src)
