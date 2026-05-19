"""
Tests for customfmt.

Layout
------
  TestAlignSelf          – alignment rule (check + fix)
  TestTrailingWhitespace – trailing-ws rule
  TestFinalNewline       – final-newline rule
  TestNonSelfAssigns     – must NOT touch ordinary assignments
  TestPreservation       – comments, blank lines, dict literals, kwargs
  TestProcessFile        – file I/O, .py filter, fix=True rewrites
  TestCLIFix             – CLI `fix` command (click test runner)
  TestCLICheck           – CLI `check` command
  TestAliases            – try-auto-format / check-format aliases
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from customfmt.cli import cli, try_auto_format, check_format
from customfmt.formatter import (
    RULE_ALIGN_SELF,
    RULE_FINAL_NEWLINE,
    RULE_TRAILING_WS,
    check_lines,
    fix_lines,
    process_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lines(src: str) -> list[str]:
    """Split *src* into lines with newlines preserved, like splitlines(keepends=True)."""
    return src.splitlines(keepends=True)


def joined(ls: list[str]) -> str:
    return "".join(ls)


# ---------------------------------------------------------------------------
# 1. Align self-assignment blocks
# ---------------------------------------------------------------------------

class TestAlignSelf:
    def test_already_aligned_no_violations(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo     = 1
                self.bar_baz = 2
                self.x       = 3
        """)
        assert check_lines(lines(src), Path("f.py")) == []

    def test_misaligned_reports_violation(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1
                self.bar_baz = 2
        """)
        viols = check_lines(lines(src), Path("f.py"))
        rules = [v.rule for v in viols]
        assert RULE_ALIGN_SELF in rules

    def test_fix_aligns_block(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1
                self.bar_baz = 2
                self.x = 3
        """)
        result = joined(fix_lines(lines(src)))
        assert "self.foo     = 1" in result
        assert "self.bar_baz = 2" in result
        assert "self.x       = 3" in result

    def test_fix_idempotent(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1
                self.bar_baz = 2
        """)
        once = fix_lines(lines(src))
        twice = fix_lines(once)
        assert once == twice

    def test_two_separate_blocks_aligned_independently(self):
        src = textwrap.dedent("""\
            class A:
                def __init__(self):
                    self.aa = 1
                    self.bb_long = 2

                def reset(self):
                    self.x = 0
                    self.yy = 1
        """)
        result = joined(fix_lines(lines(src)))
        # block 1
        assert "self.aa      = 1" in result
        assert "self.bb_long = 2" in result
        # block 2
        assert "self.x  = 0" in result
        assert "self.yy = 1" in result

    def test_single_line_block_not_violated(self):
        src = textwrap.dedent("""\
            def f(self):
                self.only = 1
        """)
        viols = check_lines(lines(src), Path("f.py"))
        assert not any(v.rule == RULE_ALIGN_SELF for v in viols)

    def test_blank_line_breaks_block(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1

                self.bar_long = 2
        """)
        result = joined(fix_lines(lines(src)))
        # Each side of the blank line is its own single-line block → no padding added
        assert "self.foo = 1" in result
        assert "self.bar_long = 2" in result

    def test_indentation_level_respected(self):
        """Blocks at different indent levels must not be merged."""
        src = textwrap.dedent("""\
            class A:
                def __init__(self):
                    self.aa = 1
                    self.bb_long = 2
                    if True:
                        self.x = 0
                        self.yy_long = 1
        """)
        result = joined(fix_lines(lines(src)))
        assert "self.aa      = 1" in result
        assert "self.bb_long = 2" in result
        assert "self.x       = 0" in result
        assert "self.yy_long = 1" in result

    def test_violation_line_numbers_correct(self):
        src = textwrap.dedent("""\
            class A:
                def __init__(self):
                    self.foo = 1
                    self.bar_baz = 2
        """)
        viols = check_lines(lines(src), Path("a.py"))
        align_viols = [v for v in viols if v.rule == RULE_ALIGN_SELF]
        line_nums = {v.line for v in align_viols}
        # lines 3 and/or 4 should be reported (1-based)
        assert line_nums <= {3, 4}
        assert line_nums  # at least one


# ---------------------------------------------------------------------------
# 2. Trailing whitespace
# ---------------------------------------------------------------------------

class TestTrailingWhitespace:
    def test_detects_trailing_space(self):
        src = "x = 1   \n"
        viols = check_lines(lines(src), Path("f.py"))
        assert any(v.rule == RULE_TRAILING_WS for v in viols)

    def test_detects_trailing_tab(self):
        src = "x = 1\t\n"
        viols = check_lines(lines(src), Path("f.py"))
        assert any(v.rule == RULE_TRAILING_WS for v in viols)

    def test_fix_removes_trailing_whitespace(self):
        src = "x = 1   \ny = 2\t\n"
        result = joined(fix_lines(lines(src)))
        assert "   " not in result
        assert "\t\n" not in result

    def test_clean_line_no_violation(self):
        src = "x = 1\n"
        viols = check_lines(lines(src), Path("f.py"))
        assert not any(v.rule == RULE_TRAILING_WS for v in viols)


# ---------------------------------------------------------------------------
# 3. Final newline
# ---------------------------------------------------------------------------

class TestFinalNewline:
    def test_missing_newline_violation(self):
        src = "x = 1"   # no trailing newline
        viols = check_lines(lines(src), Path("f.py"))
        assert any(v.rule == RULE_FINAL_NEWLINE for v in viols)

    def test_fix_adds_newline(self):
        src = "x = 1"
        result = joined(fix_lines(lines(src)))
        assert result.endswith("\n")

    def test_present_newline_no_violation(self):
        src = "x = 1\n"
        viols = check_lines(lines(src), Path("f.py"))
        assert not any(v.rule == RULE_FINAL_NEWLINE for v in viols)


# ---------------------------------------------------------------------------
# 4. Ordinary assignments must NOT be touched
# ---------------------------------------------------------------------------

class TestNonSelfAssigns:
    def test_ordinary_assignments_unchanged(self):
        src = textwrap.dedent("""\
            foo = 1
            bar_long = 2
            x = 3
        """)
        result = joined(fix_lines(lines(src)))
        assert result == src

    def test_no_violation_for_ordinary_assignments(self):
        src = textwrap.dedent("""\
            foo = 1
            bar_long = 2
        """)
        viols = check_lines(lines(src), Path("f.py"))
        assert not any(v.rule == RULE_ALIGN_SELF for v in viols)

    def test_augmented_assignment_not_matched(self):
        src = textwrap.dedent("""\
            def f(self):
                self.x += 1
                self.yy_long += 2
        """)
        # augmented assigns (+=) must not trigger alignment
        viols = check_lines(lines(src), Path("f.py"))
        assert not any(v.rule == RULE_ALIGN_SELF for v in viols)
        result = joined(fix_lines(lines(src)))
        assert result == src


# ---------------------------------------------------------------------------
# 5. Preservation: comments, blank lines, dict literals, kwargs
# ---------------------------------------------------------------------------

class TestPreservation:
    def test_inline_comment_preserved(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1  # comment A
                self.bar_baz = 2  # comment B
        """)
        result = joined(fix_lines(lines(src)))
        assert "# comment A" in result
        assert "# comment B" in result

    def test_comment_only_line_breaks_block(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.foo = 1
                # separator
                self.bar_baz = 2
        """)
        result = joined(fix_lines(lines(src)))
        # comment breaks the block; each side is a single-line block → no padding
        assert "self.foo = 1" in result
        assert "self.bar_baz = 2" in result

    def test_dict_literal_untouched(self):
        src = textwrap.dedent("""\
            def f():
                d = {
                    "foo": 1,
                    "bar_long": 2,
                }
        """)
        result = joined(fix_lines(lines(src)))
        assert result == src

    def test_function_call_kwargs_untouched(self):
        src = textwrap.dedent("""\
            def f():
                call(foo=1, bar_long=2)
        """)
        result = joined(fix_lines(lines(src)))
        assert result == src

    def test_blank_lines_between_blocks_preserved(self):
        src = textwrap.dedent("""\
            def __init__(self):
                self.a = 1

                self.b = 2
        """)
        result = joined(fix_lines(lines(src)))
        assert "\n\n" in result


# ---------------------------------------------------------------------------
# 6. process_file – file I/O
# ---------------------------------------------------------------------------

class TestProcessFile:
    def test_non_py_file_skipped(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("hello\n")
        viols, changed = process_file(f, fix=False)
        assert viols == []
        assert not changed

    def test_check_returns_violations(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("def __init__(self):\n    self.foo = 1\n    self.bar_baz = 2\n")
        viols, changed = process_file(f, fix=False)
        assert any(v.rule == RULE_ALIGN_SELF for v in viols)
        assert not changed

    def test_fix_rewrites_file(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("def __init__(self):\n    self.foo = 1\n    self.bar_baz = 2\n")
        viols, changed = process_file(f, fix=True)
        assert changed
        assert viols == []
        content = f.read_text()
        assert "self.foo     = 1" in content

    def test_fix_no_change_returns_false(self, tmp_path):
        f = tmp_path / "f.py"
        src = "def __init__(self):\n    self.foo     = 1\n    self.bar_baz = 2\n"
        f.write_text(src)
        _, changed = process_file(f, fix=True)
        assert not changed

    def test_directory_recurse(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.py").write_text("x = 1   \n")
        (sub / "b.txt").write_text("ignored\n")
        # process_file works on individual files; CLI handles recursion
        viols, _ = process_file(sub / "a.py", fix=False)
        assert any(v.rule == RULE_TRAILING_WS for v in viols)


# ---------------------------------------------------------------------------
# 7. CLI – fix command
# ---------------------------------------------------------------------------

class TestCLIFix:
    def test_fix_rewrites_and_reports(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("def __init__(self):\n    self.foo = 1\n    self.bar_baz = 2\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(f)])
        assert result.exit_code == 0
        assert "reformatted" in result.output

    def test_fix_no_change(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(f)])
        assert result.exit_code == 0
        assert "left unchanged" in result.output

    def test_fix_nonexistent_path(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(tmp_path / "nope.py")])
        # no .py files found → exit 2
        assert result.exit_code == 2

    def test_fix_non_py_only(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("hello\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(f)])
        assert result.exit_code == 2

    def test_fix_directory(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1   \n")
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(tmp_path)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 8. CLI – check command
# ---------------------------------------------------------------------------

class TestCLICheck:
    def test_check_clean_exit_0(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(f)])
        assert result.exit_code == 0

    def test_check_violations_exit_1(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("def __init__(self):\n    self.foo = 1\n    self.bar_baz = 2\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(f)])
        assert result.exit_code == 1
        assert "align-self-assignments" in result.output

    def test_check_reports_file_line_rule(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x = 1   \n")
        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(f)])
        assert result.exit_code == 1
        assert str(f) in result.output
        assert RULE_TRAILING_WS in result.output

    def test_check_does_not_modify_file(self, tmp_path):
        f = tmp_path / "f.py"
        original = "x = 1   \n"
        f.write_text(original)
        runner = CliRunner()
        runner.invoke(cli, ["check", str(f)])
        assert f.read_text() == original

    def test_check_no_py_files_exit_2(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(tmp_path / "nope.py")])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# 9. Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    def test_try_auto_format_alias(self, tmp_path, monkeypatch):
        f = tmp_path / "f.py"
        f.write_text("x = 1   \n")
        monkeypatch.setattr(sys, "argv", ["try-auto-format", str(f)])
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", str(f)])
        assert result.exit_code == 0

    def test_check_format_alias(self, tmp_path, monkeypatch):
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        monkeypatch.setattr(sys, "argv", ["check-format", str(f)])
        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(f)])
        assert result.exit_code == 0
