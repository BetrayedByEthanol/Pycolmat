"""Tests for customfmt.rules.trailing_whitespace."""

from __future__ import annotations

from pathlib import Path

from customfmt.rules.trailing_whitespace import RULE_CODE, check, fix

P = Path("f.py")


def lines(src: str) -> list[str]:
    return src.splitlines(keepends=True)


class TestCheck:
    def test_clean_no_violations(self):
        assert check(lines("x = 1\n"), P) == []

    def test_trailing_spaces_reported(self):
        viols = check(lines("x = 1   \n"), P)
        assert len(viols) == 1
        assert viols[0].code == RULE_CODE
        assert viols[0].line == 1

    def test_trailing_tab_reported(self):
        viols = check(lines("x = 1\t\n"), P)
        assert len(viols) == 1

    def test_multiple_lines(self):
        src = "a = 1  \nb = 2\nc = 3 \n"
        viols = check(lines(src), P)
        assert {v.line for v in viols} == {1, 3}

    def test_blank_line_no_violation(self):
        assert check(lines("\n"), P) == []


class TestFix:
    def test_removes_trailing_spaces(self):
        result = fix(lines("x = 1   \n"))
        assert result == ["x = 1\n"]

    def test_removes_trailing_tab(self):
        result = fix(lines("x = 1\t\n"))
        assert result == ["x = 1\n"]

    def test_preserves_newline(self):
        result = fix(lines("x = 1  \n"))
        assert result[0].endswith("\n")

    def test_clean_line_unchanged(self):
        result = fix(lines("x = 1\n"))
        assert result == ["x = 1\n"]

    def test_idempotent(self):
        src = lines("x = 1   \ny = 2  \n")
        assert fix(fix(src)) == fix(src)
