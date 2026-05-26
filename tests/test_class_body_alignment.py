"""
Tests for customfmt.rules.class_body_alignment (CF013).

TestCaseA  – assignment-only blocks
TestCaseB  – typed-only blocks
TestCaseC  – mixed (assign + typed) blocks
TestCaseD  – typed assignment (ann_val) blocks
TestSafety – multiline openers, single-line blocks, blank/comment splits,
             self.X exclusion, function-body exclusion
TestCheckVsFix – CF013 violations match Fix() behaviour
TestCLIIntegration – fix and check wired through the CLI
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.rules.class_body_alignment import RULE_CODE, Check, Fix

P = Path("F.py")


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def J(ls: list[str]) -> str:
   return "".join(ls)


def RunMain(*args: str) -> int:
   return Main(list(args))


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


# ---------------------------------------------------------------------------
# CASE A — assignment-only blocks
# ---------------------------------------------------------------------------


class TestCaseA:
   def TestAssignOnlyAligned(self):
      src = L("""\
         class Repo:
            tableName  = "ArtikelVertrieb"
            references = {}
            typeRef    = {}
            model      = ArtikelVertriebModel
            pk         = "ID"
      """)
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestAssignOnlyMisaligned(self):
      src = L("""\
         class Repo:
            tableName = "ArtikelVertrieb"
            references = {}
            typeRef = {}
            model = ArtikelVertriebModel
            pk = "ID"
      """)
      result = J(Fix(src))
      assert 'tableName  = "ArtikelVertrieb"' in result
      assert "references = {}" in result
      assert "typeRef    = {}" in result
      assert "model      = ArtikelVertriebModel" in result
      assert 'pk         = "ID"' in result

   def TestAssignOnlyViolationReported(self):
      src = L("""\
         class Repo:
            tableName = "ArtikelVertrieb"
            references = {}
      """)
      assert any(v.code == RULE_CODE for v in Check(src, P))

   def TestAssignOnlyIdempotent(self):
      src = L("""\
         class Repo:
            tableName = "x"
            refs = {}
      """)
      once = Fix(src)
      assert Fix(once) == once

   def TestSingleLineBlockNotViolation(self):
      src = L("""\
         class A:
            Name = "x"
      """)
      assert Check(src, P) == []


# ---------------------------------------------------------------------------
# CASE B — typed-only (AnnAssign without value)
# ---------------------------------------------------------------------------


class TestCaseB:
   def TestTypedOnlyAligned(self):
      src = L("""\
         class Example:
            ID            : int
            Name          : str
            VeryLongField : Decimal
      """)
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestTypedOnlyMisaligned(self):
      src = L("""\
         class Example:
            ID: int
            Name: str
            VeryLongField: Decimal
      """)
      result = J(Fix(src))
      assert "ID            : int" in result
      assert "Name          : str" in result
      assert "VeryLongField : Decimal" in result

   def TestTypedOnlyViolationReported(self):
      src = L("""\
         class Example:
            ID: int
            Name: str
      """)
      assert any(v.code == RULE_CODE for v in Check(src, P))

   def TestTypedOnlyIdempotent(self):
      src = L("""\
         class Example:
            ID: int
            Name: str
      """)
      once = Fix(src)
      assert Fix(once) == once


# ---------------------------------------------------------------------------
# CASE C — mixed (plain Assign + AnnAssign without value)
# ---------------------------------------------------------------------------


class TestCaseC:
   def TestMixedAligned(self):
      # Produce canonical form via Fix() and verify it is a fixed point.
      src = L("""\\
         class Example:
            ID: int
            Enabled = True
      """)
      fixed = Fix(src)
      assert Check(fixed, P) == []
      assert Fix(fixed) == fixed

   def TestMixedAssignReservesAnnotationColumn(self):
      """Plain Assign inside a typed block must indent = to align with ann_val lines."""
      src = L("""\
         class Example:
            ID: int
            Enabled = True
      """)
      result = J(Fix(src))
      # ID line should have ":" aligned
      assert "ID      : int" in result
      # Enabled line should have "=" at the same column as ann_val "="
      # that column is after "name_pad : " + annotation padding
      assert "Enabled" in result
      lines = [line for line in result.splitlines() if "Enabled" in line]
      assert len(lines) == 1
      enabled_line = lines[0]
      id_line = [line for line in result.splitlines() if ": int" in line][0]
      # The "=" on the Enabled line must be at the same column as
      # it would be in an ann_val line of the same block
      assert enabled_line.index("=") == id_line.index(":") + 2 + 3 + 0 + 1

   def TestMixedIdempotent(self):
      src = L("""\
         class Example:
            ID: int
            Enabled = True
      """)
      once = Fix(src)
      assert Fix(once) == once


# ---------------------------------------------------------------------------
# CASE D — typed with value (AnnAssign with value), and full mixed blocks
# ---------------------------------------------------------------------------


class TestCaseD:
   def TestAnnValAligned(self):
      # Canonical form: produce via Fix(), verify fixed point.
      src = L("""\\
         class Example:
            ID: int = 0
            Name: str = ""
            Count: int = 0
      """)
      fixed = Fix(src)
      assert Check(fixed, P) == []
      assert Fix(fixed) == fixed

   def TestAnnValMisaligned(self):
      src = L("""\
         class Example:
            ID: int = 0
            Name: str = ""
            Count: int = 0
      """)
      result = J(Fix(src))
      assert "ID    : int = 0" in result
      assert 'Name  : str = ""' in result
      assert "Count : int = 0" in result

   def TestFullMixedBlock(self):
      """The canonical example from the spec."""
      src = L("""\
         class Example:
            ID: int
            Name: str = ""
            Enabled = True
            VeryLongField: Decimal
            Count: int = 0
      """)
      result = J(Fix(src))
      assert "ID            : int" in result
      assert 'Name          : str     = ""' in result
      assert "VeryLongField : Decimal" in result
      assert "Count         : int     = 0" in result
      # Enabled must have "=" aligned with the ann_val "=" column
      enabled_line = [line for line in result.splitlines() if "Enabled" in line][0]
      ann_val_line = [line for line in result.splitlines() if "str" in line and "=" in line][0]
      assert enabled_line.index("=") == ann_val_line.index("=")

   def TestFullMixedIdempotent(self):
      src = L("""\
         class Example:
            ID: int
            Name: str = ""
            Enabled = True
            VeryLongField: Decimal
            Count: int = 0
      """)
      once = Fix(src)
      assert Fix(once) == once

   def TestAnnotationColumnAligned(self):
      """All annotation widths padded to max_ann_width."""
      src = L("""\
         class Example:
            Name: str = ""
            Count: int = 0
      """)
      result = J(Fix(src))
      # "str" and "int" are same width so no extra padding needed
      assert "Name  : str = " in result
      assert "Count : int = " in result


# ---------------------------------------------------------------------------
# Safety — blank lines, comments, multiline openers, exclusions
# ---------------------------------------------------------------------------


class TestSafety:
   def TestBlankLineSplitsBlock(self):
      src = L("""\
         class A:
            Name = "x"

            Count = 0
      """)
      # Two single-line blocks; neither triggers a violation
      assert Check(src, P) == []

   def TestCommentSplitsBlock(self):
      src = L("""\
         class A:
            Name = "x"
            # separator
            Count = 0
      """)
      assert Check(src, P) == []

   def TestMultilineAnnotationSkipped(self):
      """A line whose annotation ends with ( must break the block."""
      src = L("""\
         class A:
            Name = "x"
            Items: List(
            Count = 0
      """)
      # Items line is not parseable -> breaks the block; Name and Count
      # are each single-line blocks -> no violations
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestMultilineRhsSkipped(self):
      """A line whose RHS ends with { must break the block."""
      src = L("""\
         class A:
            Name = "x"
            Data = {
            Count = 0
      """)
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestSelfXNotTouched(self):
      """self.X assignments inside a method must not be affected."""
      src = L("""\
         class A:
            def __init__(self):
               self.Name     = ""
               self.LongName = ""
      """)
      # These are inside a function; the rule does not touch them.
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestFunctionBodyNotTouched(self):
      """Regular assignments inside a function must not be aligned."""
      src = L("""\
         class A:
            def Foo(self):
               Name = ""
               LongName = ""
      """)
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestModuleLevelNotTouched(self):
      """Module-level assignments must not be touched."""
      src = L("""\
         Name = ""
         LongName = ""
      """)
      assert Check(src, P) == []
      assert Fix(src) == src

   def TestNoSelfXPatternInClassBody(self):
      """A direct class-body self.X style line should not match."""
      src = L("""\
         class A:
            self.Name     = ""
            self.LongName = ""
      """)
      # "self.Name" contains a dot, so _RE_ASSIGN must not match it.
      assert Check(src, P) == []
      assert Fix(src) == src


# ---------------------------------------------------------------------------
# Check vs Fix consistency
# ---------------------------------------------------------------------------


class TestCheckVsFix:
   def TestViolationsMatchFixDiff(self):
      """Every line Check() flags is a line Fix() changes."""
      src = L("""\
         class Example:
            ID: int
            Name: str = ""
            Enabled = True
      """)
      viols = Check(src, P)
      fixed = Fix(src)
      violated_lines = {v.line for v in viols if v.code == RULE_CODE}
      changed_lines = {i + 1 for i, (orig, new) in enumerate(zip(src, fixed)) if orig != new}
      assert violated_lines == changed_lines

   def TestAfterFixNoViolations(self):
      src = L("""\
         class Example:
            ID: int
            Name: str = ""
            Enabled = True
      """)
      assert Check(Fix(src), P) == []


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
   def TestFixAlignsClassBody(self, tmp_path):
      src = "class Repo:\n   tableName = 'x'\n   references = {}\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("fix", str(f))
      assert rc == 0
      content = f.read_text(encoding="utf-8")
      assert "tableName  = 'x'" in content

   def TestCheckReportsCf013(self, tmp_path):
      src = "class Repo:\n   tableName = 'x'\n   references = {}\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestFixCheckExits1WhenMisaligned(self, tmp_path):
      src = "class Repo:\n   tableName = 'x'\n   references = {}\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("fix", "--check", str(f))
      assert rc == 1

   def TestFixCheckExits0WhenAligned(self, tmp_path):
      src = "class Repo:\n   tableName  = 'x'\n   references = {}\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("fix", "--check", str(f))
      assert rc == 0
