"""Tests for customfmt.rules.final_newline."""

from __future__ import annotations

from pathlib import Path

from customfmt.rules.trailing_whitespace import RULE_CODE, check, fix

P = Path("f.py")


def lines(src: str) -> list[str]:
    return src.splitlines(keepends=True)


class TestCheck:
    def test_present_newline_ok(self):
        assert check(lines("x = 1\n"), P) == []

    def test_missing_newline_violation(self):
        viols = check(lines("x = 1"), P)
        assert len(viols) == 1
        assert viols[0].code == RULE_CODE

    def test_empty_file_ok(self):
        assert check([], P) == []


class TestFix:
    def test_adds_missing_newline(self):
        result = fix(lines("x = 1"))
        assert "".join(result).endswith("\n")

    def test_present_newline_unchanged(self):
        src = lines("x = 1\n")
        assert fix(src) == src

    def test_strips_trailing_blank_lines(self):
        src = lines("x = 1\n\n\n")
        result = fix(src)
        assert "".join(result) == "x = 1\n"

    def test_empty_file_unchanged(self):
        assert fix([]) == []

    def test_idempotent(self):
        src = lines("x = 1")
        assert fix(fix(src)) == fix(src)


class TestFixMutationSafety:
    def test_does_not_mutate_caller_list(self):
        """fix() must never modify the list passed in."""
        original = ["x = 1\n", "\n", "\n"]
        copy = list(original)
        fix(original)
        assert original == copy


class TestFixCRLF:
    def test_crlf_file_gets_final_newline(self):
        src = ["x = 1\r"]  # no newline at all
        result = fix(src)
        assert "".join(result).endswith("\n")

    def test_crlf_trailing_blank_stripped(self):
        src = ["x = 1\r\n", "\r\n", "\r\n"]
        result = fix(src)
        assert result == ["x = 1\r\n"]
