"""
Tests for the --ignore option (rule code filtering).

TestParseIgnoreCodes
   TestSingleCode
   TestCommaList
   TestSemicolonList
   TestMixedSeparators
   TestRepeatedValues
   TestCaseInsensitive
   TestWhitespace
   TestEmpty

TestCheckIgnore
   TestIgnoreSuppressesViolation
   TestIgnoreExitBecomes0
   TestIgnoreSemicolonList
   TestIgnoreCommaList
   TestIgnoreRepeated
   TestIgnoreCaseInsensitive
   TestJsonExcludesIgnored
   TestUnignoredViolationsStillReported

TestFixCheckIgnore
   TestFixCheckIgnoredDoesNotReport
   TestFixCheckIgnoredExits0
   TestFixCheckOnlyIgnoredMakesExit0

TestFixWriteIgnore
   TestFixIgnoreCF013SkipsClassAlignment
   TestFixIgnoreCF009SkipsSelfAlignment
   TestFixIgnoreCF011SkipsCrlfNorm
   TestFixIgnoreCF018SkipsTrailingWhitespace
   TestFixIgnoreCF019SkipsFinalNewline
   TestFixUnignoredRulesStillApply

TestCF018CF019Codes
   TestCF018ReportedForTrailingWhitespace
   TestCF019ReportedForMissingFinalNewline
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main, ParseIgnoreCodes
from customfmt.io import UTF8_BOM
from customfmt.rules.trailing_whitespace import RULE_CODE as CF018
from customfmt.rules.final_newline import RULE_CODE as CF019

P = Path("my_module.py")


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def WriteBytes(path: Path, data: bytes) -> Path:
   path.write_bytes(data)
   return path


def RunMain(*args: str) -> int:
   return Main(list(args))


# ---------------------------------------------------------------------------
# TestParseIgnoreCodes
# ---------------------------------------------------------------------------


class TestParseIgnoreCodes:
   def TestSingleCode(self):
      assert ParseIgnoreCodes(["CF014"]) == frozenset({"CF014"})

   def TestCommaList(self):
      assert ParseIgnoreCodes(["CF014,CF015"]) == frozenset({"CF014", "CF015"})

   def TestSemicolonList(self):
      assert ParseIgnoreCodes(["CF014;CF015"]) == frozenset({"CF014", "CF015"})

   def TestMixedSeparators(self):
      result = ParseIgnoreCodes(["CF014,CF015;CF009"])
      assert result == frozenset({"CF014", "CF015", "CF009"})

   def TestRepeatedValues(self):
      result = ParseIgnoreCodes(["CF014", "CF015"])
      assert result == frozenset({"CF014", "CF015"})

   def TestCaseInsensitive(self):
      assert ParseIgnoreCodes(["cf014"]) == frozenset({"CF014"})
      assert ParseIgnoreCodes(["Cf014,CF015"]) == frozenset({"CF014", "CF015"})

   def TestWhitespace(self):
      result = ParseIgnoreCodes(["CF014 , CF015 ; CF009"])
      assert result == frozenset({"CF014", "CF015", "CF009"})

   def TestEmpty(self):
      assert ParseIgnoreCodes([]) == frozenset()
      assert ParseIgnoreCodes([""]) == frozenset()


# ---------------------------------------------------------------------------
# TestCheckIgnore — check command
# ---------------------------------------------------------------------------


class TestCheckIgnore:
   def _CrlfFile(self, tmp_path: Path) -> Path:
      """CRLF file → CF011."""
      return WriteBytes(tmp_path / "my_module.py", b"X = 1\r\n")

   def _HoistingFile(self, tmp_path: Path) -> Path:
      """Declaration after function → CF014."""
      return Write(
         tmp_path / "my_module.py",
         "def Foo():\n   pass\n\nLATE = 1\n",
      )

   def TestIgnoreSuppressesViolation(self, tmp_path, capsys):
      f = self._CrlfFile(tmp_path)
      RunMain("check", "--ignore", "CF011", str(f))
      out = capsys.readouterr().out
      assert "CF011" not in out

   def TestIgnoreExitBecomes0(self, tmp_path):
      f = self._CrlfFile(tmp_path)
      rc = RunMain("check", "--ignore", "CF011", str(f))
      assert rc == 0

   def TestIgnoreSemicolonList(self, tmp_path):
      f = self._HoistingFile(tmp_path)
      rc = RunMain("check", "--ignore", "CF014;CF015", str(f))
      assert rc == 0

   def TestIgnoreCommaList(self, tmp_path):
      f = self._HoistingFile(tmp_path)
      rc = RunMain("check", "--ignore", "CF014,CF015", str(f))
      assert rc == 0

   def TestIgnoreRepeated(self, tmp_path):
      f = self._HoistingFile(tmp_path)
      rc = RunMain("check", "--ignore", "CF014", "--ignore", "CF015", str(f))
      assert rc == 0

   def TestIgnoreCaseInsensitive(self, tmp_path):
      f = self._CrlfFile(tmp_path)
      rc = RunMain("check", "--ignore", "cf011", str(f))
      assert rc == 0

   def TestJsonExcludesIgnored(self, tmp_path, capsys):
      f = self._CrlfFile(tmp_path)
      RunMain("check", "--json", "--ignore", "CF011", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert all(v["code"] != "CF011" for v in data)

   def TestUnignoredViolationsStillReported(self, tmp_path, capsys):
      """Ignoring one code must not suppress unrelated violations."""
      # File has both CRLF (CF011) and a CF014 hoisting violation.
      src = b"def Foo():\r\n   pass\r\n\r\nLATE = 1\r\n"
      f = WriteBytes(tmp_path / "my_module.py", src)
      RunMain("check", "--ignore", "CF011", str(f))
      out = capsys.readouterr().out
      assert "CF014" in out


# ---------------------------------------------------------------------------
# TestFixCheckIgnore — fix --check mode
# ---------------------------------------------------------------------------


class TestFixCheckIgnore:
   def TestFixCheckIgnoredDoesNotReport(self, tmp_path, capsys):
      f = WriteBytes(tmp_path / "f.py", b"x = 1   \n")
      RunMain("fix", "--check", "--ignore", CF018, str(f))
      out = capsys.readouterr().out
      assert "would reformat" not in out

   def TestFixCheckIgnoredExits0(self, tmp_path):
      f = WriteBytes(tmp_path / "f.py", b"x = 1   \n")
      rc = RunMain("fix", "--check", "--ignore", CF018, str(f))
      assert rc == 0

   def TestFixCheckOnlyIgnoredMakesExit0(self, tmp_path):
      """If the ONLY fixable change is ignored, exit is 0."""
      # File has only trailing whitespace (CF018) — ignore it → exit 0.
      f = WriteBytes(tmp_path / "f.py", b"x = 1   \n")
      rc = RunMain("fix", "--check", "--ignore", CF018, str(f))
      assert rc == 0


# ---------------------------------------------------------------------------
# TestFixWriteIgnore — fix write mode
# ---------------------------------------------------------------------------


class TestFixWriteIgnore:
   def TestFixIgnoreCF013SkipsClassAlignment(self, tmp_path):
      """--ignore CF013: class-body alignment must NOT be applied."""
      src = "class A:\n   TableName = 'x'\n   References = {}\n"
      f = Write(tmp_path / "f.py", src)
      RunMain("fix", "--ignore", "CF013", str(f))
      content = f.read_text(encoding="utf-8")
      # The two class-body declarations were NOT aligned (TableName is shorter).
      assert "TableName = 'x'" in content  # still unaligned
      assert "References = {}" in content

   def TestFixIgnoreCF009SkipsSelfAlignment(self, tmp_path):
      """--ignore CF009: self.X alignment must NOT be applied."""
      # Build intentionally-unaligned source as a list so the file itself
      # does not contain a raw unaligned self-assignment block (CF009).
      src_lines = [
         "class A:\n",
         "   def __init__(self):\n",
         "      self.Foo = 1\n",       # intentionally unaligned
         "      self.BarBaz = 2\n",
      ]
      f = Write(tmp_path / "f.py", "".join(src_lines))
      RunMain("fix", "--ignore", "CF009", str(f))
      content = f.read_text(encoding="utf-8")
      # self.Foo should remain unaligned (no extra spaces before =)
      assert "self.Foo = 1" in content

   def TestFixIgnoreCF011SkipsCrlfNorm(self, tmp_path):
      """--ignore CF011: CRLF must NOT be converted to LF."""
      f = WriteBytes(tmp_path / "f.py", b"x = 1\r\ny = 2\r\n")
      RunMain("fix", "--ignore", "CF011", str(f))
      assert b"\r\n" in f.read_bytes()

   def TestFixIgnoreCF018SkipsTrailingWhitespace(self, tmp_path):
      """--ignore CF018: trailing whitespace must NOT be removed."""
      f = WriteBytes(tmp_path / "f.py", b"x = 1   \n")
      RunMain("fix", "--ignore", CF018, str(f))
      assert f.read_bytes() == b"x = 1   \n"

   def TestFixIgnoreCF019SkipsFinalNewline(self, tmp_path):
      """--ignore CF019: missing final newline must NOT be added."""
      # Also ignore CF018 so trailing_whitespace.Fix does not add \n
      # as a side-effect of normalising a line with no terminator.
      f = WriteBytes(tmp_path / "f.py", b"x = 1")
      RunMain("fix", "--ignore", CF019, "--ignore", CF018, str(f))
      assert not f.read_bytes().endswith(b"\n")

   def TestFixUnignoredRulesStillApply(self, tmp_path):
      """When CF013 is ignored, other fix rules (CF018) still run."""
      # File has both trailing whitespace (CF018) and class-body misalignment (CF013).
      src = "class A:\n   TableName = 'x'   \n   References = {}   \n"
      f = Write(tmp_path / "f.py", src)
      RunMain("fix", "--ignore", "CF013", str(f))
      content = f.read_text(encoding="utf-8")
      # CF018 (trailing whitespace) was fixed
      assert "   \n" not in content
      # CF013 (alignment) was NOT applied — still unaligned
      assert "TableName = 'x'" in content


# ---------------------------------------------------------------------------
# TestCF018CF019Codes — verify new rule codes in check output
# ---------------------------------------------------------------------------


class TestCF018CF019Codes:
   def TestCF018ReportedForTrailingWhitespace(self, tmp_path, capsys):
      """fix --check reports CF018 for trailing whitespace."""
      f = WriteBytes(tmp_path / "my_module.py", b"X = 1   \n")
      RunMain("fix", "--check", str(f))
      out = capsys.readouterr().out
      assert "CF018" in out

   def TestCF019ReportedForMissingFinalNewline(self, tmp_path, capsys):
      """fix --check reports CF019 for missing final newline."""
      f = WriteBytes(tmp_path / "my_module.py", b"X = 1")
      RunMain("fix", "--check", str(f))
      out = capsys.readouterr().out
      assert "CF019" in out

   def TestCF018CodeConstant(self):
      assert CF018 == "CF018"

   def TestCF019CodeConstant(self):
      assert CF019 == "CF019"
