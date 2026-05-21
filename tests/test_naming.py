"""Tests for customfmt.rules.naming (CF001–CF008)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.rules.naming import Check


def L(src: str) -> list[str]:
   return textwrap.dedent(src).splitlines(keepends=True)


def CodesAt(viols, code: str):
   return [v for v in viols if v.code == code]


def P(name: str) -> Path:
   return Path(name)


# ---------------------------------------------------------------------------
# CF001 – file name snake_case.py
# ---------------------------------------------------------------------------


class TestCF001:
   def TestValid(self):
      assert not CodesAt(Check(L("x = 1\n"), P("my_module.py")), "CF001")

   def TestInvalidCamel(self):
      viols = CodesAt(Check(L("x = 1\n"), P("MyModule.py")), "CF001")
      assert viols
      # Fix 4: CF001 must report line=1, col=1
      assert viols[0].line == 1
      assert viols[0].col == 1

   def TestInvalidDash(self):
      assert CodesAt(Check(L("x = 1\n"), P("my-module.py")), "CF001")

   def TestSingleWord(self):
      assert not CodesAt(Check(L("x = 1\n"), P("module.py")), "CF001")

   def TestWithDigits(self):
      assert not CodesAt(Check(L("x = 1\n"), P("module2.py")), "CF001")

   def TestLineColNotZero(self):
      """CF001 must not use line=0,col=0 (old behaviour)."""
      viols = CodesAt(Check(L("x = 1\n"), P("BadName.py")), "CF001")
      assert viols
      assert viols[0].line != 0
      assert viols[0].col != 0


# ---------------------------------------------------------------------------
# CF002 – class PascalCase
# ---------------------------------------------------------------------------


class TestCF002:
   def TestValid(self):
      src = L("class MyClass:\n   pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF002")

   def TestInvalidLower(self):
      src = L("class myClass:\n   pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF002")

   def TestInvalidUnderscore(self):
      src = L("class My_Class:\n   pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF002")

   def TestNestedClass(self):
      src = L("""\
         class Outer:
            class inner:
               pass
      """)
      viols = CodesAt(Check(src, P("f.py")), "CF002")
      assert any("inner" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF003 – function/method PascalCase  (dunders exempt)
# ---------------------------------------------------------------------------


class TestCF003:
   def TestValidFunction(self):
      src = L("def CalculateTotal():\n   pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestInvalidSnake(self):
      src = L("def calculate_total():\n   pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF003")

   def TestDunderInitExempt(self):
      """Fix 1: __init__ must NOT be flagged by CF003."""
      src = L("class A:\n   def __init__(self):\n      pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestDunderStrExempt(self):
      src = L("class A:\n   def __str__(self):\n      return ''\n")
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestDunderReprExempt(self):
      src = L("class A:\n   def __repr__(self):\n      return ''\n")
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestDunderEnterExitExempt(self):
      src = L("""\
         class A:
            def __enter__(self):
               return self
            def __exit__(self, exc_type, exc_val, exc_tb):
               pass
      """)
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestArbitraryDunderExempt(self):
      """Any __foo__ pattern is exempt."""
      src = L("class A:\n   def __custom_hook__(self):\n      pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF003")

   def TestNonDunderSnakeStillFlagged(self):
      """_private_method and normal snake_case are NOT exempt."""
      src = L("class A:\n   def bad_method(self):\n      pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF003")

   def TestMethodInClass(self):
      src = L("""\
         class A:
            def GoodMethod(self):
               pass
            def bad_method(self):
               pass
      """)
      viols = CodesAt(Check(src, P("f.py")), "CF003")
      assert any("bad_method" in v.message for v in viols)
      assert not any("GoodMethod" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF004 – parameter names snake_case
#         self/cls only exempt as first param of a class method
# ---------------------------------------------------------------------------


class TestCF004:
   def TestValid(self):
      src = L("def Foo(user_name, count):\n   pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF004")

   # -- self/cls as first param of a class method: exempt --
   def TestSelfFirstParamOfClassMethodExempt(self):
      """Fix 2: self is exempt only as first positional param of a class method."""
      src = L("class A:\n   def Foo(self):\n      pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF004")

   def TestClsFirstParamOfClassMethodExempt(self):
      src = L("class A:\n   def Foo(cls):\n      pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF004")

   # -- self/cls at module level: NOT exempt --
   def TestSelfInModuleFunctionFlagged(self):
      """Fix 2: self used in a module-level function must be flagged (CF004)."""
      src = L("def Foo(self):\n   pass\n")
      viols = CodesAt(Check(src, P("f.py")), "CF004")
      assert any("self" in v.message for v in viols)

   def TestClsInModuleFunctionFlagged(self):
      src = L("def Foo(cls):\n   pass\n")
      viols = CodesAt(Check(src, P("f.py")), "CF004")
      assert any("cls" in v.message for v in viols)

   # -- self/cls not in first position: NOT exempt --
   def TestSelfNotFirstParamFlagged(self):
      """self as second param of a class method is not exempt."""
      src = L("class A:\n   def Foo(other, self):\n      pass\n")
      viols = CodesAt(Check(src, P("f.py")), "CF004")
      # 'self' is second here → must be flagged
      assert any("self" in v.message for v in viols)

   def TestInvalidPascalParam(self):
      src = L("def Foo(UserName):\n   pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF004")

   def TestVarargKwargValid(self):
      src = L("def Foo(*args, **kwargs):\n   pass\n")
      assert not CodesAt(Check(src, P("f.py")), "CF004")

   def TestKwonlyInvalid(self):
      src = L("def Foo(*, BadName):\n   pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF004")

   def TestDunderMethodSelfExempt(self):
      """self in __init__ (a dunder) should be exempt."""
      src = L("class A:\n   def __init__(self, value):\n      pass\n")
      cf004 = CodesAt(Check(src, P("f.py")), "CF004")
      assert not any("self" in v.message for v in cf004)


# ---------------------------------------------------------------------------
# CF005 – local variable snake_case
# ---------------------------------------------------------------------------


class TestCF005:
   def TestValidLocal(self):
      src = L("def Foo():\n   total_count = 0\n")
      assert not CodesAt(Check(src, P("f.py")), "CF005")

   def TestInvalidCamel(self):
      src = L("def Foo():\n   totalCount = 0\n")
      assert CodesAt(Check(src, P("f.py")), "CF005")

   def TestForLoopTarget(self):
      src = L("def Foo():\n   for BadItem in []:\n      pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF005")

   def TestWithAsTarget(self):
      src = L("def Foo():\n   with open('f') as BadFile:\n      pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF005")

   def TestExceptAsTarget(self):
      src = L("def Foo():\n   try:\n      pass\n   except Exception as BadErr:\n      pass\n")
      assert CodesAt(Check(src, P("f.py")), "CF005")

   def TestUnderscoreSkip(self):
      src = L("def Foo():\n   _ = unused\n")
      assert not CodesAt(Check(src, P("f.py")), "CF005")

   def TestModuleLevelNotFlagged(self):
      src = L("BadName = 1\n")
      assert not CodesAt(Check(src, P("f.py")), "CF005")

   def TestTupleUnpack(self):
      src = L("def Foo():\n   good_a, BadB = 1, 2\n")
      viols = CodesAt(Check(src, P("f.py")), "CF005")
      assert any("BadB" in v.message for v in viols)
      assert not any("good_a" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF006 – instance attributes PascalCase
# ---------------------------------------------------------------------------


class TestCF006:
   def TestValid(self):
      src = L("class A:\n   def __init__(self):\n      self.UserName = 'x'\n")
      assert not CodesAt(Check(src, P("f.py")), "CF006")

   def TestInvalidSnake(self):
      src = L("class A:\n   def __init__(self):\n      self.user_name = 'x'\n")
      assert CodesAt(Check(src, P("f.py")), "CF006")

   def TestInvalidLower(self):
      src = L("class A:\n   def __init__(self):\n      self.name = 'x'\n")
      assert CodesAt(Check(src, P("f.py")), "CF006")

   def TestNonSelfAttrNotFlagged(self):
      src = L("def Foo(other):\n   other.name = 1\n")
      assert not CodesAt(Check(src, P("f.py")), "CF006")


# ---------------------------------------------------------------------------
# CF007 – global constants UPPER_CASE
# ---------------------------------------------------------------------------


class TestCF007:
   def TestValidUpper(self):
      src = L("DEFAULT_TIMEOUT = 30\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestInvalidLower(self):
      src = L("default_timeout = 30\n")
      assert CodesAt(Check(src, P("f.py")), "CF007")

   def TestFunctionCallNotConstant(self):
      src = L("UserName = get_user()\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestObjectConstructionNotConstant(self):
      src = L("Connection = Database()\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestListLiteralConstant(self):
      src = L('OPTIONS = ["a", "b"]\n')
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestListLiteralBadName(self):
      src = L('options = ["a", "b"]\n')
      assert CodesAt(Check(src, P("f.py")), "CF007")

   def TestNestedLiteral(self):
      src = L("MATRIX = ((1, 2), (3, 4))\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestNoneLiteral(self):
      src = L("DEFAULT_VALUE = None\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")

   def TestBoolLiteral(self):
      src = L("ENABLED = True\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")


# ---------------------------------------------------------------------------
# CF008 – class constants UPPER_CASE
# ---------------------------------------------------------------------------


class TestCF008:
   def TestValid(self):
      src = L("class A:\n   MAX_RETRIES = 3\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestInvalid(self):
      src = L("class A:\n   max_retries = 3\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestMethodBodyNotFlagged(self):
      src = L("class A:\n   def Foo(self):\n      local_var = 1\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestNonLiteralNotConstant(self):
      src = L("class A:\n   Connection = Database()\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")
