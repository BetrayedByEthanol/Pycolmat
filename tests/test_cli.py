"""
CLI integration tests.

Tests exercise:
  - customfmt fix (Write mode)
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
from pathlib import Path

import pytest

from customfmt.cli import Main, MainCheck, MainFix

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def Run(*args: str) -> int:
   return Main(list(args))


def RunFix(*args: str) -> int:
   return Main(["fix", *args])


def RunCheck(*args: str) -> int:
   return Main(["check", *args])


# ---------------------------------------------------------------------------
# customfmt fix – Write mode
# ---------------------------------------------------------------------------


class TestFixWrite:
   def TestFixesTrailingWhitespace(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      assert RunFix(str(f)) == 0
      assert f.read_text() == "x = 1\n"

   def TestFixesFinalNewline(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1")
      assert RunFix(str(f)) == 0
      assert f.read_text().endswith("\n")

   def TestFixesSelfAlignment(self, tmp_path):
      src = "class A:\n   def __init__(self):\n      self.Foo = 1\n      self.BarBaz = 2\n"
      f = Write(tmp_path / "a.py", src)
      assert RunFix(str(f)) == 0
      content = f.read_text()
      assert "self.Foo    = 1" in content
      assert "self.BarBaz = 2" in content

   def TestCleanFileExit0(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1\n")
      assert RunFix(str(f)) == 0

   def TestDirectoryRecurse(self, tmp_path):
      sub = tmp_path / "sub"
      sub.mkdir()
      Write(sub / "a.py", "x = 1   \n")
      assert RunFix(str(tmp_path)) == 0
      assert (sub / "a.py").read_text() == "x = 1\n"

   def TestIgnoredDirsSkipped(self, tmp_path):
      venv = tmp_path / ".venv"
      venv.mkdir()
      f = Write(venv / "a.py", "x = 1   \n")
      RunFix(str(tmp_path))
      # file should be untouched
      assert f.read_text() == "x = 1   \n"

   def TestNoPyFilesExit2(self, tmp_path):
      assert RunFix(str(tmp_path)) == 2

   def TestNonexistentPathExit2(self, tmp_path):
      assert RunFix(str(tmp_path / "nope.py")) == 2


# ---------------------------------------------------------------------------
# customfmt fix --check
# ---------------------------------------------------------------------------


class TestFixCheck:
   def TestCleanExit0(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1\n")
      assert RunFix("--check", str(f)) == 0

   def TestDirtyExit1(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      assert RunFix("--check", str(f)) == 1

   def TestDoesNotModify(self, tmp_path):
      original = "x = 1   \n"
      f = Write(tmp_path / "a.py", original)
      RunFix("--check", str(f))
      assert f.read_text() == original

   def TestReportsWouldReformat(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      RunFix("--check", str(f))
      out = capsys.readouterr().out
      assert "would reformat" in out

   def TestQuietSuppressesOutput(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      RunFix("--check", "--quiet", str(f))
      out = capsys.readouterr().out
      assert out.strip() == ""


# ---------------------------------------------------------------------------
# customfmt fix --diff
# ---------------------------------------------------------------------------


class TestFixDiff:
   def TestDiffOutput(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--diff", str(f))
      out = capsys.readouterr().out
      assert "---" in out
      assert "+++" in out
      # Fix 3: --diff alone exits 0 even when changes would be made
      assert rc == 0

   def TestDiffDoesNotModify(self, tmp_path):
      original = "x = 1   \n"
      f = Write(tmp_path / "a.py", original)
      RunFix("--diff", str(f))
      assert f.read_text() == original

   def TestNoDiffCleanFile(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1\n")
      rc = RunFix("--diff", str(f))
      out = capsys.readouterr().out
      assert "---" not in out
      assert rc == 0

   def TestDiffAndCheckExits1WhenChanges(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--diff", "--check", str(f))
      out = capsys.readouterr().out
      assert "---" in out
      assert rc == 1

   def TestDiffAndCheckExits0WhenClean(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1\n")
      rc = RunFix("--diff", "--check", str(f))
      assert rc == 0


# ---------------------------------------------------------------------------
# customfmt check
# ---------------------------------------------------------------------------


class TestCheck:
   def TestCleanExit0(self, tmp_path):
      # Minimal file that passes all rules (3-space indent, PascalCase, etc.)
      src = "X = 1\n"
      f = Write(tmp_path / "my_module.py", src)
      assert RunCheck(str(f)) == 0

   def TestViolationsExit1(self, tmp_path):
      # 4-space indent → CF010
      src = "def calculate_total():\n    x = 1\n"
      f = Write(tmp_path / "my_module.py", src)
      assert RunCheck(str(f)) == 1

   def TestReportsViolations(self, tmp_path, capsys):
      src = "def calculate_total():\n   pass\n"
      f = Write(tmp_path / "my_module.py", src)
      RunCheck(str(f))
      out = capsys.readouterr().out
      assert "CF003" in out

   def TestQuietSuppressesViolations(self, tmp_path, capsys):
      src = "def calculate_total():\n   pass\n"
      f = Write(tmp_path / "my_module.py", src)
      RunCheck("--quiet", str(f))
      out = capsys.readouterr().out
      assert out.strip() == ""

   def TestDoesNotModify(self, tmp_path):
      original = "def calculate_total():\n   pass\n"
      f = Write(tmp_path / "my_module.py", original)
      RunCheck(str(f))
      assert f.read_text() == original

   def TestNoPyFilesExit2(self, tmp_path):
      assert RunCheck(str(tmp_path)) == 2

   def TestNonexistentPathExit2(self, tmp_path):
      assert RunCheck(str(tmp_path / "nope.py")) == 2

   def TestJsonOutputClean(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1\n")
      rc = RunCheck("--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert data == []
      assert rc == 0

   def TestJsonOutputViolations(self, tmp_path, capsys):
      src = "def calculate_total():\n   pass\n"
      f = Write(tmp_path / "my_module.py", src)
      rc = RunCheck("--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert isinstance(data, list)
      assert any(d["code"] == "CF003" for d in data)
      assert rc == 1

   def TestViolationFormat(self, tmp_path, capsys):
      # Expect: path:line:col CODE message
      src = "def calculate_total():\n   pass\n"
      f = Write(tmp_path / "my_module.py", src)
      RunCheck(str(f))
      out = capsys.readouterr().out
      lines = [ln for ln in out.splitlines() if "CF003" in ln]
      assert lines
      # should be parseable as "path:line:col CODE message"
      first = lines[0]
      parts = first.split(" ", 2)
      assert len(parts) >= 3
      loc = parts[0]  # path:line:col
      assert loc.count(":") >= 2


# ---------------------------------------------------------------------------
# customfmt doctor argument parsing
# ---------------------------------------------------------------------------


class TestDoctorCli:
   def TestJsonAndPrettyAreMutuallyExclusive(self, tmp_path):
      src = tmp_path / "src"
      src.mkdir()
      Write(src / "my_module.py", "X = 1\n")

      with pytest.raises(SystemExit) as exc_info:
         Run("doctor", str(src), "--json", "--pretty")

      assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Exit code 2 on tool errors
# ---------------------------------------------------------------------------


class TestExitCode2:
   def TestFixBadPath(self, tmp_path):
      assert RunFix(str(tmp_path / "missing.py")) == 2

   def TestCheckBadPath(self, tmp_path):
      assert RunCheck(str(tmp_path / "missing.py")) == 2


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


class TestAliases:
   def TestTryAutoFormatFix(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1\n")
      rc = MainFix([str(f)])
      assert rc == 0

   def TestTryAutoFormatCheck(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = MainFix(["--check", str(f)])
      assert rc == 1

   def TestCheckFormatAlias(self, tmp_path):
      f = Write(tmp_path / "my_module.py", "X = 1\n")
      rc = MainCheck([str(f)])
      assert rc == 0


# ---------------------------------------------------------------------------
# customfmt fix --quiet in Write mode (file must still be written)
# ---------------------------------------------------------------------------


class TestFixQuietWrite:
   def TestQuietStillWritesFile(self, tmp_path):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--quiet", str(f))
      assert rc == 0
      assert f.read_text() == "x = 1\n"

   def TestQuietProducesNoOutput(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      RunFix("--quiet", str(f))
      out = capsys.readouterr().out
      assert out.strip() == ""

   def TestQuietCheckNoOutputExit1(self, tmp_path, capsys):
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--quiet", "--check", str(f))
      assert rc == 1
      assert capsys.readouterr().out.strip() == ""


# ---------------------------------------------------------------------------
# customfmt fix --diff --quiet (diff output is not suppressed by --quiet)
# ---------------------------------------------------------------------------


class TestFixDiffQuiet:
   def TestDiffQuietSuppressesDiffOutput(self, tmp_path, capsys):
      """--quiet suppresses all output including diff; --diff exits 0."""
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--diff", "--quiet", str(f))
      out = capsys.readouterr().out
      # Fix 3: --diff alone exits 0 even when changes would be made
      assert rc == 0
      assert out.strip() == ""  # nothing printed due to --quiet

   def TestDiffWithoutQuietPrintsDiff(self, tmp_path, capsys):
      """--diff alone (no --quiet) prints the unified diff and exits 0."""
      f = Write(tmp_path / "a.py", "x = 1   \n")
      rc = RunFix("--diff", str(f))
      out = capsys.readouterr().out
      # Fix 3: --diff alone exits 0
      assert rc == 0
      assert "---" in out


# ---------------------------------------------------------------------------
# customfmt check --json with syntax-error file
# ---------------------------------------------------------------------------


class TestCheckJSONSyntaxError:
   def TestSyntaxErrorFilePartialResults(self, tmp_path, capsys):
      """
      A file with a SyntaxError can't be AST-parsed; naming rules skip it
      silently, but CF009/CF010 (line-based rules) still Run.
      The JSON output must be valid even when some rules can't Run.
      """
      f = Write(tmp_path / "bad_syntax.py", "def (:\n   pass\n")
      RunCheck("--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)  # must be valid JSON
      assert isinstance(data, list)
      # CF001 fires because 'bad_syntax.py' is valid snake_case,
      # but CF010 may fire due to indentation — just verify no crash.


# ---------------------------------------------------------------------------
# Stabilization smoke tests for read-only/reference/rename CLI commands
# ---------------------------------------------------------------------------


class TestStabilizationCliSmoke:
   def WriteSafeProject(self, tmp_path):
      src = (
         "class UserModel:\n"
         "   pass\n"
         "\n"
         "def BuildValue():\n"
         "   return UserModel()\n"
      )
      return Write(tmp_path / "models.py", src)

   def TestDoctorPrettySmoke(self, tmp_path, capsys):
      f = self.WriteSafeProject(tmp_path)

      rc = Run("doctor", str(f), "--pretty")

      out = capsys.readouterr().out
      data = json.loads(out)
      assert rc == 0
      assert data["python_file_count"] == 1
      assert data["exit_code"] == 0

   def TestRefsPrettySmoke(self, tmp_path, capsys):
      f = self.WriteSafeProject(tmp_path)

      rc = Run("refs", str(f), "--name", "UserModel", "--pretty")

      out = capsys.readouterr().out
      data = json.loads(out)
      assert rc == 0
      assert data["query"] == {"type": "name", "name": "UserModel"}
      assert data["summary"]["definitions"] == 1
      assert data["summary"]["references"] == 1

   def TestRenameSymbolDiffSmokeDoesNotWrite(self, tmp_path, capsys):
      f = self.WriteSafeProject(tmp_path)
      original = f.read_text(encoding="utf-8")

      rc = Run(
         "rename-symbol", str(f), "--name", "UserModel", "--to", "AccountModel", "--diff"
      )

      out = capsys.readouterr().out
      assert rc == 0
      assert "---" in out
      assert "+++" in out
      assert "class AccountModel:" in out
      assert "return AccountModel()" in out
      assert f.read_text(encoding="utf-8") == original

   def TestRenameSymbolApplySmokeWritesSafeTempProject(self, tmp_path, capsys):
      f = self.WriteSafeProject(tmp_path)

      rc = Run(
         "rename-symbol", str(f), "--name", "UserModel", "--to", "AccountModel", "--apply"
      )

      out = capsys.readouterr().out
      assert rc == 0
      assert f"renamed {f}" in out
      assert f.read_text(encoding="utf-8") == (
         "class AccountModel:\n"
         "   pass\n"
         "\n"
         "def BuildValue():\n"
         "   return AccountModel()\n"
      )


class TestRenameAttributeSkeletonCli:
   def WriteRepoProject(self, tmp_path):
      src = (
         "class Repo:\n"
         "   tableName = \"x\"\n"
         "\n"
         "def Run():\n"
         "   repo = Repo()\n"
         "   return repo.tableName\n"
      )
      return Write(tmp_path / "repo.py", src)

   def TestRejectsMissingClass(self, tmp_path, capsys):
      f = self.WriteRepoProject(tmp_path)

      rc = Run("rename-attribute", str(f), "--name", "tableName", "--to", "TableName", "--diff")

      err = capsys.readouterr().err
      assert rc == 2
      assert "rename-attribute requires --class" in err

   def TestRejectsMissingNameAndTo(self, tmp_path, capsys):
      f = self.WriteRepoProject(tmp_path)

      rc = Run("rename-attribute", str(f), "--class", "Repo", "--diff")

      err = capsys.readouterr().err
      assert rc == 2
      assert "rename-attribute requires --name, --to" in err

   def TestReportsDiffNotImplementedAndDoesNotWrite(self, tmp_path, capsys):
      f = self.WriteRepoProject(tmp_path)
      original = f.read_text(encoding="utf-8")

      rc = Run(
         "rename-attribute",
         str(f),
         "--class",
         "Repo",
         "--name",
         "tableName",
         "--to",
         "TableName",
         "--diff",
      )

      err = capsys.readouterr().err
      assert rc == 2
      assert "rename-attribute --diff is not implemented yet" in err
      assert "future diff planning must prove declaration" in err
      assert f.read_text(encoding="utf-8") == original

   def TestRejectsApplyAndDoesNotWrite(self, tmp_path, capsys):
      f = self.WriteRepoProject(tmp_path)
      original = f.read_text(encoding="utf-8")

      rc = Run(
         "rename-attribute",
         str(f),
         "--class",
         "Repo",
         "--name",
         "tableName",
         "--to",
         "TableName",
         "--apply",
      )

      err = capsys.readouterr().err
      assert rc == 2
      assert "rename-attribute apply is not implemented" in err
      assert f.read_text(encoding="utf-8") == original
