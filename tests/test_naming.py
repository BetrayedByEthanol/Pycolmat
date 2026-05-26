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
      src = L(
         "def Foo():\n   try:\n      pass\n   except Exception as BadErr:\n      pass\n"
      )
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
# CF007 – module-level declarations must be PascalCase or UPPER_CASE
# ---------------------------------------------------------------------------


class TestCF007:
   def TestPascalCaseModuleDeclPasses(self):
      """PascalCase module-level declaration is valid."""
      assert not CodesAt(Check(L("AppConfig = LoadConfig()\n"), P("f.py")), "CF007")

   def TestUpperCaseModuleDeclPasses(self):
      """UPPER_CASE module-level declaration is valid."""
      assert not CodesAt(Check(L("DEFAULT_TIMEOUT = 30\n"), P("f.py")), "CF007")

   def TestUpperCaseLiteralPasses(self):
      """UPPER_CASE with literal RHS is still valid."""
      assert not CodesAt(Check(L("MAX_RETRIES = 3\n"), P("f.py")), "CF007")

   def TestPascalCaseNonLiteralPasses(self):
      """PascalCase with non-literal RHS (function call) is valid."""
      assert not CodesAt(Check(L("UserName = GetUser()\n"), P("f.py")), "CF007")

   def TestSnakeCaseFails(self):
      """snake_case module-level declaration is a CF007 violation."""
      assert CodesAt(Check(L("default_timeout = 30\n"), P("f.py")), "CF007")

   def TestCamelCaseFails(self):
      """camelCase module-level declaration is a CF007 violation."""
      assert CodesAt(Check(L("appConfig = LoadConfig()\n"), P("f.py")), "CF007")

   def TestLowercaseFails(self):
      """Lowercase module-level declaration is a CF007 violation."""
      assert CodesAt(Check(L("model = MyModel()\n"), P("f.py")), "CF007")

   def TestLiteralRhsDoesNotForceUpperCase(self):
      """A literal RHS must NOT force UPPER_CASE; PascalCase is equally valid."""
      # Old behaviour: only literals triggered CF007 and only UPPER_CASE passed.
      # New behaviour: all decls must be PascalCase or UPPER_CASE regardless of RHS.
      assert not CodesAt(Check(L("TableName = \"x\"\n"), P("f.py")), "CF007")

   def TestNonLiteralRhsStillChecked(self):
      """Non-literal RHS is still checked — it is not exempt."""
      assert CodesAt(Check(L("table_name = GetTable()\n"), P("f.py")), "CF007")

   def TestDunderExempt(self):
      """Dunder names like __version__ are exempt from CF007."""
      assert not CodesAt(Check(L("__version__ = \"1.0\"\n"), P("f.py")), "CF007")

   def TestAnnAssignModuleLevelChecked(self):
      """AnnAssign at module level is also subject to CF007."""
      assert CodesAt(Check(L("my_count: int = 0\n"), P("f.py")), "CF007")

   def TestAnnAssignModuleLevelPascalPasses(self):
      assert not CodesAt(Check(L("MyCount: int = 0\n"), P("f.py")), "CF007")

   def TestInsideFunctionNotFlagged(self):
      """Assignments inside functions are local variables, not module decls."""
      src = L("def Foo():\n   snake_var = 1\n")
      assert not CodesAt(Check(src, P("f.py")), "CF007")


# ---------------------------------------------------------------------------
# CF008 – class-body declarations must be PascalCase or UPPER_CASE
# ---------------------------------------------------------------------------


class TestCF008:
   def TestPascalCaseClassDeclPasses(self):
      """PascalCase class-body declaration is valid."""
      src = L("class A:\n   TableName = \"ArtikelVertrieb\"\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestUpperCaseClassDeclPasses(self):
      """UPPER_CASE class-body declaration is valid."""
      src = L("class A:\n   TABLE_NAME = \"ArtikelVertrieb\"\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestSnakeCaseFails(self):
      src = L("class A:\n   table_name = \"x\"\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestCamelCaseFails(self):
      src = L("class A:\n   tableName = \"x\"\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestLowercaseFails(self):
      src = L("class A:\n   pk = \"ID\"\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestLiteralRhsDoesNotForceUpperCase(self):
      """Literal RHS must NOT force UPPER_CASE; PascalCase is equally valid."""
      src = L("class A:\n   TypeRef = {}\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestNonLiteralRhsStillChecked(self):
      """Non-literal RHS is not exempt from CF008."""
      src = L("class A:\n   type_ref = SomeClass()\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestMethodBodyNotFlagged(self):
      """Assignments inside methods are local variables, not class decls."""
      src = L("class A:\n   def Foo(self):\n      local_var = 1\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestDunderExempt(self):
      """Dunder names like __slots__ are exempt from CF008."""
      src = L("class A:\n   __slots__ = (\"Name\",)\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestAnnAssignClassBodyChecked(self):
      """AnnAssign in class body is subject to CF008."""
      src = L("class A:\n   my_count: int = 0\n")
      assert CodesAt(Check(src, P("f.py")), "CF008")

   def TestAnnAssignClassBodyPascalPasses(self):
      src = L("class A:\n   MyCount: int = 0\n")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestFullRepoClassExample(self):
      """The canonical Repo class from the spec — all PascalCase, all valid."""
      src = L("""class Repo:
   TableName  = "ArtikelVertrieb"
   References = {}
   TypeRef    = {}
   Model      = ArtikelVertriebModel
   Pk         = "ID"
""")
      assert not CodesAt(Check(src, P("f.py")), "CF008")

   def TestFullRepoBadClassExample(self):
      """The bad Repo class from the spec — all snake_case, all CF008."""
      src = L("""class Repo:
   tableName  = "ArtikelVertrieb"
   references = {}
   typeRef    = {}
   model      = ArtikelVertriebModel
   pk         = "ID"
""")
      viols = CodesAt(Check(src, P("f.py")), "CF008")
      assert len(viols) == 5
