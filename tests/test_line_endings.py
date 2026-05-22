"""
Tests for CF011 / CF012 and the UTF-8 LF I/O pipeline.

Coverage
--------
TestLineEndingsRule
   TestCheckBytesCrlf          – CF011 reported for CRLF bytes
   TestCheckBytesCrOnly        – CF011 reported for bare CR bytes
   TestCheckBytesLfClean       – no violation for LF-only bytes
   TestCheckBytesEmptyFile     – no violation for empty file
   TestCheckBytesBom           – CF012 reported for UTF-8 BOM
   TestCheckBytesInvalidUtf8   – CF012 reported for invalid UTF-8
   TestCheckBytesInvalidUtf8SkipsCf011 – CF012 stops further checks
   TestFixTextCrlf             – CRLF normalised to LF
   TestFixTextCrOnly           – bare CR normalised to LF
   TestFixTextMixed            – mixed CRLF + bare CR both normalised
   TestFixTextLfUnchanged      – LF text returned unchanged
   TestFixTextIdempotent       – applying FixText twice is safe

TestIoHelpers
   TestReadUtf8TextValid       – clean file round-trips correctly
   TestReadUtf8TextBomRaises   – ValueError on BOM
   TestReadUtf8TextBadBytesRaises – UnicodeDecodeError on bad bytes
   TestWriteUtf8LfNormalises   – CRLF in text is written as LF bytes
   TestWriteUtf8LfRoundTrip    – written file reads back identically

TestFormatterPipeline
   TestProcessFileCrlfFixed    – CRLF file is rewritten with LF
   TestProcessFileCrOnlyFixed  – CR-only file is rewritten with LF
   TestProcessFileLfUnchanged  – LF file reports no change
   TestProcessFileCheckCrlf    – fix --check reports CF011 for CRLF
   TestProcessFileBomRaises    – BOM file raises ValueError (exit 2)
   TestProcessFileBadUtf8Raises – bad UTF-8 file raises UnicodeDecodeError

TestCheckerPipeline
   TestCheckFileCf011Crlf      – checker reports CF011 for CRLF
   TestCheckFileCf012Bom       – checker reports CF012 for BOM
   TestCheckFileCf012BadUtf8   – checker reports CF012 for invalid bytes
   TestCheckFileBadUtf8SkipsAst – CF012 returned, no crash, no AST viols

TestCliIntegration
   TestFixCrlfExits0           – fix rewrites CRLF file, exits 0
   TestFixBadUtf8Exits2        – fix on invalid UTF-8 exits 2
   TestCheckCf011Exits1        – check exits 1 for CRLF file
   TestCheckCf012Exits1        – check exits 1 for BOM file
"""

from __future__ import annotations

from pathlib import Path

import pytest

from customfmt.checker import CheckFile
from customfmt.cli import Main
from customfmt.formatter import ProcessFile
from customfmt.io import UTF8_BOM, ReadUtf8Text, WriteUtf8Lf
from customfmt.rules.line_endings import (
   RULE_CF011,
   RULE_CF012,
   CheckBytes,
   FixText,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Write(path: Path, data: bytes) -> Path:
   path.write_bytes(data)
   return path


def RunMain(*args: str) -> int:
   return Main(list(args))


# ---------------------------------------------------------------------------
# CheckBytes / FixText unit tests
# ---------------------------------------------------------------------------


class TestLineEndingsRule:
   def TestCheckBytesCrlf(self, tmp_path):
      raw = b"x = 1\r\ny = 2\r\n"
      viols = CheckBytes(raw, tmp_path / "f.py")
      assert any(v.code == RULE_CF011 for v in viols)
      assert any("CRLF" in v.message for v in viols)

   def TestCheckBytesCrOnly(self, tmp_path):
      raw = b"x = 1\ry = 2\r"
      viols = CheckBytes(raw, tmp_path / "f.py")
      assert any(v.code == RULE_CF011 for v in viols)
      assert any("CR" in v.message for v in viols)

   def TestCheckBytesLfClean(self, tmp_path):
      raw = b"x = 1\ny = 2\n"
      assert CheckBytes(raw, tmp_path / "f.py") == []

   def TestCheckBytesEmptyFile(self, tmp_path):
      assert CheckBytes(b"", tmp_path / "f.py") == []

   def TestCheckBytesBom(self, tmp_path):
      raw = UTF8_BOM + b"x = 1\n"
      viols = CheckBytes(raw, tmp_path / "f.py")
      assert any(v.code == RULE_CF012 for v in viols)
      assert any("BOM" in v.message for v in viols)

   def TestCheckBytesInvalidUtf8(self, tmp_path):
      raw = b"x = \xff\nbroken\n"
      viols = CheckBytes(raw, tmp_path / "f.py")
      assert any(v.code == RULE_CF012 for v in viols)
      assert any("UTF-8" in v.message for v in viols)

   def TestCheckBytesInvalidUtf8SkipsCf011(self, tmp_path):
      # Invalid UTF-8 that also has CRLF should only get CF012,
      # not CF011, because line-ending detection is skipped on bad bytes.
      raw = b"x = \xff\r\nbroken\r\n"
      viols = CheckBytes(raw, tmp_path / "f.py")
      codes = {v.code for v in viols}
      assert RULE_CF012 in codes
      assert RULE_CF011 not in codes

   def TestCheckBytesViolationLineCol(self, tmp_path):
      raw = b"x = 1\r\n"
      viols = CheckBytes(raw, tmp_path / "f.py")
      cf011 = [v for v in viols if v.code == RULE_CF011]
      assert cf011[0].line == 1
      assert cf011[0].col == 1

   def TestFixTextCrlf(self):
      assert FixText("a\r\nb\r\n") == "a\nb\n"

   def TestFixTextCrOnly(self):
      assert FixText("a\rb\r") == "a\nb\n"

   def TestFixTextMixed(self):
      assert FixText("a\r\nb\rc\n") == "a\nb\nc\n"

   def TestFixTextLfUnchanged(self):
      text = "a\nb\n"
      assert FixText(text) == text

   def TestFixTextIdempotent(self):
      text = "a\r\nb\r\n"
      assert FixText(FixText(text)) == FixText(text)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


class TestIoHelpers:
   def TestReadUtf8TextValid(self, tmp_path):
      f = tmp_path / "f.py"
      f.write_bytes(b"hello\n")
      assert ReadUtf8Text(f) == "hello\n"

   def TestReadUtf8TextBomRaises(self, tmp_path):
      f = tmp_path / "f.py"
      f.write_bytes(UTF8_BOM + b"hello\n")
      with pytest.raises(ValueError, match="BOM"):
         ReadUtf8Text(f)

   def TestReadUtf8TextBadBytesRaises(self, tmp_path):
      f = tmp_path / "f.py"
      f.write_bytes(b"hello\xff\n")
      with pytest.raises(UnicodeDecodeError):
         ReadUtf8Text(f)

   def TestWriteUtf8LfNormalises(self, tmp_path):
      f = tmp_path / "f.py"
      WriteUtf8Lf(f, "a\r\nb\r\n")
      assert f.read_bytes() == b"a\nb\n"

   def TestWriteUtf8LfRoundTrip(self, tmp_path):
      f = tmp_path / "f.py"
      text = "hello\nworld\n"
      WriteUtf8Lf(f, text)
      assert ReadUtf8Text(f) == text


# ---------------------------------------------------------------------------
# Formatter pipeline
# ---------------------------------------------------------------------------


class TestFormatterPipeline:
   def TestProcessFileCrlfFixed(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\r\ny = 2\r\n")
      changed, _, _ = ProcessFile(f)
      assert changed
      assert b"\r" not in f.read_bytes()

   def TestProcessFileCrOnlyFixed(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\ry = 2\r")
      changed, _, _ = ProcessFile(f)
      assert changed
      assert b"\r" not in f.read_bytes()

   def TestProcessFileLfUnchanged(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\ny = 2\n")
      changed, _, _ = ProcessFile(f)
      assert not changed

   def TestProcessFileCheckCrlf(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\r\n")
      changed, _, viols = ProcessFile(f, check_only=True)
      assert changed
      assert any(v.code == RULE_CF011 for v in viols)
      # File must NOT be modified in check_only mode
      assert b"\r\n" in f.read_bytes()

   def TestProcessFileBomRaises(self, tmp_path):
      f = Write(tmp_path / "f.py", UTF8_BOM + b"x = 1\n")
      with pytest.raises(ValueError, match="BOM"):
         ProcessFile(f)

   def TestProcessFileBadUtf8Raises(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = \xff\n")
      with pytest.raises(UnicodeDecodeError):
         ProcessFile(f)


# ---------------------------------------------------------------------------
# Checker pipeline
# ---------------------------------------------------------------------------


class TestCheckerPipeline:
   def TestCheckFileCf011Crlf(self, tmp_path):
      f = Write(tmp_path / "my_module.py", b"X = 1\r\n")
      viols = CheckFile(f)
      assert any(v.code == RULE_CF011 for v in viols)

   def TestCheckFileCf012Bom(self, tmp_path):
      f = Write(tmp_path / "my_module.py", UTF8_BOM + b"X = 1\n")
      viols = CheckFile(f)
      assert any(v.code == RULE_CF012 for v in viols)

   def TestCheckFileCf012BadUtf8(self, tmp_path):
      f = Write(tmp_path / "my_module.py", b"x = \xff\n")
      viols = CheckFile(f)
      assert any(v.code == RULE_CF012 for v in viols)

   def TestCheckFileBadUtf8SkipsAst(self, tmp_path):
      # Invalid UTF-8 must not crash; AST-based rules must be skipped.
      f = Write(tmp_path / "my_module.py", b"x = \xff\n")
      viols = CheckFile(f)
      codes = {v.code for v in viols}
      assert RULE_CF012 in codes
      # CF001–CF010 must not appear — they require a decoded source.
      ast_codes = {f"CF{n:03d}" for n in range(1, 11)}
      assert not (codes & ast_codes)

   def TestCheckFileBomStillRunsAst(self, tmp_path):
      # A BOM file is still valid UTF-8 after stripping — AST rules run.
      # The file uses 4-space indent so CF010 should fire alongside CF012.
      src = UTF8_BOM + b"def Foo():\n    pass\n"
      f = Write(tmp_path / "my_module.py", src)
      viols = CheckFile(f)
      codes = {v.code for v in viols}
      assert RULE_CF012 in codes
      assert "CF010" in codes


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCliIntegration:
   def TestFixCrlfExits0(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\r\n")
      rc = RunMain("fix", str(f))
      assert rc == 0
      assert b"\r" not in f.read_bytes()

   def TestFixCrlfQuietExits0(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\r\n")
      rc = RunMain("fix", "--quiet", str(f))
      assert rc == 0
      assert b"\r" not in f.read_bytes()

   def TestFixCheckCrlfExits1(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = 1\r\n")
      rc = RunMain("fix", "--check", str(f))
      assert rc == 1
      # File untouched in --check mode
      assert b"\r\n" in f.read_bytes()

   def TestFixBadUtf8Exits2(self, tmp_path):
      f = Write(tmp_path / "f.py", b"x = \xff\n")
      rc = RunMain("fix", str(f))
      assert rc == 2

   def TestFixBomExits2(self, tmp_path):
      f = Write(tmp_path / "f.py", UTF8_BOM + b"x = 1\n")
      rc = RunMain("fix", str(f))
      assert rc == 2

   def TestCheckCf011Exits1(self, tmp_path):
      f = Write(tmp_path / "my_module.py", b"X = 1\r\n")
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestCheckCf012BomExits1(self, tmp_path):
      f = Write(tmp_path / "my_module.py", UTF8_BOM + b"X = 1\n")
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestCheckCf012BadUtf8Exits1(self, tmp_path):
      f = Write(tmp_path / "my_module.py", b"x = \xff\n")
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestCheckLfCleanExits0(self, tmp_path):
      f = Write(tmp_path / "my_module.py", b"X = 1\n")
      rc = RunMain("check", str(f))
      assert rc == 0
