"""Tests for customfmt.rules.indentation (CF010)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.rules.indentation import Check

P = Path("f.py")


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def Codes(viols):
   return [v.code for v in viols]


class TestIndentation:
   def TestValid3Spaces(self):
      src = L("""\
            def Foo():
               x = 1
        """)
      assert Check(src, P) == []

   def TestValid6Spaces(self):
      src = L("""\
            def Foo():
               if True:
                  x = 1
        """)
      assert Check(src, P) == []

   def Test4SpacesViolation(self):
      src = "def Foo():\n    x = 1\n"
      viols = Check(src.splitlines(keepends=True), P)
      assert any(v.code == "CF010" for v in viols)

   def TestTabViolation(self):
      src = "def Foo():\n\tx = 1\n"
      viols = Check(src.splitlines(keepends=True), P)
      assert any("tabs" in v.message for v in viols)

   def TestBlankLinesSkipped(self):
      src = "def Foo():\n\n   x = 1\n"
      assert Check(src.splitlines(keepends=True), P) == []

   def TestModuleLevelNoViolation(self):
      src = "X = 1\n"
      assert Check(src.splitlines(keepends=True), P) == []

   def TestMultilineStringInteriorSkipped(self):
      # The continuation lines of the docstring are indented with 4 spaces
      # but should not be flagged because they are inside a string literal.
      src = 'def Foo():\n   """\n    this has 4-space indent inside the string\n   """\n   pass\n'
      viols = Check(src.splitlines(keepends=True), P)
      assert all(v.code == "CF010" for v in viols)
      # The interior lines (line 3) should NOT appear
      assert not any(v.line == 3 for v in viols)

   def TestViolationLineNumber(self):
      src = "def Foo():\n    x = 1\n"  # 4-space indent on line 2
      viols = Check(src.splitlines(keepends=True), P)
      assert any(v.line == 2 for v in viols)
