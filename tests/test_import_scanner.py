"""Tests for customfmt deps (import_scanner + CLI subcommand)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from customfmt.cli import Main
from customfmt.symbols.import_scanner import STDLIB, ScanImports, _InferMarkerFromTest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def RunDeps(*args: str) -> int:
   return Main(["deps", *args])


# ---------------------------------------------------------------------------
# STDLIB filter
# ---------------------------------------------------------------------------


class TestStdlibSet:
   def TestCommonStdlibFiltered(self):
      assert "os" in STDLIB
      assert "sys" in STDLIB
      assert "pathlib" in STDLIB
      assert "json" in STDLIB
      assert "asyncio" in STDLIB

   def TestExternalNotInStdlib(self):
      assert "requests" not in STDLIB
      assert "flask" not in STDLIB
      assert "numpy" not in STDLIB


# ---------------------------------------------------------------------------
# Platform marker inference
# ---------------------------------------------------------------------------


class TestInferMarker:
   def _Parse(self, expr: str):
      import ast
      return ast.parse(expr, mode="eval").body

   def TestSysPlatformEqWin32(self):
      node = self._Parse('sys.platform == "win32"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "win32"'

   def TestSysPlatformEqLinux(self):
      node = self._Parse('sys.platform == "linux"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "linux"'

   def TestSysPlatformEqDarwin(self):
      node = self._Parse('sys.platform == "darwin"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "darwin"'

   def TestOsNameEqNt(self):
      node = self._Parse('os.name == "nt"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "win32"'

   def TestOsNameEqPosix(self):
      node = self._Parse('os.name == "posix"')
      assert _InferMarkerFromTest(node) == 'sys_platform != "win32"'

   def TestPlatformSystemWindows(self):
      node = self._Parse('platform.system() == "Windows"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "win32"'

   def TestPlatformSystemLinux(self):
      node = self._Parse('platform.system() == "Linux"')
      assert _InferMarkerFromTest(node) == 'sys_platform == "linux"'

   def TestSysPlatformStartswithWin(self):
      node = self._Parse('sys.platform.startswith("win")')
      assert _InferMarkerFromTest(node) == 'sys_platform == "win32"'

   def TestNegatedNotExpr(self):
      node = self._Parse('not sys.platform == "win32"')
      assert _InferMarkerFromTest(node) == 'sys_platform != "win32"'

   def TestNegatedFlag(self):
      node = self._Parse('sys.platform == "win32"')
      assert _InferMarkerFromTest(node, negated=True) == 'sys_platform != "win32"'

   def TestUnrecognisedReturnsNone(self):
      node = self._Parse('"some_custom_check"')
      assert _InferMarkerFromTest(node) is None


# ---------------------------------------------------------------------------
# ScanImports — basic detection
# ---------------------------------------------------------------------------


class TestScanImports:
   def TestSimpleExternalImport(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      result, errs = ScanImports([str(tmp_path)])
      assert not errs
      names = {e.PackageName for e in result.Imports}
      assert "requests" in names

   def TestStdlibExcluded(self, tmp_path):
      Write(tmp_path / "mod.py", "import os\nimport sys\nimport pathlib\n")
      result, errs = ScanImports([str(tmp_path)])
      assert not errs
      assert result.Imports == []

   def TestImportFrom(self, tmp_path):
      Write(tmp_path / "mod.py", "from flask import Flask\n")
      result, errs = ScanImports([str(tmp_path)])
      names = {e.PackageName for e in result.Imports}
      assert "flask" in names

   def TestKnownMismatchPIL(self, tmp_path):
      Write(tmp_path / "mod.py", "from PIL import Image\n")
      result, errs = ScanImports([str(tmp_path)])
      names = {e.PackageName for e in result.Imports}
      assert "Pillow" in names

   def TestKnownMismatchYaml(self, tmp_path):
      Write(tmp_path / "mod.py", "import yaml\n")
      result, errs = ScanImports([str(tmp_path)])
      names = {e.PackageName for e in result.Imports}
      assert "PyYAML" in names

   def TestModuleLevelIsNotConditional(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      result, errs = ScanImports([str(tmp_path)])
      entry = next(e for e in result.Imports if e.PackageName == "requests")
      assert not entry.IsConditional

   def TestDeduplication(self, tmp_path):
      Write(tmp_path / "a.py", "import requests\n")
      Write(tmp_path / "b.py", "import requests\n")
      result, errs = ScanImports([str(tmp_path)])
      entries = [e for e in result.Imports if e.PackageName == "requests"]
      assert len(entries) == 1
      assert len(entries[0].Locations) == 2

   def TestLocationFormat(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      result, errs = ScanImports([str(tmp_path)])
      entry = next(e for e in result.Imports if e.PackageName == "requests")
      assert any("mod.py" in loc for loc in entry.Locations)


# ---------------------------------------------------------------------------
# ScanImports — conditional / platform imports
# ---------------------------------------------------------------------------


class TestConditionalImports:
   def TestConditionalMarkerWin32(self, tmp_path):
      src = (
         "import sys\n"
         "def Setup():\n"
         "   if sys.platform == 'win32':\n"
         "      import pywin32\n"
      )
      Write(tmp_path / "mod.py", src)
      result, errs = ScanImports([str(tmp_path)])
      entry = next((e for e in result.Imports if e.PackageName == "pywin32"), None)
      assert entry is not None
      assert entry.IsConditional
      assert entry.PlatformMarker == 'sys_platform == "win32"'
      assert not entry.NeedsReview

   def TestConditionalElseBranchNegated(self, tmp_path):
      src = (
         "import sys\n"
         "def Setup():\n"
         "   if sys.platform == 'win32':\n"
         "      import pywin32\n"
         "   else:\n"
         "      import some_unix_lib\n"
      )
      Write(tmp_path / "mod.py", src)
      result, errs = ScanImports([str(tmp_path)])
      unix_entry = next((e for e in result.Imports if e.PackageName == "some-unix-lib"), None)
      assert unix_entry is not None
      assert unix_entry.IsConditional
      assert unix_entry.PlatformMarker == 'sys_platform != "win32"'

   def TestConditionalUnrecognisedNeedsReview(self, tmp_path):
      src = (
         "def Setup():\n"
         "   if some_custom_check():\n"
         "      import special_pkg\n"
      )
      Write(tmp_path / "mod.py", src)
      result, errs = ScanImports([str(tmp_path)])
      entry = next((e for e in result.Imports if e.PackageName == "special-pkg"), None)
      assert entry is not None
      assert entry.IsConditional
      assert entry.NeedsReview
      assert entry.PlatformMarker is None

   def TestModuleLevelWinsOverConditional(self, tmp_path):
      # If the same package appears at module level AND inside a conditional,
      # the merged entry should be unconditional.
      src = (
         "import requests\n"
         "def Compat():\n"
         "   if sys.platform == 'win32':\n"
         "      import requests\n"
      )
      Write(tmp_path / "mod.py", src)
      result, errs = ScanImports([str(tmp_path)])
      entry = next(e for e in result.Imports if e.PackageName == "requests")
      assert not entry.IsConditional
      assert entry.PlatformMarker is None


# ---------------------------------------------------------------------------
# RequirementsLine formatting
# ---------------------------------------------------------------------------


class TestRequirementsLine:
   def TestUnconditional(self):
      from customfmt.symbols.import_scanner import ImportEntry
      e = ImportEntry("requests", "requests", [], False, None, False)
      assert e.RequirementsLine() == "requests"

   def TestWithMarker(self):
      from customfmt.symbols.import_scanner import ImportEntry
      e = ImportEntry("pywin32", "pywin32", [], True, 'sys_platform == "win32"', False)
      assert e.RequirementsLine() == 'pywin32; sys_platform == "win32"'

   def TestNeedsReviewComment(self):
      from customfmt.symbols.import_scanner import ImportEntry
      e = ImportEntry("special-pkg", "special_pkg", [], True, None, True)
      assert "REVIEW" in e.RequirementsLine()


# ---------------------------------------------------------------------------
# FormatRequirementsIn output
# ---------------------------------------------------------------------------


class TestFormatRequirementsIn:
   def TestHeaderPresent(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      result, _ = ScanImports([str(tmp_path)])
      output = result.FormatRequirementsIn()
      assert "requirements.in" in output
      assert "customfmt deps" in output

   def TestUnconditionalBeforeConditional(self, tmp_path):
      src = (
         "import requests\n"
         "def Setup():\n"
         "   if sys.platform == 'win32':\n"
         "      import pywin32\n"
      )
      Write(tmp_path / "mod.py", src)
      result, _ = ScanImports([str(tmp_path)])
      output = result.FormatRequirementsIn()
      req_pos = output.index("requests")
      win_pos = output.index("pywin32")
      assert req_pos < win_pos

   def TestEndsWithNewline(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      result, _ = ScanImports([str(tmp_path)])
      assert result.FormatRequirementsIn().endswith("\n")


# ---------------------------------------------------------------------------
# CLI: customfmt deps
# ---------------------------------------------------------------------------


class TestDepsCli:
   def TestBasicExit0(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      assert RunDeps(str(tmp_path)) == 0

   def TestNoPythonFilesExit2(self, tmp_path):
      assert RunDeps(str(tmp_path)) == 2

   def TestJsonOutput(self, tmp_path, capsys):
      Write(tmp_path / "mod.py", "import requests\n")
      rc = RunDeps("--json", str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "imports" in data
      assert "errors" in data

   def TestPrettyOutput(self, tmp_path, capsys):
      Write(tmp_path / "mod.py", "import requests\n")
      rc = RunDeps("--pretty", str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "imports" in data

   def TestJsonPrettyMutuallyExclusive(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      with pytest.raises(SystemExit) as exc_info:
         RunDeps("--json", "--pretty", str(tmp_path))
      assert exc_info.value.code == 2

   def TestOutputFile(self, tmp_path):
      Write(tmp_path / "mod.py", "import requests\n")
      out_file = tmp_path / "requirements.in"
      rc = RunDeps("--output", str(out_file), str(tmp_path))
      assert rc == 0
      assert out_file.exists()
      content = out_file.read_text(encoding="utf-8")
      assert "requests" in content

   def TestRequirementsInFormatDefault(self, tmp_path, capsys):
      Write(tmp_path / "mod.py", "import flask\n")
      rc = RunDeps(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      assert "flask" in out
      # Should not be JSON by default
      assert not out.strip().startswith("{")

   def TestStdlibOnlyProjectExit0(self, tmp_path, capsys):
      Write(tmp_path / "mod.py", "import os\nimport sys\n")
      rc = RunDeps(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      # No packages emitted beyond the header comment
      lines = [line for line in out.splitlines() if line and not line.startswith("#")]
      assert lines == []

   def TestConditionalInOutput(self, tmp_path, capsys):
      src = (
         "def Setup():\n"
         "   if sys.platform == 'win32':\n"
         "      import pywin32\n"
      )
      Write(tmp_path / "mod.py", src)
      rc = RunDeps(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      assert "pywin32" in out
      assert 'sys_platform == "win32"' in out
