"""
Tests for customfmt.rules.hoisting (CF014 / CF015).

TestCF014ModuleLevel
   TestValidDeclsBeforeClass
   TestValidDeclsBeforeFunction
   TestValidImportsThenDeclsThenClass
   TestValidEmptyModule
   TestValidOnlyImports
   TestValidOnlyDecls
   TestValidOnlyFunctions
   TestInvalidDeclAfterClass
   TestInvalidDeclAfterFunction
   TestInvalidAnnAssignAfterClass
   TestInvalidMultipleDeclsAfterBarrier
   TestInvalidDeclAfterSecondFunction
   TestMainGuardTransparent
   TestImportAfterClassTransparent
   TestBlankLinesAndCommentsTransparent

TestCF015ClassBody
   TestValidDeclsBeforeMethod
   TestValidDeclsBeforeNestedClass
   TestValidOnlyDecls
   TestValidOnlyMethods
   TestInvalidDeclAfterMethod
   TestInvalidDeclAfterNestedClass
   TestInvalidAnnAssignAfterMethod
   TestInvalidMultipleDeclsAfterBarrier
   TestBlankLinesBetweenDeclsAndMethod
   TestMultipleClassesEachCheckedIndependently

TestCLIIntegration
   TestCheckReportsCF014
   TestCheckReportsCF015
   TestFixDoesNotAutoFix
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.rules.hoisting import RULE_CF014, RULE_CF015, Check

P = Path("my_module.py")


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def Codes(viols, code: str) -> list:
   return [v for v in viols if v.code == code]


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def RunMain(*args: str) -> int:
   return Main(list(args))


# ---------------------------------------------------------------------------
# CF014 – module-level hoisting
# ---------------------------------------------------------------------------


class TestCF014ModuleLevel:
   def TestValidDeclsBeforeClass(self):
      src = L("""\
         MY_CONST = 42
         OTHER = "x"

         class MyClass:
            pass
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestValidDeclsBeforeFunction(self):
      src = L("""\
         TIMEOUT = 30
         NAME = "app"

         def MyFunc():
            pass
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestValidImportsThenDeclsThenClass(self):
      src = L("""\
         import os
         from pathlib import Path

         BASE_DIR = Path(".")
         MAX_RETRIES = 3

         class Config:
            pass
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestValidEmptyModule(self):
      assert Check([], P) == []

   def TestValidOnlyImports(self):
      src = L("""\
         import os
         import sys
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestValidOnlyDecls(self):
      src = L("""\
         X = 1
         Y = 2
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestValidOnlyFunctions(self):
      src = L("""\
         def Foo():
            pass

         def Bar():
            pass
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestInvalidDeclAfterClass(self):
      src = L("""\
         class MyClass:
            pass

         LATE_CONST = 99
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert len(viols) == 1
      assert "LATE_CONST" in viols[0].message

   def TestInvalidDeclAfterFunction(self):
      src = L("""\
         def MyFunc():
            pass

         LATE_VAR = "oops"
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert len(viols) == 1
      assert "LATE_VAR" in viols[0].message

   def TestInvalidAnnAssignAfterClass(self):
      src = L("""\
         class MyClass:
            pass

         Count: int = 0
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert len(viols) == 1
      assert "Count" in viols[0].message

   def TestInvalidMultipleDeclsAfterBarrier(self):
      src = L("""\
         def Foo():
            pass

         A = 1
         B = 2
         C: str = ""
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert len(viols) == 3

   def TestInvalidDeclAfterSecondFunction(self):
      """A declaration between two functions is a violation."""
      src = L("""\
         def Foo():
            pass

         MID_CONST = 1

         def Bar():
            pass
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert len(viols) == 1
      assert "MID_CONST" in viols[0].message

   def TestMainGuardTransparent(self):
      """if __name__ == '__main__': does not count as a declaration or barrier."""
      src = L("""\
         TIMEOUT = 30

         def Main():
            pass

         if __name__ == "__main__":
            Main()
      """)
      # TIMEOUT before Def -> valid; __main__ guard -> transparent
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestImportAfterClassTransparent(self):
      """Imports after a class are transparent (not flagged)."""
      src = L("""\
         class Foo:
            pass

         import os
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestBlankLinesAndCommentsTransparent(self):
      """Blank lines and comments between decls and class are fine."""
      src = L("""\
         X = 1

         # this is a comment

         Y = 2

         class Foo:
            pass
      """)
      assert Codes(Check(src, P), RULE_CF014) == []

   def TestViolationLineNumber(self):
      """The reported line number must be the declaration line."""
      src = L("""\
         class Foo:
            pass
         LATE = 1
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert viols[0].line == 3

   def TestBarrierLineInMessage(self):
      """The message must mention the first barrier line."""
      src = L("""\
         class Foo:
            pass
         LATE = 1
      """)
      viols = Codes(Check(src, P), RULE_CF014)
      assert "line 1" in viols[0].message


# ---------------------------------------------------------------------------
# CF015 – class-body hoisting
# ---------------------------------------------------------------------------


class TestCF015ClassBody:
   def TestValidDeclsBeforeMethod(self):
      src = L("""\
         class MyClass:
            TABLE = "records"
            MAX = 100

            def MyMethod(self):
               pass
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestValidDeclsBeforeNestedClass(self):
      src = L("""\
         class Outer:
            CONFIG = {}

            class Inner:
               pass
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestValidOnlyDecls(self):
      src = L("""\
         class MyClass:
            A = 1
            B = 2
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestValidOnlyMethods(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            def Bar(self):
               pass
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestInvalidDeclAfterMethod(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            LATE = "oops"
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 1
      assert "LATE" in viols[0].message

   def TestInvalidDeclAfterNestedClass(self):
      src = L("""\
         class Outer:
            class Inner:
               pass
            LATE_DECL = 1
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 1
      assert "LATE_DECL" in viols[0].message

   def TestInvalidAnnAssignAfterMethod(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            Count: int = 0
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 1
      assert "Count" in viols[0].message

   def TestInvalidMultipleDeclsAfterBarrier(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            A = 1
            B = 2
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 2

   def TestBlankLinesBetweenDeclsAndMethod(self):
      """Blank lines between decls and method are fine."""
      src = L("""\
         class MyClass:
            TABLE = "x"

            def Foo(self):
               pass
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestMultipleClassesEachCheckedIndependently(self):
      """Two classes are each checked; a valid one does not suppress a bad one."""
      src = L("""\
         class Good:
            X = 1

            def Foo(self):
               pass

         class Bad:
            def Foo(self):
               pass
            X = 1
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 1
      assert "X" in viols[0].message

   def TestViolationLineNumber(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            LATE = 1
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert viols[0].line == 4

   def TestBarrierLineInMessage(self):
      src = L("""\
         class MyClass:
            def Foo(self):
               pass
            LATE = 1
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert "line 2" in viols[0].message

   def TestAssignInsideFunctionNotFlagged(self):
      """Assignments inside a method body must NOT be checked."""
      src = L("""\
         class MyClass:
            def Foo(self):
               local_var = 1
               another = 2
      """)
      assert Codes(Check(src, P), RULE_CF015) == []

   def TestDunderMethodBeforeDecl(self):
      """__init__ is a barrier; a declaration after it is a violation."""
      src = L("""\
         class MyClass:
            def __init__(self):
               pass
            TABLE = "x"
      """)
      viols = Codes(Check(src, P), RULE_CF015)
      assert len(viols) == 1
      assert "TABLE" in viols[0].message


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
   def TestCheckReportsCF014(self, tmp_path):
      src = "def Foo():\n   pass\n\nLATE = 1\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestCheckReportsCF015(self, tmp_path):
      src = "class A:\n   def Foo(self):\n      pass\n   LATE = 1\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestFixDoesNotAutoFix(self, tmp_path):
      """try-auto-format must NOT move declarations (CF014/CF015 are check-only)."""
      src = "def Foo():\n   pass\n\nLATE = 1\n"
      f = Write(tmp_path / "my_module.py", src)
      RunMain("fix", str(f))
      # Content must be unchanged (or only whitespace/alignment changes applied)
      content = f.read_text(encoding="utf-8")
      assert "LATE = 1" in content
      # The function definition must still be before LATE
      assert content.index("def Foo") < content.index("LATE = 1")
