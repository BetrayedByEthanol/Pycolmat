"""Tests for customfmt.rules.indentation (CF010)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.rules.indentation import check

P = Path("f.py")


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def codes(viols):
   return [v.code for v in viols]


class TestIndentation:
   def test_valid_3_spaces(self):
      src = L("""\
            def Foo():
               x = 1
        """)
      assert check(src, P) == []

   def test_valid_6_spaces(self):
      src = L("""\
            def Foo():
               if True:
                  x = 1
        """)
      assert check(src, P) == []

   def test_4_spaces_violation(self):
      src = "def Foo():\n    x = 1\n"
      viols = check(src.splitlines(keepends=True), P)
      assert any(v.code == "CF010" for v in viols)

   def test_tab_violation(self):
      src = "def Foo():\n\tx = 1\n"
      viols = check(src.splitlines(keepends=True), P)
      assert any("tabs" in v.message for v in viols)

   def test_blank_lines_skipped(self):
      src = "def Foo():\n\n   x = 1\n"
      assert check(src.splitlines(keepends=True), P) == []

   def test_module_level_no_violation(self):
      src = "X = 1\n"
      assert check(src.splitlines(keepends=True), P) == []

   def test_multiline_string_interior_skipped(self):
      # The continuation lines of the docstring are indented with 4 spaces
      # but should not be flagged because they are inside a string literal.
      src = 'def Foo():\n   """\n    this has 4-space indent inside the string\n   """\n   pass\n'
      viols = check(src.splitlines(keepends=True), P)
      assert all(v.code == "CF010" for v in viols)
      # The interior lines (line 3) should NOT appear
      assert not any(v.line == 3 for v in viols)

   def test_violation_line_number(self):
      src = "def Foo():\n    x = 1\n"  # 4-space indent on line 2
      viols = check(src.splitlines(keepends=True), P)
      assert any(v.line == 2 for v in viols)
