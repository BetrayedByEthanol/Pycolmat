"""Tests for the read-only customfmt doctor command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
   def TestJsonPrettyMutuallyExclusiveExit2(self, tmp_path):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      with pytest.raises(SystemExit) as exc_info:
         RunDoctor(str(f), "--json", "--pretty")

      assert exc_info.value.code == 2

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

   def TestReportsUnambiguousNamespaceLikeDirectoriesWithoutWarning(
      self, tmp_path, capsys
   ):
      ns = tmp_path / "ns"
      ns.mkdir()
      f = Write(ns / "my_module.py", "X = 1\n")

      rc = RunDoctor("--json", str(tmp_path))
      data = json.loads(capsys.readouterr().out)

      assert rc == 0
      assert data["package_readiness"]["namespace_like_count"] == 1
      assert data["package_readiness"]["namespace_like_dirs"] == [str(f.parent)]
      assert data["package_readiness"]["warnings"] == []

   def TestWarnsForAmbiguousNamespacePackageStructure(self, tmp_path, capsys):
      first = tmp_path / "first" / "ns"
      second = tmp_path / "second" / "ns"
      first.mkdir(parents=True)
      second.mkdir(parents=True)
      Write(first / "models.py", "X = 1\n")
      Write(second / "models.py", "Y = 1\n")

      rc = RunDoctor("--json", str(tmp_path / "first"), str(tmp_path / "second"))
      data = json.loads(capsys.readouterr().out)

      assert rc == 0
      assert data["package_readiness"]["namespace_like_count"] == 2
      assert "ns.models" in data["package_readiness"]["ambiguous_namespace_modules"]
      assert data["package_readiness"]["warnings"]

   def TestEncodingIoErrorsHaveSeparateJsonBucket(self, tmp_path, capsys, monkeypatch):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      def RaiseIoError(path):
         if path == f:
            raise OSError("permission denied")
         return path.read_bytes()

      monkeypatch.setattr("customfmt.doctor.ReadUtf8Bytes", RaiseIoError)

      rc = RunDoctor("--json", str(f))
      data = json.loads(capsys.readouterr().out)

      assert rc == 2
      assert data["encoding"]["non_utf8_count"] == 0
      assert data["encoding"]["non_utf8_files"] == []
      assert data["encoding"]["io_error_count"] == 1
      assert data["encoding"]["io_error_files"] == [str(f)]
      assert data["exit_code"] == 2

   def TestEncodingIoErrorsAppearInHumanOutput(self, tmp_path, capsys, monkeypatch):
      f = Write(tmp_path / "my_module.py", "X = 1\n")

      def RaiseIoError(path):
         if path == f:
            raise OSError("permission denied")
         return path.read_bytes()

      monkeypatch.setattr("customfmt.doctor.ReadUtf8Bytes", RaiseIoError)

      rc = RunDoctor(str(f))
      out = capsys.readouterr().out

      assert rc == 2
      assert "io_errors: 1" in out
      assert "io_error_files:" in out
      assert str(f) in out
      assert "non_utf8: 0" in out
