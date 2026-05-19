"""Tests for customfmt.rules.naming (CF001–CF008)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from customfmt.rules.naming import check


def L(src: str) -> list[str]:
    return textwrap.dedent(src).splitlines(keepends=True)


def codes_at(viols, code: str):
    return [v for v in viols if v.code == code]


# ---------------------------------------------------------------------------
# Helpers to build paths with specific names
# ---------------------------------------------------------------------------
def p(name: str) -> Path:
    return Path(name)


# ---------------------------------------------------------------------------
# CF001 – file name snake_case.py
# ---------------------------------------------------------------------------

class TestCF001:
    def test_valid(self):
        assert not codes_at(check(L("x = 1\n"), p("my_module.py")), "CF001")

    def test_invalid_camel(self):
        assert codes_at(check(L("x = 1\n"), p("MyModule.py")), "CF001")

    def test_invalid_dash(self):
        assert codes_at(check(L("x = 1\n"), p("my-module.py")), "CF001")

    def test_single_word(self):
        assert not codes_at(check(L("x = 1\n"), p("module.py")), "CF001")

    def test_with_digits(self):
        assert not codes_at(check(L("x = 1\n"), p("module2.py")), "CF001")


# ---------------------------------------------------------------------------
# CF002 – class PascalCase
# ---------------------------------------------------------------------------

class TestCF002:
    def test_valid(self):
        src = L("class MyClass:\n   pass\n")
        assert not codes_at(check(src, p("f.py")), "CF002")

    def test_invalid_lower(self):
        src = L("class myClass:\n   pass\n")
        assert codes_at(check(src, p("f.py")), "CF002")

    def test_invalid_underscore(self):
        src = L("class My_Class:\n   pass\n")
        assert codes_at(check(src, p("f.py")), "CF002")

    def test_nested_class(self):
        src = L("""\
            class Outer:
               class inner:
                  pass
        """)
        viols = codes_at(check(src, p("f.py")), "CF002")
        assert any("inner" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF003 – function/method PascalCase
# ---------------------------------------------------------------------------

class TestCF003:
    def test_valid_function(self):
        src = L("def CalculateTotal():\n   pass\n")
        assert not codes_at(check(src, p("f.py")), "CF003")

    def test_invalid_snake(self):
        src = L("def calculate_total():\n   pass\n")
        assert codes_at(check(src, p("f.py")), "CF003")

    def test_dunder_flagged(self):
        # __init__ is not PascalCase – the rule should flag it
        # (project convention trumps Python convention here)
        src = L("class A:\n   def __init__(self):\n      pass\n")
        assert codes_at(check(src, p("f.py")), "CF003")

    def test_method_in_class(self):
        src = L("""\
            class A:
               def GoodMethod(self):
                  pass
               def bad_method(self):
                  pass
        """)
        viols = codes_at(check(src, p("f.py")), "CF003")
        assert any("bad_method" in v.message for v in viols)
        assert not any("GoodMethod" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF004 – parameter names snake_case
# ---------------------------------------------------------------------------

class TestCF004:
    def test_valid(self):
        src = L("def Foo(user_name, count):\n   pass\n")
        assert not codes_at(check(src, p("f.py")), "CF004")

    def test_self_cls_exempt(self):
        src = L("class A:\n   def Foo(self, cls):\n      pass\n")
        assert not codes_at(check(src, p("f.py")), "CF004")

    def test_invalid_pascal_param(self):
        src = L("def Foo(UserName):\n   pass\n")
        assert codes_at(check(src, p("f.py")), "CF004")

    def test_vararg_kwarg(self):
        src = L("def Foo(*args, **kwargs):\n   pass\n")
        assert not codes_at(check(src, p("f.py")), "CF004")

    def test_kwonly(self):
        src = L("def Foo(*, BadName):\n   pass\n")
        assert codes_at(check(src, p("f.py")), "CF004")


# ---------------------------------------------------------------------------
# CF005 – local variable snake_case
# ---------------------------------------------------------------------------

class TestCF005:
    def test_valid_local(self):
        src = L("def Foo():\n   total_count = 0\n")
        assert not codes_at(check(src, p("f.py")), "CF005")

    def test_invalid_camel(self):
        src = L("def Foo():\n   totalCount = 0\n")
        assert codes_at(check(src, p("f.py")), "CF005")

    def test_for_loop_target(self):
        src = L("def Foo():\n   for BadItem in []:\n      pass\n")
        assert codes_at(check(src, p("f.py")), "CF005")

    def test_with_as_target(self):
        src = L("def Foo():\n   with open('f') as BadFile:\n      pass\n")
        assert codes_at(check(src, p("f.py")), "CF005")

    def test_except_as_target(self):
        src = L("def Foo():\n   try:\n      pass\n   except Exception as BadErr:\n      pass\n")
        assert codes_at(check(src, p("f.py")), "CF005")

    def test_underscore_skip(self):
        # _ and __x are skipped
        src = L("def Foo():\n   _ = unused\n")
        assert not codes_at(check(src, p("f.py")), "CF005")

    def test_module_level_not_flagged(self):
        # Module-level assignments are handled by CF007, not CF005
        src = L("BadName = 1\n")
        assert not codes_at(check(src, p("f.py")), "CF005")

    def test_tuple_unpack(self):
        src = L("def Foo():\n   good_a, BadB = 1, 2\n")
        viols = codes_at(check(src, p("f.py")), "CF005")
        assert any("BadB" in v.message for v in viols)
        assert not any("good_a" in v.message for v in viols)


# ---------------------------------------------------------------------------
# CF006 – instance attributes PascalCase
# ---------------------------------------------------------------------------

class TestCF006:
    def test_valid(self):
        src = L("class A:\n   def __init__(self):\n      self.UserName = 'x'\n")
        assert not codes_at(check(src, p("f.py")), "CF006")

    def test_invalid_snake(self):
        src = L("class A:\n   def __init__(self):\n      self.user_name = 'x'\n")
        assert codes_at(check(src, p("f.py")), "CF006")

    def test_invalid_lower(self):
        src = L("class A:\n   def __init__(self):\n      self.name = 'x'\n")
        assert codes_at(check(src, p("f.py")), "CF006")

    def test_non_self_attr_not_flagged(self):
        # other.attr is not a self.X assignment → not CF006
        src = L("def Foo(other):\n   other.name = 1\n")
        assert not codes_at(check(src, p("f.py")), "CF006")


# ---------------------------------------------------------------------------
# CF007 – global constants UPPER_CASE
# ---------------------------------------------------------------------------

class TestCF007:
    def test_valid_upper(self):
        src = L("DEFAULT_TIMEOUT = 30\n")
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_invalid_lower(self):
        src = L("default_timeout = 30\n")
        assert codes_at(check(src, p("f.py")), "CF007")

    def test_function_call_not_constant(self):
        # Non-literal RHS → not a constant → CF007 does not apply
        src = L("UserName = get_user()\n")
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_object_construction_not_constant(self):
        src = L("Connection = Database()\n")
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_list_literal_constant(self):
        src = L('OPTIONS = ["a", "b"]\n')
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_list_literal_bad_name(self):
        src = L('options = ["a", "b"]\n')
        assert codes_at(check(src, p("f.py")), "CF007")

    def test_nested_literal(self):
        src = L("MATRIX = ((1, 2), (3, 4))\n")
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_none_literal(self):
        src = L("DEFAULT_VALUE = None\n")
        assert not codes_at(check(src, p("f.py")), "CF007")

    def test_bool_literal(self):
        src = L("ENABLED = True\n")
        assert not codes_at(check(src, p("f.py")), "CF007")


# ---------------------------------------------------------------------------
# CF008 – class constants UPPER_CASE
# ---------------------------------------------------------------------------

class TestCF008:
    def test_valid(self):
        src = L("class A:\n   MAX_RETRIES = 3\n")
        assert not codes_at(check(src, p("f.py")), "CF008")

    def test_invalid(self):
        src = L("class A:\n   max_retries = 3\n")
        assert codes_at(check(src, p("f.py")), "CF008")

    def test_method_body_not_flagged(self):
        # Assignments inside methods are handled by CF005, not CF008
        src = L("class A:\n   def Foo(self):\n      local_var = 1\n")
        assert not codes_at(check(src, p("f.py")), "CF008")

    def test_non_literal_not_constant(self):
        src = L("class A:\n   Connection = Database()\n")
        assert not codes_at(check(src, p("f.py")), "CF008")
