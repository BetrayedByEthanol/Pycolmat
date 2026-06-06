"""Tests for the read-only customfmt doctor command."""

from __future__ import annotations

import json
from pathlib import Path

from customfmt.cli import Main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def RunDoctor(*args: str) -> int:
   return Main(["doctor", *args])


# ---------------------------------------------------------------------------
# customfmt doctor
# ---------------------------------------------------------------------------


class TestDoctor:
   def TestCleanProjectExit0(self, tmp_path):
      pkg = tmp_path / "pkg"
      pkg.mkdir()
      Write(pkg / "__init__.py", "")
      Write(pkg / "module.py", "X = 1\n")

      assert RunDoctor(str(pkg)) == 0

   def TestStyleViolationsExit1(self, tmp_path):
      f = Write(tmp_path / "my_module.py", "def calculate_total():\n   pass\n")

      assert RunDoctor(str(f)) == 1

   def TestNoPythonFilesExit2(self, tmp_path):
      assert RunDoctor(str(tmp_path)) == 2

   def TestDetectsCrlf(self, tmp_path, capsys):
      f = tmp_path / "my_module.py"
      f.write_bytes(b"X = 1\r\n")

      rc = RunDoctor("--json", str(f))
      data = json.loads(capsys.readouterr().out)

      assert rc == 1
      assert data["encoding"]["crlf_count"] == 1
      assert str(f) in data["encoding"]["crlf_files"]
      assert data["auto_fix_readiness"]["by_rule"]["CF011"] == 1
      assert f.read_bytes() == b"X = 1\r\n"

   def TestDetectsTrailingWhitespaceAndFinalNewline(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1   ")

      rc = RunDoctor("--json", str(f))
      data = json.loads(capsys.readouterr().out)

      assert rc == 1
      assert data["auto_fix_readiness"]["by_rule"]["CF018"] == 1
      assert data["auto_fix_readiness"]["by_rule"]["CF019"] == 1
      assert f.read_text(encoding="utf-8") == "X = 1   "

   def TestDetectsParserErrorsExit2(self, tmp_path, capsys):
      f = Write(tmp_path / "bad_syntax.py", "def (:\n   pass\n")

      rc = RunDoctor("--json", str(f))
      data = json.loads(capsys.readouterr().out)

      assert rc == 2
      assert data["symbol_readiness"]["index_errors"]
      assert data["symbol_readiness"]["resolver_errors"]

   def TestJsonOutputMachineReadable(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      rc = RunDoctor("--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)

      assert rc == 0
      assert data["python_file_count"] == 1
      assert data["python_files"] == [str(f)]
      assert data["exit_code"] == 0

   def TestPrettyOutputsIndentedJson(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      rc = RunDoctor("--pretty", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)

      assert rc == 0
      assert "\n  \"python_file_count\"" in out
      assert data["python_file_count"] == 1

   def TestHumanOutputIncludesSummarySections(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      rc = RunDoctor(str(f))
      out = capsys.readouterr().out

      assert rc == 0
      assert "Python file discovery" in out
      assert "Encoding / line endings" in out
      assert "customfmt rule status" in out
      assert "Auto-fix readiness" in out
      assert "Symbol tooling readiness" in out
      assert "Package / import readiness" in out

   def TestDetectsNamespaceLikeDirectories(self, tmp_path, capsys):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      rc = RunDoctor("--json", str(f))
      data = json.loads(capsys.readouterr().out)

      assert rc == 0
      assert data["package_readiness"]["namespace_like_count"] == 1
      assert data["package_readiness"]["warnings"]
