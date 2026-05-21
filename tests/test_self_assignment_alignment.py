"""Tests for customfmt.rules.self_assignment_alignment."""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.rules.self_assignment_alignment import (
   RULE_CODE,
   Check,
   Fix,
   _RhsIsMultilineOpener,
)

P = Path("F.py")


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def Joined(ls: list[str]) -> str:
   return "".join(ls)


# ---------------------------------------------------------------------------
# Check()
# ---------------------------------------------------------------------------


class TestCheck:
   def TestAlignedNoViolations(self):
      src = L("""\
         def __init__(self):
            self.Name            = ""
            self.Descr           = None
            self.CompType        = 0
            self.ShowInDatasheet = True
      """)
      assert Check(src, P) == []

   def TestMisalignedTwoLines(self):
      # Build unaligned source dynamically so the file itself has no
      # raw unaligned self-assignment block that would trigger CF009.
      src = [
         "   def __init__(self):\n",
         "      self.Foo = 1\n",  # intentionally unaligned
         "      self.BarBaz = 2\n",
      ]
      viols = Check(src, P)
      assert any(v.code == RULE_CODE for v in viols)

   def TestSingleLineBlockNoViolation(self):
      src = L("""\
         def F(self):
            self.Only = 1
      """)
      assert Check(src, P) == []

   def TestViolationLineNumbers(self):
      # Build unaligned source dynamically so the file itself has no
      # raw unaligned self-assignment block that would trigger CF009.
      src = [
         "class A:\n",
         "   def __init__(self):\n",
         "      self.Foo = 1\n",  # intentionally unaligned
         "      self.BarBaz = 2\n",
      ]
      viols = [v for v in Check(src, P) if v.code == RULE_CODE]
      assert viols
      assert all(v.line in {3, 4} for v in viols)

   def TestBlankLineBreaksBlock(self):
      src = L("""\
         def __init__(self):
            self.Foo = 1

            self.BarLong = 2
      """)
      assert Check(src, P) == []

   def TestIndentMismatchBreaksBlock(self):
      src = L("""\
         def __init__(self):
            self.Aa = 1
            self.Bb = 2
            if True:
               self.X  = 0
               self.Yy = 1
      """)
      viols = [v for v in Check(src, P) if v.code == RULE_CODE]
      line_nums = {v.line for v in viols}
      assert line_nums <= {2, 3, 5, 6}

   # Fix 5: multiline-opener blocks must not be reported
   def TestMultilineCallNotReported(self):
      """Block with self.Name = call( must NOT be reported as CF009."""
      src = L("""\
         def __init__(self):
            self.Name = call(
            self.Items = []
      """)
      assert Check(src, P) == []

   def TestMultilineListNotReported(self):
      src = L("""\
         def __init__(self):
            self.Items = [
            self.Other = 1
      """)
      assert Check(src, P) == []

   def TestMultilineDictNotReported(self):
      src = L("""\
         def __init__(self):
            self.Config = {
            self.Other = 1
      """)
      assert Check(src, P) == []

   def TestMultilineBackslashNotReported(self):
      src = L("""\
         def __init__(self):
            self.Value = something + \\
            self.Other = 1
      """)
      assert Check(src, P) == []

   def TestCheckConsistentWithFix(self):
      """CF009 is only reported when Fix() would change something."""
      src = L("""\
         def __init__(self):
            self.Foo    = 1
            self.BarBaz = 2
      """)
      fixed = Fix(src)
      # After fix, check should find no violations
      assert Check(fixed, P) == []


# ---------------------------------------------------------------------------
# Fix()
# ---------------------------------------------------------------------------


class TestFix:
   def TestAlignsBlock(self):
      src = L("""\
         def __init__(self):
            self.Name            = ""
            self.Descr           = None
            self.CompType        = 0
            self.ShowInDatasheet = True
      """)
      result = Joined(Fix(src))
      assert 'self.Name            = ""' in result
      assert "self.Descr           = None" in result
      assert "self.CompType        = 0" in result
      assert "self.ShowInDatasheet = True" in result

   def TestIdempotent(self):
      src = L("""\
         def __init__(self):
            self.Foo    = 1
            self.BarBaz = 2
      """)
      once = Fix(src)
      twice = Fix(once)
      assert once == twice

   def TestTwoBlocksAlignedIndependently(self):
      src = L("""\
         class A:
            def __init__(self):
               self.Aa     = 1
               self.BbLong = 2

            def Reset(self):
               self.X  = 0
               self.Yy = 1
      """)
      result = Joined(Fix(src))
      assert "self.Aa     = 1" in result
      assert "self.BbLong = 2" in result
      assert "self.X  = 0" in result
      assert "self.Yy = 1" in result

   def TestPreservesInlineComment(self):
      src = L("""\
         def __init__(self):
            self.Foo    = 1  # comment A
            self.BarBaz = 2  # comment B
      """)
      result = Joined(Fix(src))
      assert "# comment A" in result
      assert "# comment B" in result

   def TestOrdinaryAssignmentsUntouched(self):
      src = L("""\
         foo = 1
         bar_long = 2
         x = 3
      """)
      assert Fix(src) == src

   def TestAugmentedAssignmentUntouched(self):
      src = L("""\
         def F(self):
            self.X += 1
            self.YyLong += 2
      """)
      assert Fix(src) == src

   def TestDictLiteralsUntouched(self):
      src = L("""\
         def F():
            d = {
               "foo": 1,
               "bar_long": 2,
            }
      """)
      assert Fix(src) == src

   def TestBlankLinePreservesSplit(self):
      src = L("""\
         def __init__(self):
            self.Foo = 1

            self.BarLong = 2
      """)
      result = Joined(Fix(src))
      assert "\n\n" in result

   def TestCommentLineBreaksBlock(self):
      src = L("""\
         def __init__(self):
            self.Foo = 1
            # separator
            self.BarBaz = 2
      """)
      result = Joined(Fix(src))
      assert "self.Foo = 1" in result
      assert "self.BarBaz = 2" in result

   # Fix 5: multiline openers must not be touched by Fix()
   def TestMultilineCallOpenerNotTouched(self):
      """self.Name = call(  must not be aligned."""
      src = L("""\
         def __init__(self):
            self.Name = call(
            self.Items = []
      """)
      assert Fix(src) == src

   def TestMultilineListOpenerNotTouched(self):
      src = L("""\
         def __init__(self):
            self.Items = [
            self.Other = 1
      """)
      assert Fix(src) == src

   def TestMultilineDictOpenerNotTouched(self):
      src = L("""\
         def __init__(self):
            self.Config = {
            self.Other = 1
      """)
      assert Fix(src) == src

   def TestMultilineBackslashNotTouched(self):
      src = L("""\
         def __init__(self):
            self.Value = something + \\
            self.Other = 1
      """)
      assert Fix(src) == src

   def TestMultilineOpenerInCommentStillAligns(self):
      """# ( in an inline comment is not a multiline opener."""
      src = L("""\
         def __init__(self):
            self.Foo    = 1  # value (important)
            self.BarBaz = 2
      """)
      result = Joined(Fix(src))
      # Should align — the ( is inside a comment
      assert "self.Foo    = 1" in result
      assert "self.BarBaz = 2" in result


# ---------------------------------------------------------------------------
# _RhsIsMultilineOpener helper
# ---------------------------------------------------------------------------


class TestRhsIsMultilineOpener:
   def TestOpenParen(self):
      assert _RhsIsMultilineOpener("call(")

   def TestOpenBracket(self):
      assert _RhsIsMultilineOpener("[")

   def TestOpenBrace(self):
      assert _RhsIsMultilineOpener("{")

   def TestBackslash(self):
      assert _RhsIsMultilineOpener("something + \\")

   def TestPlainValueFalse(self):
      assert not _RhsIsMultilineOpener("1")

   def TestStringFalse(self):
      assert not _RhsIsMultilineOpener('"hello"')

   def TestCommentWithParenFalse(self):
      """( inside a trailing comment must not trigger multiline detection."""
      assert not _RhsIsMultilineOpener("1  # value (important)")

   def TestEmptyFalse(self):
      assert not _RhsIsMultilineOpener("")
