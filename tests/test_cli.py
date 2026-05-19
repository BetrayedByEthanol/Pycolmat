"""
CLI integration tests.

Tests exercise:
  - customfmt fix (write mode)
  - customfmt fix --check
  - customfmt fix --diff
  - customfmt fix --quiet
  - customfmt check (all rules)
  - customfmt check --json
  - Exit codes 0 / 1 / 2
  - try-auto-format alias
  - check-format alias
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from customfmt.cli import main, main_fix, main_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def run(*args: str) -> int:
    return main(list(args))


def run_fix(*args: str) -> int:
    return main(["fix", *args])


def run_check(*args: str) -> int:
    return main(["check", *args])


# ---------------------------------------------------------------------------
# customfmt fix – write mode
# ---------------------------------------------------------------------------

class TestFixWrite:
    def test_fixes_trailing_whitespace(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1   \n")
        assert run_fix(str(f)) == 0
        assert f.read_text() == "x = 1\n"

    def test_fixes_final_newline(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1")
        assert run_fix(str(f)) == 0
        assert f.read_text().endswith("\n")

    def test_fixes_self_alignment(self, tmp_path):
        src = "class A:\n   def __init__(self):\n      self.Foo = 1\n      self.BarBaz = 2\n"
        f = write(tmp_path / "a.py", src)
        assert run_fix(str(f)) == 0
        content = f.read_text()
        assert "self.Foo    = 1" in content
        assert "self.BarBaz = 2" in content

    def test_clean_file_exit_0(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1\n")
        assert run_fix(str(f)) == 0

    def test_directory_recurse(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        write(sub / "a.py", "x = 1   \n")
        assert run_fix(str(tmp_path)) == 0
        assert (sub / "a.py").read_text() == "x = 1\n"

    def test_ignored_dirs_skipped(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        f = write(venv / "a.py", "x = 1   \n")
        run_fix(str(tmp_path))
        # file should be untouched
        assert f.read_text() == "x = 1   \n"

    def test_no_py_files_exit_2(self, tmp_path):
        assert run_fix(str(tmp_path)) == 2

    def test_nonexistent_path_exit_2(self, tmp_path):
        assert run_fix(str(tmp_path / "nope.py")) == 2


# ---------------------------------------------------------------------------
# customfmt fix --check
# ---------------------------------------------------------------------------

class TestFixCheck:
    def test_clean_exit_0(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1\n")
        assert run_fix("--check", str(f)) == 0

    def test_dirty_exit_1(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1   \n")
        assert run_fix("--check", str(f)) == 1

    def test_does_not_modify(self, tmp_path):
        original = "x = 1   \n"
        f = write(tmp_path / "a.py", original)
        run_fix("--check", str(f))
        assert f.read_text() == original

    def test_reports_would_reformat(self, tmp_path, capsys):
        f = write(tmp_path / "a.py", "x = 1   \n")
        run_fix("--check", str(f))
        out = capsys.readouterr().out
        assert "would reformat" in out

    def test_quiet_suppresses_output(self, tmp_path, capsys):
        f = write(tmp_path / "a.py", "x = 1   \n")
        run_fix("--check", "--quiet", str(f))
        out = capsys.readouterr().out
        assert out.strip() == ""


# ---------------------------------------------------------------------------
# customfmt fix --diff
# ---------------------------------------------------------------------------

class TestFixDiff:
    def test_diff_output(self, tmp_path, capsys):
        f = write(tmp_path / "a.py", "x = 1   \n")
        rc = run_fix("--diff", str(f))
        out = capsys.readouterr().out
        assert "---" in out
        assert "+++" in out
        assert rc == 1

    def test_diff_does_not_modify(self, tmp_path):
        original = "x = 1   \n"
        f = write(tmp_path / "a.py", original)
        run_fix("--diff", str(f))
        assert f.read_text() == original

    def test_no_diff_clean_file(self, tmp_path, capsys):
        f = write(tmp_path / "a.py", "x = 1\n")
        rc = run_fix("--diff", str(f))
        out = capsys.readouterr().out
        assert "---" not in out
        assert rc == 0


# ---------------------------------------------------------------------------
# customfmt check
# ---------------------------------------------------------------------------

class TestCheck:
    def test_clean_exit_0(self, tmp_path):
        # Minimal file that passes all rules (3-space indent, PascalCase, etc.)
        src = "X = 1\n"
        f = write(tmp_path / "my_module.py", src)
        assert run_check(str(f)) == 0

    def test_violations_exit_1(self, tmp_path):
        # 4-space indent → CF010
        src = "def CalculateTotal():\n    x = 1\n"
        f = write(tmp_path / "my_module.py", src)
        assert run_check(str(f)) == 1

    def test_reports_violations(self, tmp_path, capsys):
        src = "def calculate_total():\n   pass\n"
        f = write(tmp_path / "my_module.py", src)
        run_check(str(f))
        out = capsys.readouterr().out
        assert "CF003" in out

    def test_quiet_suppresses_violations(self, tmp_path, capsys):
        src = "def calculate_total():\n   pass\n"
        f = write(tmp_path / "my_module.py", src)
        run_check("--quiet", str(f))
        out = capsys.readouterr().out
        assert out.strip() == ""

    def test_does_not_modify(self, tmp_path):
        original = "def calculate_total():\n   pass\n"
        f = write(tmp_path / "my_module.py", original)
        run_check(str(f))
        assert f.read_text() == original

    def test_no_py_files_exit_2(self, tmp_path):
        assert run_check(str(tmp_path)) == 2

    def test_nonexistent_path_exit_2(self, tmp_path):
        assert run_check(str(tmp_path / "nope.py")) == 2

    def test_json_output_clean(self, tmp_path, capsys):
        f = write(tmp_path / "my_module.py", "X = 1\n")
        rc = run_check("--json", str(f))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data == []
        assert rc == 0

    def test_json_output_violations(self, tmp_path, capsys):
        src = "def calculate_total():\n   pass\n"
        f = write(tmp_path / "my_module.py", src)
        rc = run_check("--json", str(f))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert any(d["code"] == "CF003" for d in data)
        assert rc == 1

    def test_violation_format(self, tmp_path, capsys):
        # Expect: path:line:col CODE message
        src = "def calculate_total():\n   pass\n"
        f = write(tmp_path / "my_module.py", src)
        run_check(str(f))
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if "CF003" in l]
        assert lines
        # should be parseable as "path:line:col CODE message"
        first = lines[0]
        parts = first.split(" ", 2)
        assert len(parts) >= 3
        loc = parts[0]  # path:line:col
        assert loc.count(":") >= 2


# ---------------------------------------------------------------------------
# Exit code 2 on tool errors
# ---------------------------------------------------------------------------

class TestExitCode2:
    def test_fix_bad_path(self, tmp_path):
        assert run_fix(str(tmp_path / "missing.py")) == 2

    def test_check_bad_path(self, tmp_path):
        assert run_check(str(tmp_path / "missing.py")) == 2


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    def test_try_auto_format_fix(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1\n")
        rc = main_fix([str(f)])
        assert rc == 0

    def test_try_auto_format_check(self, tmp_path):
        f = write(tmp_path / "a.py", "x = 1   \n")
        rc = main_fix(["--check", str(f)])
        assert rc == 1

    def test_check_format_alias(self, tmp_path):
        f = write(tmp_path / "my_module.py", "X = 1\n")
        rc = main_check([str(f)])
        assert rc == 0
