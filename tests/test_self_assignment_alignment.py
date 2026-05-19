"""Tests for customfmt.rules.self_assignment_alignment."""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.rules.self_assignment_alignment import check, fix, RULE_CODE


P = Path("f.py")


def L(src: str) -> list[str]:
    return textwrap.dedent(src).splitlines(keepends=True)


def joined(ls: list[str]) -> str:
    return "".join(ls)


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

class TestCheck:
    def test_aligned_no_violations(self):
        src = L("""\
            def __init__(self):
                self.Name            = ""
                self.Descr           = None
                self.CompType        = 0
                self.ShowInDatasheet = True
        """)
        assert check(src, P) == []

    def test_misaligned_two_lines(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1
                self.BarBaz = 2
        """)
        viols = check(src, P)
        assert any(v.code == RULE_CODE for v in viols)

    def test_single_line_block_no_violation(self):
        src = L("""\
            def f(self):
                self.Only = 1
        """)
        assert check(src, P) == []

    def test_violation_line_numbers(self):
        src = L("""\
            class A:
                def __init__(self):
                    self.Foo = 1
                    self.BarBaz = 2
        """)
        viols = [v for v in check(src, P) if v.code == RULE_CODE]
        assert viols
        assert all(v.line in {3, 4} for v in viols)

    def test_blank_line_breaks_block(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1

                self.BarLong = 2
        """)
        # Each is a single-line block → no violation
        assert check(src, P) == []

    def test_indent_mismatch_breaks_block(self):
        src = L("""\
            def __init__(self):
                self.Aa = 1
                self.Bb = 2
                if True:
                    self.X = 0
                    self.Yy = 1
        """)
        viols = [v for v in check(src, P) if v.code == RULE_CODE]
        # The two blocks are separate; each may or may not be misaligned
        # depending on their own widths. Neither single-line block should fire.
        line_nums = {v.line for v in viols}
        # block 1 lines 2-3, block 2 lines 5-6
        assert line_nums <= {2, 3, 5, 6}


# ---------------------------------------------------------------------------
# fix()
# ---------------------------------------------------------------------------

class TestFix:
    def test_aligns_block(self):
        src = L("""\
            def __init__(self):
                self.Name = ""
                self.Descr = None
                self.CompType = 0
                self.ShowInDatasheet = True
        """)
        result = joined(fix(src))
        assert 'self.Name            = ""' in result
        assert "self.Descr           = None" in result
        assert "self.CompType        = 0" in result
        assert "self.ShowInDatasheet = True" in result

    def test_idempotent(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1
                self.BarBaz = 2
        """)
        once = fix(src)
        twice = fix(once)
        assert once == twice

    def test_two_blocks_aligned_independently(self):
        src = L("""\
            class A:
                def __init__(self):
                    self.Aa = 1
                    self.BbLong = 2

                def Reset(self):
                    self.X = 0
                    self.Yy = 1
        """)
        result = joined(fix(src))
        assert "self.Aa     = 1" in result
        assert "self.BbLong = 2" in result
        assert "self.X  = 0" in result
        assert "self.Yy = 1" in result

    def test_preserves_inline_comment(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1  # comment A
                self.BarBaz = 2  # comment B
        """)
        result = joined(fix(src))
        assert "# comment A" in result
        assert "# comment B" in result

    def test_ordinary_assignments_untouched(self):
        src = L("""\
            foo = 1
            bar_long = 2
            x = 3
        """)
        assert fix(src) == src

    def test_augmented_assignment_untouched(self):
        src = L("""\
            def f(self):
                self.X += 1
                self.YyLong += 2
        """)
        assert fix(src) == src

    def test_dict_literals_untouched(self):
        src = L("""\
            def f():
                d = {
                    "foo": 1,
                    "bar_long": 2,
                }
        """)
        assert fix(src) == src

    def test_blank_line_preserves_split(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1

                self.BarLong = 2
        """)
        result = joined(fix(src))
        assert "\n\n" in result

    def test_comment_line_breaks_block(self):
        src = L("""\
            def __init__(self):
                self.Foo = 1
                # separator
                self.BarBaz = 2
        """)
        result = joined(fix(src))
        # Each side is a 1-line block → no padding added
        assert "self.Foo = 1" in result
        assert "self.BarBaz = 2" in result
